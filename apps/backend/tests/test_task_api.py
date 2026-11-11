from dataclasses import asdict
import json
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from nova.api.app import create_app
from nova.infrastructure.config import Settings
from test_tasks import action


TOKEN='b'*64
AUTH={'Authorization':f'Bearer {TOKEN}'}


@pytest.fixture
def client(tmp_path):
    app=create_app(Settings(TOKEN,43210,task_database=tmp_path/'tasks.sqlite3'))
    with TestClient(app,base_url='http://127.0.0.1:43210',headers=AUTH) as c:
        yield c


def test_api_workflow_and_persisted_events(client):
    a=asdict(action(True));v=client.post('/api/v1/tasks',json=a)
    assert v.status_code==200
    v=v.json();assert v['status']=='awaiting_approval'
    assert v['approval']['action']==a
    path=f"/api/v1/tasks/{a['task_id']}"
    body={'approval_id':v['approval']['approval_id'],'approve':True,'source':'screen'}
    approved=client.post(path+'/approval',json=body)
    assert approved.status_code==200 and approved.json()['status']=='succeeded'
    assert client.get(path).json()==approved.json()
    assert client.get('/api/v1/tasks').json()['tasks']==[approved.json()]
    replay=client.post(path+'/approval',json=body)
    assert replay.status_code==409 and replay.json()['error_code']=='APPROVAL_REPLAY'
    assert TOKEN not in json.dumps(approved.json())


@pytest.mark.parametrize('method,suffix', [('POST',''),('GET',''),('GET','/id'),('POST','/id/approval'),('POST','/id/cancel'),('POST','/id/reconcile')])
@pytest.mark.parametrize('bad_auth',[None,'Bearer invalid'])
def test_task_auth_all_routes(client,method,suffix,bad_auth):
    headers={} if bad_auth is None else {'Authorization':bad_auth}
    client.headers.pop('authorization',None)
    r=client.request(method,'/api/v1/tasks'+suffix,headers=headers,json={})
    assert r.status_code==401 and r.json()['error_code']=='SESSION_UNAUTHORIZED'


@pytest.mark.parametrize('headers,status',[({'Host':'evil.example'},400),({'Origin':'tauri://localhost'},403)])
def test_task_host_origin(client,headers,status):
    assert client.post('/api/v1/tasks',json=asdict(action()),headers=headers).status_code==status


@pytest.mark.parametrize('change',[
    {'tool_id':'windows.open_app'}, {'scope':'host.all'},
    {'arguments':{'command':'calc.exe'}}, {'arguments':{'query':'rapor','root_id':'C:/Users'}},
    {'task_id':'../../private'}, {'arguments':{'query':'rapor','root_id':'synthetic.documents','extra':True}},
    {'executable':True},
])
def test_strict_api_arguments(client,change):
    payload={**asdict(action()),**change}
    r=client.post('/api/v1/tasks',json=payload)
    assert r.status_code==422 and r.json()['error_code']=='INVALID_REQUEST'
    assert client.get('/api/v1/tasks').json()['tasks']==[]


def test_approval_voice_fabrication_and_cross_task(client):
    a=client.post('/api/v1/tasks',json=asdict(action(True))).json()
    b=client.post('/api/v1/tasks',json=asdict(action(True))).json()
    path=f"/api/v1/tasks/{a['action']['task_id']}/approval"
    payload={'approval_id':a['approval']['approval_id'],'approve':True,'source':'voice'}
    assert client.post(path,json=payload).status_code==422
    payload['source']='screen';payload['approval_id']=b['approval']['approval_id']
    assert client.post(path,json=payload).json()['error_code']=='APPROVAL_MISMATCH'
    payload['approval_id']=str(uuid4())
    assert client.post(path,json=payload).json()['error_code']=='APPROVAL_MISMATCH'


def test_api_reject_cancel_missing_and_body_limit(client):
    a=client.post('/api/v1/tasks',json=asdict(action(True))).json()
    path=f"/api/v1/tasks/{a['action']['task_id']}"
    assert client.post(path+'/cancel').json()['status']=='cancelled'
    assert client.get('/api/v1/tasks/'+str(uuid4())).status_code==404
    assert client.get('/api/v1/tasks/not-an-id').status_code==422
    assert client.post('/api/v1/tasks',content=b' '*16385).status_code==413


def test_reconnect_read_only_history_and_stale_approval(tmp_path):
    settings=Settings(TOKEN,43210,task_database=tmp_path/'tasks.sqlite3')
    with TestClient(create_app(settings),base_url='http://127.0.0.1:43210',headers=AUTH) as c:
        v=c.post('/api/v1/tasks',json=asdict(action(True))).json()
    with TestClient(create_app(settings),base_url='http://127.0.0.1:43210',headers=AUTH) as c:
        path='/api/v1/tasks/'+v['action']['task_id']
        assert c.get(path).json()['status']=='cancelled'
        r=c.post(path+'/approval',json={'approval_id':v['approval']['approval_id'],'approve':True,'source':'screen'})
        assert r.json()['error_code']=='TASK_SESSION_INVALID'
