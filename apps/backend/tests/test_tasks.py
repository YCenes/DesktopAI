"""Yalnızca temporary SQLite, sentetik eylemler ve fake adapter'lar."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace, FrozenInstanceError
from pathlib import Path
import json
import os
import socket
import sqlite3
import subprocess
import threading
import time
import sys
from uuid import uuid4

import pytest

from nova.application.tasks import TaskService
from nova.application.tools import ToolRegistry, PermissionService
from nova.domain.tasks import ActionRequest, OpenAppArguments, SearchFilesArguments, TaskError, ExecutionResult
from nova.infrastructure.task_store import TaskStore
from nova.infrastructure.task_runtime import TaskRuntime


def action(high=False):
    return ActionRequest(str(uuid4()), str(uuid4()), "fake.open_app" if high else "fake.search_files",
        OpenAppArguments("demo.editor") if high else SearchFilesArguments("rapor", "synthetic.documents"),
        "simulation.apps" if high else "simulation.files")


@pytest.fixture
def service(tmp_path):
    s = TaskService(tmp_path / "tasks.sqlite3")
    yield s
    s.close()


def code(expected, call):
    with pytest.raises(TaskError) as error:
        call()
    assert error.value.code == expected


@pytest.mark.parametrize("change,expected", [
    ({"tool_id": "windows.open_app"}, "TOOL_UNKNOWN"),
    ({"tool_id": "__import__('os')"}, "TOOL_UNKNOWN"),
    ({"scope": "host.all"}, "SCOPE_DENIED"),
    ({"arguments": OpenAppArguments("C:/Windows/cmd.exe")}, "ARGUMENTS_INVALID"),
    ({"arguments": {"query": "rapor", "root_id": "synthetic.documents"}}, "ARGUMENTS_INVALID"),
    ({"arguments": SearchFilesArguments("../private", "synthetic.documents")}, "ARGUMENTS_INVALID"),
    ({"arguments": SearchFilesArguments("rapor", "C:/Users")}, "ARGUMENTS_INVALID"),
    ({"task_id": "../../bad"}, "INVALID_ACTION"),
])
def test_default_deny_and_invalid_actions(service, change, expected):
    invalid = replace(action(), **change)
    assert service.policy.evaluate(invalid).decision == "deny"
    code(expected, lambda: service.create(invalid))
    assert service.list_tasks() == []


def test_argument_schema_exact_and_immutable(service):
    a = action()
    with pytest.raises(FrozenInstanceError):
        a.scope = "host.all"
    payload = asdict(a); payload["arguments"]["command"] = "calc.exe"
    code("ARGUMENTS_INVALID", lambda: service.registry.from_dict(payload))
    payload = asdict(a); payload["executable"] = True
    code("INVALID_ACTION", lambda: service.registry.from_dict(payload))


def test_allow_fake_execution_and_ordered_events(service):
    a = action(); view = service.create(a)
    assert view["status"] == "succeeded"
    assert view["result"]["simulated"] is True
    assert view["external_calls"] == 0
    assert [e["sequence"] for e in view["events"]] == list(range(1, 6))
    assert [e["kind"] for e in view["events"]][-2:] == ["execution_intent", "execution_result"]
    assert service.store.conn.execute("SELECT state FROM execution_journal").fetchone()[0] == "succeeded"


def test_high_risk_requires_trusted_approval(service):
    a = action(True); view = service.create(a)
    assert view["status"] == "awaiting_approval"
    assert view["approval"]["action"] == asdict(a)
    assert view["approval"]["risk"] == "high"
    assert not service.store.conn.execute("SELECT 1 FROM execution_journal").fetchone()
    code("APPROVAL_REQUIRED", lambda: service.execution.execute(a.task_id, time.monotonic()+5))
    approved = service.respond(a.task_id, view["approval"]["approval_id"], True)
    assert approved["status"] == "succeeded"
    assert approved["approval"] is None
    code("APPROVAL_REPLAY", lambda: service.respond(a.task_id, view["approval"]["approval_id"], True))


def test_reject_has_no_execution(service):
    a = action(True); v = service.create(a)
    assert service.respond(a.task_id, v["approval"]["approval_id"], False)["status"] == "cancelled"
    assert service.store.conn.execute("SELECT COUNT(*) FROM execution_journal").fetchone()[0] == 0


@pytest.mark.parametrize("column,value,expected", [
    ("expires_at", 0, "APPROVAL_EXPIRED"),
    ("specification", "modified arguments", "APPROVAL_MISMATCH"),
    ("session_id", "other-session", "APPROVAL_MISMATCH"),
    ("policy_version", "old-policy", "APPROVAL_POLICY_CHANGED"),
    ("action_id", str(uuid4()), "APPROVAL_MISMATCH"),
])
def test_binding_expiry_and_modified_record(service, column, value, expected):
    a = action(True); v = service.create(a)
    # Sütun adı testin sabit parametrelerinden gelir; public SQL girişi yoktur.
    service.store.conn.execute(f"UPDATE approvals SET {column}=?", (value,))
    code(expected, lambda: service.respond(a.task_id, v["approval"]["approval_id"], True))
    assert service.store.conn.execute("SELECT COUNT(*) FROM execution_journal").fetchone()[0] == 0


def test_changed_policy_after_grant_prevents_adapter(service):
    a = action(True); v = service.create(a)
    service.execution.respond(a.task_id, v["approval"]["approval_id"], True)
    service.policy.version = "fake-policy-2"
    code("APPROVAL_POLICY_CHANGED", lambda: service.execution.execute(a.task_id, time.monotonic()+5))


def test_expired_after_grant_is_rechecked(service):
    a = action(True); v = service.create(a)
    service.execution.respond(a.task_id, v["approval"]["approval_id"], True)
    service.execution.clock = lambda: v["approval"]["expires_at"] + 1
    code("APPROVAL_EXPIRED", lambda: service.execution.execute(a.task_id, time.monotonic()+5))


def test_cross_task_and_fabricated_approval(service):
    a, b = action(True), action(True)
    va = service.create(a); service.create(b)
    code("APPROVAL_MISMATCH", lambda: service.respond(b.task_id, va["approval"]["approval_id"], True))
    code("APPROVAL_MISMATCH", lambda: service.respond(a.task_id, str(uuid4()), True))


def test_approve_cannot_enable_unsupported_capability(service, monkeypatch):
    a = action(True); v = service.create(a)
    original = service.policy.evaluate
    monkeypatch.setattr(service.policy, "evaluate", lambda a: replace(original(a), decision="deny"))
    code("PERMISSION_DENIED", lambda: service.respond(a.task_id, v["approval"]["approval_id"], True))


def test_policy_rechecked_immediately_before_execution(service, monkeypatch):
    a = action(); service.create(a, run=False)
    with service.store.transaction() as db:
        service.store.transition(db, a.task_id, "running", "test_validate")
    original = service.policy.evaluate; count = 0
    def changing(a):
        nonlocal count
        count += 1
        return replace(original(a), decision="deny") if count > 1 else original(a)
    monkeypatch.setattr(service.policy, "evaluate", changing)
    code("PERMISSION_CHANGED", lambda: service.execution.execute(a.task_id, time.monotonic()+5))
    assert service.store.conn.execute("SELECT COUNT(*) FROM execution_journal").fetchone()[0] == 0


def test_duplicate_action_id_is_idempotent_but_changed_spec_rejected(service):
    a = action(); first = service.create(a)
    assert service.create(a) == first
    code("ACTION_ID_CONFLICT", lambda: service.create(replace(a, task_id=str(uuid4()))))
    code("ACTION_ID_CONFLICT", lambda: service.create(replace(a, arguments=SearchFilesArguments("ornek", "synthetic.documents"))))
    assert service.store.conn.execute("SELECT COUNT(*) FROM execution_journal").fetchone()[0] == 1


def test_concurrent_duplicate_submissions(service, monkeypatch):
    a = action(); calls = []
    original = service.registry.simulate
    monkeypatch.setattr(service.registry, "simulate", lambda action: (calls.append(action.action_id), original(action))[1])
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: service.create(a), range(12)))
    assert all(v["action"]["action_id"] == a.action_id for v in results)
    assert calls == [a.action_id]
    assert service.view(a.task_id)["status"] == "succeeded"


def test_concurrent_direct_execution_uses_durable_journal(service, monkeypatch):
    a = action(); service.create(a, run=False)
    with service.store.transaction() as db:
        service.store.transition(db, a.task_id, "running", "validated")
    started, release = threading.Event(), threading.Event(); calls = []
    original = service.registry.simulate
    def blocked(a):
        calls.append(a.action_id); started.set(); assert release.wait(3)
        return original(a)
    monkeypatch.setattr(service.registry, "simulate", blocked)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(service.execution.execute, a.task_id, time.monotonic()+5)
        assert started.wait(2)
        code("EXECUTION_ALREADY_RECORDED", lambda: service.execution.execute(a.task_id, time.monotonic()+5))
        release.set(); first.result()
    assert calls == [a.action_id]


def test_sqlite_rollback_and_immutable_spec(service):
    a = action(); service.create(a, run=False)
    with pytest.raises(RuntimeError):
        with service.store.transaction() as db:
            service.store.transition(db, a.task_id, "running", "should_rollback")
            raise RuntimeError("synthetic failure")
    assert service.view(a.task_id)["status"] == "queued"
    assert len(service.view(a.task_id)["events"]) == 1
    with pytest.raises(sqlite3.IntegrityError):
        service.store.conn.execute("UPDATE tasks SET spec='modified'")


def test_grant_consumption_rolls_back_if_intent_cannot_commit(service):
    a = action(True); v = service.create(a)
    service.execution.respond(a.task_id, v["approval"]["approval_id"], True)
    service.store.conn.execute("CREATE TRIGGER reject_journal BEFORE INSERT ON execution_journal BEGIN SELECT RAISE(ABORT,'test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.execution.execute(a.task_id, time.monotonic()+5)
    assert service.store.conn.execute("SELECT state FROM approvals").fetchone()[0] == "granted"
    assert service.view(a.task_id)["status"] == "awaiting_approval"


def test_restart_after_crash_requires_reconciliation(tmp_path):
    class SimulatedCrash(BaseException): pass
    path = tmp_path / 'history.sqlite3'; s = TaskService(path)
    a = action(); s.create(a, run=False)
    with s.store.transaction() as db:
        s.store.transition(db, a.task_id, "running", "validated")
    s.registry.simulate = lambda a: (_ for _ in ()).throw(SimulatedCrash())
    with pytest.raises(SimulatedCrash):
        s.execution.execute(a.task_id, time.monotonic()+5)
    s.close()
    recovered = TaskService(path)
    try:
        assert recovered.view(a.task_id)["status"] == "unknown"
        recovered.run(a.task_id)
        assert recovered.view(a.task_id)["status"] == "unknown"
        assert recovered.reconcile(a.task_id)["error_code"] == "RECONCILED_NO_RETRY"
        assert recovered.store.conn.execute("SELECT COUNT(*) FROM execution_journal").fetchone()[0] == 1
    finally: recovered.close()


def test_restart_invalidates_pending_approval_and_preserves_history(tmp_path):
    path = tmp_path/'history.sqlite3'; s = TaskService(path)
    low = action(); high = action(True)
    s.create(low); view = s.create(high); s.close()
    s = TaskService(path)
    try:
        assert s.view(low.task_id)["status"] == "succeeded"
        assert s.view(high.task_id)["status"] == "cancelled"
        code("TASK_SESSION_INVALID", lambda: s.respond(high.task_id, view["approval"]["approval_id"], True))
        code("ACTION_ID_CONFLICT", lambda: s.create(high))
    finally:s.close()


def test_checkpoint_resume_after_graph_recreation(tmp_path):
    path=tmp_path/'tasks.sqlite3'; s=TaskService(path, session_id='synthetic-session')
    a=action(True); v=s.create(a)
    assert s.workflow.graph.get_state({'configurable':{'thread_id':a.task_id}}).next == ('await_approval',)
    s.close(); s=TaskService(path, session_id='synthetic-session')
    try:
        assert s.respond(a.task_id,v['approval']['approval_id'],True)['status']=='succeeded'
        assert s.store.conn.execute('SELECT COUNT(*) FROM execution_journal').fetchone()[0]==1
    finally:s.close()


@pytest.mark.parametrize('limits,expected', [({'timeout':0},'WORKFLOW_TIMEOUT'),({'max_steps':1},'WORKFLOW_STEP_LIMIT')])
def test_graph_limits(service, limits, expected):
    a=action(); service.create(a,run=False); service.run(a.task_id,**limits)
    assert service.view(a.task_id)['error_code']==expected
    assert service.store.conn.execute('SELECT COUNT(*) FROM execution_journal').fetchone()[0]==0


def test_cancellation_before_execution(service):
    a=action(); service.create(a,run=False)
    assert service.cancel(a.task_id)['status']=='cancelled'
    service.run(a.task_id)
    assert service.view(a.task_id)['status']=='cancelled'
    assert service.store.conn.execute('SELECT COUNT(*) FROM execution_journal').fetchone()[0]==0


def test_cancellation_during_execution_is_unknown(service, monkeypatch):
    a=action()
    original=service.registry.simulate
    def cancel_during(a):
        service.cancel(a.task_id)
        return original(a)
    monkeypatch.setattr(service.registry,'simulate',cancel_during)
    assert service.create(a)['status']=='unknown'
    assert service.reconcile(a.task_id)['status']=='failed'


def test_tool_error_distinct_from_cancel_unknown(service, monkeypatch):
    def fail(a):raise ValueError('synthetic secret should never escape')
    monkeypatch.setattr(service.registry,'simulate',fail)
    v=service.create(action())
    assert v['status']=='failed' and v['error_code']=='TOOL_ERROR'
    assert 'secret' not in json.dumps(v)


def test_state_transition_and_reconciliation_boundaries(service):
    a=action(); service.create(a)
    code('TASK_STATE_CONFLICT',lambda:service.cancel(a.task_id))
    code('RECONCILIATION_DENIED',lambda:service.reconcile(a.task_id))
    with service.store.transaction() as db:
        code('TASK_STATE_CONFLICT',lambda:service.store.transition(db,a.task_id,'running','invalid'))


def test_migration_versions_and_reopen(tmp_path):
    path=tmp_path/'db.sqlite3'; store=TaskStore(path)
    assert store.conn.execute('PRAGMA user_version').fetchone()[0]==1
    store.migrate(); store.close()
    with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=99')
    code('SCHEMA_UNSUPPORTED',lambda:TaskStore(path))


def test_runtime_single_owner_and_release(tmp_path):
    path=tmp_path/'db.sqlite3'; a=TaskRuntime(path); b=TaskRuntime(path)
    try:
        a.get();code('TASK_STORE_BUSY',b.get)
        a.close();assert b.get() is not None
    finally:a.close();b.close()


def test_no_os_or_external_api_for_all_workflows(service, monkeypatch):
    import httpx
    import requests
    def forbidden(*args,**kwargs):pytest.fail('Fake workflow dış yetenek kullanamaz')
    monkeypatch.setattr(subprocess,'Popen',forbidden)
    monkeypatch.setattr(os,'system',forbidden)
    if hasattr(os,'startfile'):monkeypatch.setattr(os,'startfile',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(httpx.Client,'send',forbidden)
    monkeypatch.setattr(requests.Session,'send',forbidden)
    assert service.create(action())['status']=='succeeded'
    a=action(True);v=service.create(a)
    assert service.respond(a.task_id,v['approval']['approval_id'],True)['status']=='succeeded'
    assert os.environ['LANGSMITH_TRACING']=='false'


def test_real_process_crash_after_journal_commit(tmp_path):
    path=tmp_path/'process-crash.sqlite3'; marker=tmp_path/'started.marker'
    a=action()
    script='''
import json,sys,time
from pathlib import Path
from nova.application.tasks import TaskService
s=TaskService(Path(sys.argv[1]))
a=s.registry.from_dict(json.loads(sys.argv[3]))
def blocked(action):
    Path(sys.argv[2]).write_text('synthetic adapter entered',encoding='utf-8')
    time.sleep(30)
s.registry.simulate=blocked
s.create(a)
'''
    child=subprocess.Popen([sys.executable,'-c',script,str(path),str(marker),json.dumps(asdict(a))],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+15
        while not marker.exists() and child.poll() is None and time.monotonic()<deadline:
            time.sleep(.05)
        assert marker.exists(),'Fake adapter journal commit sonrasında başlamalı'
        child.kill();child.wait(timeout=5)
        recovered=TaskService(path)
        try:
            assert recovered.view(a.task_id)['status']=='unknown'
            recovered.run(a.task_id)
            assert recovered.view(a.task_id)['status']=='unknown'
            assert recovered.store.conn.execute('SELECT COUNT(*) FROM execution_journal').fetchone()[0]==1
        finally:recovered.close()
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=5)


def test_unknown_risk_metadata_is_default_deny(service):
    definition=service.registry._tools['fake.search_files']
    service.registry._tools['fake.search_files']=replace(definition,risk='unrecognized')
    assert service.policy.evaluate(action()).decision=='deny'


def test_timeout_after_adapter_is_unknown_not_success(service,monkeypatch):
    import types
    import nova.application.execution as module
    late=False
    monkeypatch.setattr(module,'time',types.SimpleNamespace(monotonic=lambda:200 if late else 10))
    original=service.registry.simulate
    def adapter(a):
        nonlocal late
        late=True
        return original(a)
    monkeypatch.setattr(service.registry,'simulate',adapter)
    a=action();service.create(a,run=False)
    with service.store.transaction() as db:service.store.transition(db,a.task_id,'running','validated')
    service.execution.execute(a.task_id,100)
    assert service.view(a.task_id)['status']=='unknown'
    assert service.view(a.task_id)['result'] is None
