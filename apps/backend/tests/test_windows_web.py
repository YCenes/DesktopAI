from dataclasses import replace
import hashlib
import json
import threading
from urllib.parse import parse_qs,urlsplit
from uuid import uuid4

import pytest

from nova.application.tasks import TaskService
from nova.application.tools import ToolRegistry
from nova.domain.tasks import ActionRequest,WebSearchArguments,TaskError
from nova.domain.web_search import search_url
from nova.infrastructure.windows_tools import WindowsTools
from test_windows_apps import NativeDouble


@pytest.mark.parametrize('query',['hava durumu İstanbul','C++ öğrenme & örnek','a=b & c# "tırnak"','Türkçe ıİşğü'])
def test_fixed_endpoint_and_encoding(query):
    url=urlsplit(search_url(query))
    assert (url.scheme,url.netloc,url.path)==('https','www.google.com','/search')
    assert parse_qs(url.query)=={'q':[query]}
    assert not url.fragment


@pytest.mark.parametrize('query',['',' ','x'*257,'https://evil.example','file:C:/a','javascript:alert(1)',
    'ms-settings:','cmd.exe:','foo\nbar','x\x00','a\u202eb','\\\\server\\a'])
def test_url_protocol_and_control_rejection(query):
    with pytest.raises(TaskError):search_url(query)


class BrowserDouble(NativeDouble):
    def default_browser(self):return self.path/'chrome.exe'
    def launch_search(self,image,url):
        assert self.locked;self.calls.append((image,url));return 321


@pytest.fixture
def web(tmp_path,monkeypatch):
    image=tmp_path/'chrome.exe';image.write_bytes(b'synthetic browser; never executed')
    monkeypatch.setenv('PROGRAMFILES',str(tmp_path))
    config=tmp_path/'config.json';config.write_text(json.dumps({'enable_web_search':True,'browser_sha256':hashlib.sha256(image.read_bytes()).hexdigest()}))
    native=BrowserDouble(tmp_path);tools=WindowsTools(config,native)
    s=TaskService(tmp_path/'tasks.sqlite3',registry=ToolRegistry(tools))
    yield s,native,image
    s.close()


def request(query='NOVA Windows geliştirme'):
    return ActionRequest(str(uuid4()),str(uuid4()),'windows.web_search',WebSearchArguments(query),'windows.web')


def test_web_requires_explicit_approval_and_discloses_external_service(web):
    s,native,_=web;a=request();v=s.create(a)
    assert v['status']=='awaiting_approval' and 'Google' in v['approval']['expected_effect'] and not native.calls
    v=s.respond(a.task_id,v['approval']['approval_id'],True)
    assert v['status']=='succeeded' and v['result']['details']['completion']=='search_submitted'
    assert native.calls[0][1]==search_url(a.arguments.query)
    with pytest.raises(TaskError):s.respond(a.task_id,'00000000-0000-0000-0000-000000000000',True)
    assert len(native.calls)==1


def test_unsafe_or_changed_browser_handler_is_denied(web,monkeypatch):
    s,native,image=web
    monkeypatch.setattr(native,'default_browser',lambda:image.with_name('cmd.exe'))
    assert s.create(request())['status']=='failed' and not native.calls


def test_browser_identity_change_after_approval(web):
    s,native,image=web;a=request();v=s.create(a);image.write_bytes(b'changed synthetic file')
    with pytest.raises(TaskError):s.respond(a.task_id,v['approval']['approval_id'],True)
    assert not native.calls


def test_bounded_native_dispatch_unknown_does_not_retry(web,monkeypatch):
    s,native,_=web;entered=threading.Event();release=threading.Event();calls=[]
    def blocked(image,url):
        calls.append(url);entered.set();release.wait(2);return 999
    monkeypatch.setattr(native,'launch_search',blocked)
    s.execution.native_timeout=.02
    a=request();v=s.create(a)
    try:
        v=s.respond(a.task_id,v['approval']['approval_id'],True)
        assert entered.is_set() and v['status']=='unknown'
        assert s.create(a)['status']=='unknown' and len(calls)==1
    finally:release.set()


def test_real_cancellation_before_and_during_dispatch(web,monkeypatch):
    s,native,_=web
    a=request();v=s.create(a);assert s.cancel(a.task_id)['status']=='cancelled'
    with pytest.raises(TaskError):s.respond(a.task_id,v['approval']['approval_id'],True)
    assert not native.calls
    a=request();v=s.create(a)
    def cancel_during(image,url):
        native.calls.append((image,url));s.cancel(a.task_id);return 888
    monkeypatch.setattr(native,'launch_search',cancel_during)
    result=s.respond(a.task_id,v['approval']['approval_id'],True)
    assert result['status']=='unknown' and result['error_code']=='OUTCOME_UNKNOWN'
    assert s.create(a)['status']=='unknown' and len(native.calls)==1
