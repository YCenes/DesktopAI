from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import time
from uuid import uuid4

import pytest

from nova.application.tasks import TaskService
from nova.application.tools import ToolRegistry
from nova.domain.tasks import ActionRequest,ScopedSearchArguments,OpenFileArguments,TaskError
from nova.infrastructure.windows_native import WindowsNative
from nova.infrastructure.windows_tools import WindowsTools


class FileNativeDouble(WindowsNative):
    def __init__(self,windows):super().__init__();self.windows=windows;self.calls=[]
    def windows_directory(self):return self.windows
    def launch_notepad(self,image,document=None):self.calls.append((image,document));return 456


@pytest.fixture
def files(tmp_path):
    root=tmp_path/'allowed';root.mkdir()
    image=tmp_path/'Windows'/'System32'/'notepad.exe';image.parent.mkdir(parents=True);image.write_bytes(b'synthetic only')
    config=tmp_path/'config.json';config.write_text(json.dumps({'enabled_apps':['windows.notepad'],
        'notepad_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'roots':[{'id':'test','path':str(root)}]}))
    native=FileNativeDouble(image.parents[1]);tools=WindowsTools(config,native)
    s=TaskService(tmp_path/'tasks.sqlite3',registry=ToolRegistry(tools))
    yield s,tools,native,root,config
    s.close()


def search_action(root_id='test',query='rapor'):
    return ActionRequest(str(uuid4()),str(uuid4()),'windows.search_files',ScopedSearchArguments(root_id,query),'windows.files')


def open_action(match):
    return ActionRequest(str(uuid4()),str(uuid4()),'windows.open_file',OpenFileArguments(match['root_id'],match['relative_path'],match['identity']),'windows.files')


def test_authorized_metadata_search_and_separate_approved_open(files,monkeypatch):
    s,tools,native,root,_=files
    (root/'rapor.txt').write_text('synthetic harmless content',encoding='utf-8')
    original=Path.open
    def no_content(self,*a,**kw):
        if self==root/'rapor.txt':pytest.fail('Search must not read file contents')
        return original(self,*a,**kw)
    monkeypatch.setattr(Path,'open',no_content)
    v=s.create(search_action());assert v['status']=='succeeded'
    matches=v['result']['details']['files'];assert len(matches)==1
    assert matches[0]['relative_path']=='rapor.txt' and len(matches[0]['identity'])==64
    assert not native.calls
    a=open_action(matches[0]);v=s.create(a);assert v['status']=='awaiting_approval'
    v=s.respond(a.task_id,v['approval']['approval_id'],True)
    assert v['status']=='succeeded' and v['result']['details']['completion']=='handoff_requested'
    assert native.calls[0][1]==root/'rapor.txt'


def test_unconfigured_root_is_denied(files):
    s,_,native,_,_=files
    v=s.create(search_action('ungranted'))
    assert v['status']=='failed' and v['error_code']=='PERMISSION_DENIED' and not native.calls


@pytest.mark.parametrize('path',['../outside/rapor.txt','../allowed-sibling/rapor.txt','/rapor.txt','C:/Windows/rapor.txt',
    '\\\\server\\share\\rapor.txt','\\\\?\\C:\\rapor.txt','rapor.txt:payload','folder\\rapor.txt','./rapor.txt','folder/../rapor.txt',
    'rapor.exe','rapor.ps1','rapor.cmd','rapor.bat','rapor.lnk','rapor.url','rapor.docm','rapor.pdf','rapor.exe.txt','rapor.txt ','.ssh/rapor.txt','credentials.txt'])
def test_traversal_protocol_active_content_and_sensitive_names(files,path):
    s,_,native,_,_=files
    a=ActionRequest(str(uuid4()),str(uuid4()),'windows.open_file',OpenFileArguments('test',path,'a'*64),'windows.files')
    v=s.create(a);assert v['status']=='failed' and not native.calls


def test_changed_file_and_root_identity_denied(files):
    s,_,native,root,_=files
    path=root/'rapor.txt';path.write_text('one')
    match=s.create(search_action())['result']['details']['files'][0]
    path.write_text('different synthetic contents')
    assert s.create(open_action(match))['status']=='failed'
    moved=root.with_name('old-allowed');root.rename(moved);root.mkdir()
    assert s.create(search_action())['status']=='failed' and not native.calls


def test_junction_escape_and_hardlink_are_not_searched(files,tmp_path):
    import _winapi
    s,_,native,root,_=files
    outside=tmp_path/'outside';outside.mkdir();(outside/'rapor.txt').write_text('synthetic outside')
    _winapi.CreateJunction(str(outside),str(root/'jump'))
    os.link(outside/'rapor.txt',root/'rapor.txt')
    v=s.create(search_action());assert v['result']['details']['files']==[]
    assert not native.calls


def test_symlink_escape_denied_when_supported(files,tmp_path):
    s,_,_,root,_=files
    outside=tmp_path/'outside';outside.mkdir();(outside/'rapor.txt').write_text('synthetic')
    try:os.symlink(outside,root/'link',target_is_directory=True)
    except OSError as e:
        if getattr(e,'winerror',None)==1314:pytest.skip('Windows symlink privilege unavailable; junction test is separate')
        raise
    assert s.create(search_action())['result']['details']['files']==[]


def test_file_is_locked_against_replace_during_handoff(files,monkeypatch):
    s,_,native,root,_=files
    path=root/'rapor.txt';path.write_text('synthetic')
    match=s.create(search_action())['result']['details']['files'][0]
    replacement=root/'replacement.txt';replacement.write_text('other synthetic')
    def swap(image,document):
        with pytest.raises(PermissionError):os.replace(replacement,document)
        return 789
    monkeypatch.setattr(native,'launch_notepad',swap)
    a=open_action(match);v=s.create(a)
    assert s.respond(a.task_id,v['approval']['approval_id'],True)['status']=='succeeded'


def test_locked_file_safely_excluded(files):
    s,_,native,root,_=files
    p=root/'rapor.txt';p.write_text('synthetic')
    handle=native.kernel.CreateFileW(str(p),0xC0000000,0,None,3,0,None)
    import ctypes
    assert handle!=ctypes.c_void_p(-1).value
    try:assert s.create(search_action())['result']['details']['files']==[]
    finally:native.kernel.CloseHandle(handle)


def test_search_result_count_entry_and_time_bounds(files):
    s,tools,_,root,_=files
    for i in range(25):(root/f'rapor-{i}.txt').write_text('synthetic')
    v=s.create(search_action());assert len(v['result']['details']['files'])==20 and v['result']['details']['truncated']
    tools.max_entries=3
    v=s.create(search_action());assert len(v['result']['details']['files'])<=3 and v['result']['details']['truncated']
    tools.search_seconds=0
    v=s.create(search_action());assert not v['result']['details']['files'] and v['result']['details']['truncated']


@pytest.mark.parametrize('location',['C:/','C:/Windows','C:/Windows/System32','C:/Program Files','C:/Users'])
def test_system_broad_roots_fail_closed(files,location):
    _,tools,_,_,_=files
    tools.native.windows_directory=lambda:Path('C:/Windows')
    with pytest.raises(TaskError):tools.validate_root_location(Path(location))


def test_unsafe_handler_config_rejected_and_default_association_unused(files):
    _,_,native,_,config=files
    data=json.loads(config.read_text());data['file_handler']='cmd.exe';config.write_text(json.dumps(data))
    with pytest.raises(TaskError):WindowsTools(config,native)


def test_same_size_edit_with_restored_write_time_changes_identity(files):
    s,_,_,root,_=files
    p=root/'rapor.txt';p.write_text('one');before=p.stat()
    match=s.create(search_action())['result']['details']['files'][0]
    p.write_text('two');os.utime(p,ns=(before.st_atime_ns,before.st_mtime_ns))
    assert s.create(open_action(match))['status']=='failed'


def test_large_file_and_depth_limit(files):
    s,tools,_,root,_=files
    with (root/'rapor-large.txt').open('wb') as stream:stream.truncate(10*1024*1024+1)
    directory=root
    for i in range(7):directory=directory/f'd{i}';directory.mkdir()
    (directory/'rapor.txt').write_text('synthetic')
    v=s.create(search_action())
    assert not v['result']['details']['files'] and v['result']['details']['truncated']
