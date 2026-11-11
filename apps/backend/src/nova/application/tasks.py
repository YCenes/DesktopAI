from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4

from nova.application.execution import ExecutionService
from nova.application.tools import ToolRegistry, PermissionService
from nova.domain.tasks import ActionRequest, ApprovalRequest, TaskError, TERMINAL, identifier
from nova.infrastructure.task_store import TaskStore
from nova.integrations.task_workflow import TaskWorkflow


class TaskService:
    def __init__(self, path: Path, session_id: str | None = None, registry=None, policy=None):
        self.session_id = session_id or str(uuid4())
        self.store = TaskStore(path)
        self.registry = registry or ToolRegistry()
        self.policy = policy or PermissionService(self.registry)
        self.execution = ExecutionService(self.store, self.registry, self.policy, self.session_id)
        self.workflow = TaskWorkflow(self.execution, path.with_name(path.stem + '-checkpoints.sqlite3'))
        self._workflow_lock = threading.Lock()
        self.store.recover(self.session_id)

    def create(self, action: ActionRequest, run=True):
        self.registry.validate(action)
        with self.store.transaction() as db:
            previous = db.execute("SELECT * FROM tasks WHERE task_id=? OR action_id=?", (action.task_id, action.action_id)).fetchone()
            if previous:
                if previous["spec"] != action.canonical() or previous["session_id"] != self.session_id:
                    raise TaskError("ACTION_ID_CONFLICT", "Görev veya eylem kimliği farklı bir istekte kullanılmış.")
                duplicate = True
            else:
                duplicate = False
                db.execute("INSERT INTO tasks(task_id,action_id,spec,session_id,status) VALUES (?,?,?,?,'queued')",
                    (action.task_id, action.action_id, action.canonical(), self.session_id))
                self.store.event(db, action.task_id, "task_created")
        if run and not duplicate:
            self.run(action.task_id)
        return self.view(action.task_id)

    def run(self, task_id, resume=False, **limits):
        if not self._workflow_lock.acquire(timeout=1):
            self.fail(task_id, "WORKFLOW_BUSY")
            return
        try:
            if self.view(task_id)["status"] in TERMINAL:
                return
            try:
                self.workflow.run(task_id, resume=resume, **limits)
            except TaskError as error:
                self.fail(task_id, error.code)
            except Exception:
                self.fail(task_id, "WORKFLOW_ERROR")
        finally:
            self._workflow_lock.release()

    def fail(self, task_id, code):
        with self.store.transaction() as db:
            row = self.store.row(db, task_id)
            if row["status"] in TERMINAL:
                return
            journal = db.execute("SELECT 1 FROM execution_journal WHERE task_id=?", (task_id,)).fetchone()
            status = "unknown" if journal else "failed"
            if journal:
                db.execute("UPDATE execution_journal SET state='unknown' WHERE task_id=?", (task_id,))
            self.store.transition(db, task_id, status, "workflow_stopped", "OUTCOME_UNKNOWN" if journal else code)

    def respond(self, task_id, approval_id, approve):
        identifier(task_id); identifier(approval_id)
        self.execution.respond(task_id, approval_id, approve)
        if approve:
            self.run(task_id, resume=True)
        return self.view(task_id)

    def view(self, task_id):
        identifier(task_id)
        with self.store.transaction() as db:
            row = self.store.row(db, task_id)
            action = self.execution.action(row)
            approval = db.execute("SELECT * FROM approvals WHERE task_id=? AND state='pending'", (task_id,)).fetchone()
            public_approval = None
            if approval:
                tool = self.registry.validate(action)
                public_approval = asdict(ApprovalRequest(approval["approval_id"], action, tool.risk,
                    tool.expected_effect, approval["expires_at"], approval["policy_version"]))
            events = [dict(e) for e in db.execute("SELECT sequence,kind,status,created_at FROM task_events WHERE task_id=? ORDER BY sequence", (task_id,))]
            return {"api_version": "1", "simulated": True, "external_calls": 0,
                "action": asdict(action), "status": row["status"],
                "result": json.loads(row["result"]) if row["result"] else None,
                "error_code": row["error_code"], "approval": public_approval, "events": events}

    def list_tasks(self):
        with self.store.transaction() as db:
            ids = [r[0] for r in db.execute("SELECT task_id FROM tasks ORDER BY rowid DESC LIMIT 20")]
        return [self.view(task_id) for task_id in ids]

    def cancel(self, task_id):
        identifier(task_id)
        self.execution.cancel(task_id)
        return self.view(task_id)

    def reconcile(self, task_id):
        identifier(task_id)
        self.execution.reconcile(task_id)
        return self.view(task_id)

    def close(self):
        self.workflow.close()
        self.store.close()
