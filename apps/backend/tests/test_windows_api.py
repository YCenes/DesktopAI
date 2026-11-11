from dataclasses import asdict
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from nova.api.app import create_app
from nova.application.windows_commands import command_action
from nova.infrastructure.config import Settings
from nova.domain.tasks import TaskError
from test_windows_apps import make_action


AUTH={'Authorization':'Bearer '+'c'*64}


@pytest.fixture
def client(tmp_path):
    app=create_app(Settings('c'*64,43210,task_database=tmp_path/'tasks.sqlite3'))
    with TestClient(app,base_url='http://127.0.0.1:43210',headers=AUTH) as c:yield c


@pytest.mark.parametrize('text,tool',[('Not Defteri’ni aç','windows.open_app'),('Notepad aç','windows.open_app'),
    ('dosya ara rapor','windows.search_files'),("web'de ara Türkçe hava durumu",'windows.web_search')])
def test_deterministic_command_mapping(text,tool):
    a=command_action(text,str(uuid4()),str(uuid4()),('test',))
    assert a.tool_id==tool


@pytest.mark.parametrize('text',["Chrome'u aç",'calc.exe /c evil aç',"Notepad aç ve dosya sil",'belki Notepad aç','Python nedir?','2 + 2 kaç?'])
def test_unknown_ambiguous_or_chat_cannot_execute(text):
    with pytest.raises(TaskError):command_action(text,str(uuid4()),str(uuid4()),('test',))


def test_no_root_or_multiple_roots_require_explicit_selection():
    for roots in [(),('one','two')]:
        with pytest.raises(TaskError):command_action('dosya ara rapor',str(uuid4()),str(uuid4()),roots)


def test_api_default_denial_persisted_and_fake_channel_rejects_real(client):
    a=asdict(make_action())
    v=client.post('/api/v1/windows/tasks',json=a)
    assert v.status_code==200 and v.json()['status']=='failed' and v.json()['simulated'] is False
    assert client.get('/api/v1/windows/tasks').json()['tasks'][0]['error_code']=='PERMISSION_DENIED'
    assert client.get('/api/v1/tasks').json()['tasks']==[]
    assert client.post('/api/v1/tasks',json=a).status_code==422
    path='/api/v1/tasks/'+a['task_id']
    assert client.get(path).status_code==403
    assert client.post(path+'/cancel').status_code==403
    assert client.post(path+'/reconcile').status_code==403
    assert client.post(path+'/approval',json={'approval_id':str(uuid4()),'approve':True,'source':'screen'}).status_code==403


@pytest.mark.parametrize('method,path',[('POST','/commands'),('POST','/tasks'),('GET','/tasks'),('GET','/tasks/id'),('POST','/tasks/id/approval'),('POST','/tasks/id/cancel')])
@pytest.mark.parametrize('auth',[None,'Bearer invalid'])
def test_all_windows_api_auth_boundaries(client,method,path,auth):
    client.headers.pop('authorization',None)
    r=client.request(method,'/api/v1/windows'+path,headers={} if auth is None else {'Authorization':auth},json={})
    assert r.status_code==401


def test_api_command_rejection_does_not_create_task(client):
    payload={'task_id':str(uuid4()),'action_id':str(uuid4()),'text':"Chrome'u aç"}
    r=client.post('/api/v1/windows/commands',json=payload)
    assert r.status_code==403 and r.json()['error_code']=='APP_NOT_ALLOWED'
    assert client.get('/api/v1/windows/tasks').json()['tasks']==[]


def test_old_fake_task_cannot_be_approved_through_windows_api(client):
    from test_tasks import action
    v=client.post('/api/v1/tasks',json=asdict(action(True))).json()
    path='/api/v1/windows/tasks/'+v['action']['task_id']+'/approval'
    r=client.post(path,json={'approval_id':v['approval']['approval_id'],'approve':True,'source':'screen'})
    assert r.status_code==403 and r.json()['error_code']=='TASK_KIND_DENIED'


def test_host_origin_and_body_limits_on_windows_route(client):
    for headers,code in [({'Host':'evil.example'},400),({'Origin':'http://localhost'},403)]:
        assert client.post('/api/v1/windows/tasks',json={},headers=headers).status_code==code
    assert client.post('/api/v1/windows/tasks',content=b' '*16385).status_code==413
