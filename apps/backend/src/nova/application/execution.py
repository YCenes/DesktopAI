"""Fake adapter için tek yetkili execution girişi; journal otoritedir."""
from dataclasses import asdict
import json
import time
from uuid import uuid4
import queue
import threading

from nova.application.tools import PermissionService, ToolRegistry
from nova.domain.tasks import ActionRequest, ApprovalGrant, ExecutionResult, TaskError, TERMINAL
from nova.infrastructure.task_store import TaskStore


class ExecutionService:
    def __init__(self, store: TaskStore, registry: ToolRegistry, policy: PermissionService, session_id: str, clock=time.time):
        self.store, self.registry, self.policy = store, registry, policy
        self.session_id, self.clock = session_id, clock
        self.approval_ttl = 120
        self.native_timeout = 3.0

    def dispatch(self,action,deadline):
        if action.tool_id.startswith('fake.'):
            return self.registry.execute(action,deadline)
        # Native çağrı takılırsa bounded caller unknown kaydeder; thread zorla sonlandırılmaz.
        response=queue.Queue(maxsize=1)
        def worker():
            try:response.put((self.registry.execute(action,deadline),None))
            except BaseException as error:response.put((None,error))
        threading.Thread(target=worker,daemon=True,name='nova-native-dispatch').start()
        try:result,error=response.get(timeout=max(0,min(self.native_timeout,deadline-time.monotonic())))
        except queue.Empty:return ExecutionResult('unknown','Windows isteği süre içinde doğrulanamadı; otomatik tekrar yapılmaz.',False)
        if error is not None:raise error
        return result

    def action(self, row) -> ActionRequest:
        return self.registry.from_dict(json.loads(row["spec"]))

    def check_session(self, row):
        if row["session_id"] != self.session_id:
            raise TaskError("TASK_SESSION_INVALID", "Bu görev önceki oturuma ait; yeniden yürütülemez.", 403)

    def prepare(self, task_id: str):
        with self.store.transaction() as db:
            row = self.store.row(db, task_id)
            self.check_session(row)
            if row["status"] in TERMINAL:
                return
            action = self.action(row)
            decision = self.policy.evaluate(action)
            if decision.decision == "deny":
                self.store.transition(db, task_id, "failed", "permission_denied", "PERMISSION_DENIED")
            elif decision.decision == "require_approval":
                if row["status"] == "running":
                    db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?)", (
                        str(uuid4()), task_id, action.action_id, action.canonical(), self.session_id,
                        decision.policy_version, self.clock() + self.approval_ttl, "pending"))
                    self.store.transition(db, task_id, "awaiting_approval", "approval_requested")
            else:
                self.store.event(db, task_id, "permission_allowed")

    def respond(self, task_id: str, approval_id: str, approve: bool):
        with self.store.transaction() as db:
            row = self.store.row(db, task_id)
            self.check_session(row)
            record = db.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if record is None or record["task_id"] != task_id:
                raise TaskError("APPROVAL_MISMATCH", "Onay bu göreve ait değil.", 403)
            if record["state"] != "pending" or row["status"] != "awaiting_approval":
                raise TaskError("APPROVAL_REPLAY", "Bu onay daha önce kullanıldı veya geçersiz.")
            self._grant(record, row)
            if not approve:
                db.execute("UPDATE approvals SET state='rejected' WHERE approval_id=?", (approval_id,))
                self.store.transition(db, task_id, "cancelled", "approval_rejected", "APPROVAL_REJECTED")
                return
            if self.policy.evaluate(self.action(row)).decision != "require_approval":
                raise TaskError("PERMISSION_DENIED", "Güncel politika bu onaya izin vermiyor.", 403)
            db.execute("UPDATE approvals SET state='granted' WHERE approval_id=?", (approval_id,))
            self.store.event(db, task_id, "approval_granted")

    def _grant(self, record, row) -> ApprovalGrant:
        if (record["task_id"] != row["task_id"] or record["action_id"] != row["action_id"]
            or record["specification"] != row["spec"] or record["session_id"] != self.session_id):
            raise TaskError("APPROVAL_MISMATCH", "Onay eylem veya oturumla eşleşmiyor.", 403)
        if record["policy_version"] != self.policy.version:
            raise TaskError("APPROVAL_POLICY_CHANGED", "İzin politikası değişti; eski onay geçersiz.", 403)
        if record["expires_at"] <= self.clock():
            raise TaskError("APPROVAL_EXPIRED", "Onayın süresi doldu; yeni bir görev oluşturun.")
        return ApprovalGrant(record["approval_id"], record["task_id"], record["action_id"],
            record["session_id"], record["policy_version"], record["expires_at"], record["specification"])

    def execute(self, task_id: str, deadline: float):
        with self.store.transaction() as db:
            row = self.store.row(db, task_id)
            self.check_session(row)
            if row["status"] in TERMINAL:
                return
            if db.execute("SELECT 1 FROM execution_journal WHERE action_id=?", (row["action_id"],)).fetchone():
                raise TaskError("EXECUTION_ALREADY_RECORDED", "Eylem daha önce başlatıldı; tekrar yürütülmez.")
            if row["status"] not in ("running", "awaiting_approval"):
                raise TaskError("TASK_STATE_CONFLICT", "Eylem yürütmeye hazır değil.")
            if row["cancel_requested"]:
                self.store.transition(db, task_id, "cancelled", "cancelled_before_execution", "TASK_CANCELLED")
                return
            if time.monotonic() >= deadline:
                raise TaskError("WORKFLOW_TIMEOUT", "Görev süre sınırını aştı.")
            action = self.action(row)
            self.registry.validate(action)
            decision = self.policy.evaluate(action)
            if decision.decision == "deny":
                raise TaskError("PERMISSION_DENIED", "Eylem güncel politikada reddedildi.", 403)
            if decision.decision == "require_approval":
                record = db.execute("SELECT * FROM approvals WHERE task_id=?", (task_id,)).fetchone()
                if record is None or record["state"] != "granted":
                    raise TaskError("APPROVAL_REQUIRED", "Eylem için açık ekran onayı gerekli.", 403)
                self._grant(record, row)
            # Journal ve grant tüketimi tek transaction: crash'te tekrar çalıştırılmaz.
            final = self.policy.evaluate(action)
            if final != decision:
                raise TaskError("PERMISSION_CHANGED", "Yürütme öncesinde izin değişti.", 403)
            if decision.decision == "require_approval":
                self._grant(record, row)
                db.execute("UPDATE approvals SET state='consumed' WHERE task_id=?", (task_id,))
            if row["status"] == "awaiting_approval":
                self.store.transition(db, task_id, "running", "execution_authorized")
            db.execute("INSERT INTO execution_journal VALUES (?,?,'started',NULL)", (action.action_id, task_id))
            self.store.event(db, task_id, "execution_intent")

        # DB transaction dışında adapter. İptal başladıktan sonraki etkileri geri almış sayılmaz.
        try:
            result = self.dispatch(action,deadline)
            if type(result) is not ExecutionResult or result.simulated != action.tool_id.startswith('fake.') or result.status not in ('succeeded','unknown'):
                raise ValueError("invalid fake result")
        except TaskError as error:
            result = ExecutionResult('failed',error.message,action.tool_id.startswith('fake.'))
        except Exception:
            if action.tool_id.startswith('fake.'):
                result = ExecutionResult("failed", "Simülasyon aracı hata verdi; gerçek Windows işlemi yapılmadı.")
            else:
                result = ExecutionResult('unknown','Windows işleminin sonucu doğrulanamadı; otomatik tekrar yapılmaz.',False)
        with self.store.transaction() as db:
            row = self.store.row(db, task_id)
            uncertain = row["cancel_requested"] or time.monotonic() >= deadline or result.status == 'unknown'
            status = "unknown" if uncertain else result.status
            code = "OUTCOME_UNKNOWN" if uncertain else ("TOOL_ERROR" if status == "failed" else None)
            public = None if uncertain else asdict(result)
            db.execute("UPDATE execution_journal SET state=?,result=? WHERE action_id=?",
                (status, json.dumps(public, ensure_ascii=False) if public else None, action.action_id))
            self.store.transition(db, task_id, status, "execution_result", code, public)

    def cancel(self, task_id):
        with self.store.transaction() as db:
            row = self.store.row(db, task_id)
            self.check_session(row)
            if row["status"] in TERMINAL:
                raise TaskError("TASK_STATE_CONFLICT", "Tamamlanmış görev iptal edilemez.")
            if row["cancel_requested"]:
                return
            db.execute("UPDATE tasks SET cancel_requested=1 WHERE task_id=?", (task_id,))
            journal = db.execute("SELECT 1 FROM execution_journal WHERE task_id=?", (task_id,)).fetchone()
            if journal:
                self.store.event(db, task_id, "cancellation_requested")
            else:
                db.execute("UPDATE approvals SET state='invalidated' WHERE task_id=?", (task_id,))
                self.store.transition(db, task_id, "cancelled", "cancelled_before_execution", "TASK_CANCELLED")

    def reconcile(self, task_id: str):
        # Fake etkileri yalnızca sabit sonuç üretir. Windows adapter'ı için kullanılamaz.
        with self.store.transaction() as db:
            row = self.store.row(db, task_id)
            action = self.action(row)
            if row["status"] != "unknown" or not action.tool_id.startswith("fake."):
                raise TaskError("RECONCILIATION_DENIED", "Yalnızca belirsiz simülasyon sonucu uzlaştırılabilir.")
            result = asdict(ExecutionResult("failed", "Simülasyon belirsiz olarak kapatıldı; eylem tekrar yürütülmedi."))
            db.execute("UPDATE execution_journal SET state='failed',result=? WHERE task_id=?", (json.dumps(result, ensure_ascii=False), task_id))
            self.store.transition(db, task_id, "failed", "reconciled_without_retry", "RECONCILED_NO_RETRY", result)
