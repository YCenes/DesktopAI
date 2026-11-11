from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import time
from uuid import uuid4

import pytest

from nova.application.tasks import TaskService
from nova.application.tools import ToolRegistry
from nova.domain.tasks import ActionRequest, RegisteredAppArguments, TaskError
from nova.infrastructure.windows_tools import WindowsTools


class NativeDouble:
    def __init__(self,path):self.path=path;self.calls=[];self.locked=False
    def windows_directory(self):return self.path
    @contextmanager
    def guarded(self,path):
        self.locked=True
        try:yield None
        finally:self.locked=False
    def launch_notepad(self,image,document=None):
        assert self.locked
        self.calls.append((image,document));return 123


def make_action():
    return ActionRequest(str(uuid4()),str(uuid4()),'windows.open_app',RegisteredAppArguments('windows.notepad'),'windows.apps')


@pytest.fixture
def real_service(tmp_path):
    image=tmp_path/'System32'/'notepad.exe';image.parent.mkdir();image.write_bytes(b'synthetic executable fixture; never executed')
    config=tmp_path/'config.json';config.write_text(json.dumps({'enabled_apps':['windows.notepad'],'notepad_sha256':hashlib.sha256(image.read_bytes()).hexdigest()}))
    native=NativeDouble(tmp_path)
    s=TaskService(tmp_path/'tasks.sqlite3',registry=ToolRegistry(WindowsTools(config,native)))
    yield s,native,image
    s.close()


def test_real_registered_app_requires_approval_and_launches_once(real_service):
    s,native,_=real_service;a=make_action();v=s.create(a)
    assert v['status']=='awaiting_approval' and not native.calls
    v=s.respond(a.task_id,v['approval']['approval_id'],True)
    assert v['status']=='succeeded' and v['simulated'] is False
    assert '123' in v['result']['message'] and 'doğrulanmadı' in v['result']['message']
    assert s.create(a)==v and len(native.calls)==1
    with pytest.raises(TaskError):s.respond(a.task_id,s.store.conn.execute('SELECT approval_id FROM approvals').fetchone()[0],True)
    assert len(native.calls)==1


@pytest.mark.parametrize('app',['cmd.exe','powershell','C:/Windows/notepad.exe','windows.notepad /c evil','unknown'])
def test_unregistered_and_argument_injection(real_service,app):
    s,native,_=real_service
    with pytest.raises(TaskError):s.create(replace(make_action(),arguments=RegisteredAppArguments(app)))
    assert not native.calls


def test_identity_change_after_approval_denies_launch(real_service):
    s,native,image=real_service;a=make_action();v=s.create(a)
    image.write_bytes(b'changed synthetic file')
    with pytest.raises(TaskError):s.respond(a.task_id,v['approval']['approval_id'],True)
    assert not native.calls


def test_default_deny_without_configuration(tmp_path):
    s=TaskService(tmp_path/'db.sqlite3',registry=ToolRegistry(WindowsTools()))
    try:
        v=s.create(make_action())
        assert v['status']=='failed' and v['error_code']=='PERMISSION_DENIED'
    finally:s.close()


def test_launch_failure_and_uncertain_outcome_are_distinct(real_service,monkeypatch):
    s,native,_=real_service
    def failed(*a):raise TaskError('APP_LAUNCH_FAILED','Başlatılamadı.')
    monkeypatch.setattr(native,'launch_notepad',failed)
    a=make_action();v=s.create(a);v=s.respond(a.task_id,v['approval']['approval_id'],True)
    assert v['status']=='failed'
    def uncertain(*a):raise RuntimeError('private implementation detail')
    monkeypatch.setattr(native,'launch_notepad',uncertain)
    a=make_action();v=s.create(a);v=s.respond(a.task_id,v['approval']['approval_id'],True)
    assert v['status']=='unknown' and v['result'] is None
    assert s.create(a)['status']=='unknown'


def test_no_app_started_for_expired_or_denied_approval(real_service):
    s,native,_=real_service;a=make_action();v=s.create(a)
    s.execution.clock=lambda:v['approval']['expires_at']+1
    with pytest.raises(TaskError):s.respond(a.task_id,v['approval']['approval_id'],True)
    assert not native.calls


def test_real_journal_restart_unknown_and_no_fake_reconciliation(real_service,monkeypatch):
    s,native,image=real_service;a=make_action();v=s.create(a)
    s.execution.respond(a.task_id,v['approval']['approval_id'],True)
    class InterruptedNative(BaseException):pass
    def interrupted(*args):native.calls.append(('interrupted',None));raise InterruptedNative()
    monkeypatch.setattr(native,'launch_notepad',interrupted)
    with pytest.raises(InterruptedNative):s.execution.execute(a.task_id,time.monotonic()+5)
    # Aynı store recovery sınırı yeni session ile çağrılır; eski action yeniden yürütülmez.
    s.store.recover('new-test-session')
    assert s.view(a.task_id)['status']=='unknown'
    s.run(a.task_id)
    assert len(native.calls)==1
    with pytest.raises(TaskError):s.reconcile(a.task_id)


def test_native_process_uses_fixed_application_and_no_shell(monkeypatch,tmp_path):
    from nova.infrastructure.windows_native import WindowsNative
    import nova.infrastructure.windows_native as module
    import types
    calls=[]
    def spawn(args,**kwargs):calls.append((args,kwargs));return types.SimpleNamespace(pid=1234)
    monkeypatch.setattr(module.subprocess,'Popen',spawn)
    native=WindowsNative();image=tmp_path/'notepad.exe'
    assert native.launch_notepad(image)==1234
    assert calls[0][0]==[str(image)] and calls[0][1]['executable']==str(image)
    assert calls[0][1]['shell'] is False and calls[0][1]['close_fds'] is True
