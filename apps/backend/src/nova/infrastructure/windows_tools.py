"""Güvenilir yerel config + dar Windows adapter. Fake namespace'ten ayrıdır."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import os
import ntpath
import time
from contextlib import ExitStack

from nova.domain.tasks import ActionRequest, ExecutionResult, TaskError, ToolResultDetails, FileMatch
from nova.infrastructure.windows_native import WindowsNative
from nova.domain.web_search import search_url


class WindowsTools:
    def __init__(self, config_path: Path | None = None, native=None):
        self.native = native
        self.config = {"enabled_apps": [], "notepad_sha256": None, 'roots':[], 'file_handler':'windows.notepad', 'enable_web_search':False,'browser_sha256':None}
        if config_path is not None and config_path.exists():
            if config_path.stat().st_size > 16384:
                raise TaskError("TOOLS_CONFIG_INVALID", "Windows araç yapılandırması çok büyük.")
            data=json.loads(config_path.read_text(encoding='utf-8-sig'))
            if (type(data) is not dict or set(data)-{'enabled_apps','notepad_sha256','roots','file_handler','enable_web_search','browser_sha256'}
                or data.get('enabled_apps',[]) not in ([],['windows.notepad'])
                or (data.get('enabled_apps') and not re.fullmatch('[a-fA-F0-9]{64}',data.get('notepad_sha256') or ''))
                or data.get('file_handler','windows.notepad')!='windows.notepad'
                or type(data.get('enable_web_search',False)) is not bool
                or (data.get('enable_web_search') and not re.fullmatch('[a-fA-F0-9]{64}',data.get('browser_sha256') or ''))):
                raise TaskError("TOOLS_CONFIG_INVALID", "Windows araç yapılandırması geçersiz.")
            self.config.update(data)
        roots=self.config['roots']
        if type(roots) is not list or len(roots)>8:
            raise TaskError('TOOLS_CONFIG_INVALID','En fazla sekiz açık dosya kökü tanımlanabilir.')
        self.roots={}
        for root in roots:
            if type(root) is not dict or set(root)!={'id','path'} or not re.fullmatch('[a-z][a-z0-9_-]{0,31}',root['id']) or root['id'] in self.roots:
                raise TaskError('TOOLS_CONFIG_INVALID','Dosya kökü yapılandırması geçersiz.')
            path=Path(root['path'])
            self.validate_root_location(path)
            with self.platform().guarded(path) as info:
                if not info.attributes & 0x10:
                    raise TaskError('ROOT_DENIED','Dosya kökü bir dizin olmalıdır.',403)
                stamp=(info.volume,info.index_high,info.index_low)
            self.roots[root['id']]=(path,stamp)
        self.max_entries=512;self.max_results=20;self.max_depth=5;self.search_seconds=2
        self.policy_version='windows-policy-1-'+hashlib.sha256(json.dumps(self.config,sort_keys=True).encode()).hexdigest()[:16]

    def platform(self):
        if self.native is None:
            self.native=WindowsNative()
        return self.native

    @contextmanager
    def verified_app(self, app_id):
        if app_id!='windows.notepad' or app_id not in self.config['enabled_apps']:
            raise TaskError("APP_NOT_ALLOWED", "Uygulama açıkça izinli değil.", 403)
        native=self.platform()
        image=native.windows_directory()/'System32'/'notepad.exe'
        with native.guarded(image):
            with image.open('rb') as source:
                digest=hashlib.file_digest(source,'sha256').hexdigest()
            if digest.lower()!=self.config['notepad_sha256'].lower():
                raise TaskError("APP_IDENTITY_CHANGED", "Uygulama kimliği değişti; güvenilir yapılandırmayı yeniden doğrulayın.", 403)
            yield image

    def authorize(self, action: ActionRequest):
        if action.tool_id=='windows.open_app':
            with self.verified_app(action.arguments.app_id):pass
        elif action.tool_id=='windows.search_files':
            with self.root_guard(action.arguments.root_id):pass
        elif action.tool_id=='windows.open_file':
            with self.file_guard(action.arguments):pass
            with self.verified_app('windows.notepad'):pass
        elif action.tool_id=='windows.web_search':
            search_url(action.arguments.query)
            with self.verified_browser():pass
        else:
            raise TaskError('TOOL_UNKNOWN','Windows aracı kayıtlı değil.',403)

    def execute(self, action: ActionRequest, deadline: float) -> ExecutionResult:
        if action.tool_id=='windows.web_search':
            url=search_url(action.arguments.query)
            with self.verified_browser() as image:
                self.check_deadline(deadline)
                pid=self.platform().launch_search(image,url)
            return ExecutionResult('succeeded','Arama isteği varsayılan tarayıcıya iletildi. Arama terimleri Google hizmetine gönderilir; sayfanın yüklendiği doğrulanmadı.',False,ToolResultDetails('search_submitted',pid))
        if action.tool_id=='windows.search_files':return self.search(action.arguments,deadline)
        if action.tool_id=='windows.open_file':
            with self.file_guard(action.arguments) as (path,info):
                with self.verified_app('windows.notepad') as image:
                    self.check_deadline(deadline)
                    pid=self.platform().launch_notepad(image,path)
            return ExecutionResult('succeeded','Dosya doğrulanmış Not Defteri uygulamasına iletildi. Görüntüleyicinin dosyayı okuduğu henüz doğrulanmadı.',False,ToolResultDetails('handoff_requested',pid))
        with self.verified_app(action.arguments.app_id) as image:
            self.check_deadline(deadline)
            pid=self.platform().launch_notepad(image)
        return ExecutionResult('succeeded',f'Not Defteri başlatma isteği kabul edildi (PID {pid}). Pencerenin hazır olduğu doğrulanmadı.',False,ToolResultDetails('process_started',pid))

    @contextmanager
    def verified_browser(self):
        if not self.config['enable_web_search']:
            raise TaskError('WEB_SEARCH_DISABLED','Web araması güvenilir yapılandırmada etkin değil.',403)
        image=self.platform().default_browser()
        bases=[Path(os.environ[k]) for k in ('PROGRAMFILES','PROGRAMFILES(X86)') if k in os.environ]
        if image.name.casefold() not in {'msedge.exe','chrome.exe','firefox.exe'} or not any(self.within(image,p) for p in bases):
            raise TaskError('BROWSER_HANDLER_DENIED','Varsayılan tarayıcı güvenli handler politikasında değil.',403)
        with self.platform().guarded(image):
            with image.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
            if digest.lower()!=self.config['browser_sha256'].lower():
                raise TaskError('BROWSER_IDENTITY_CHANGED','Varsayılan tarayıcı değişti; güvenilir yapılandırmayı yeniden doğrulayın.',403)
            if self.platform().default_browser()!=image:
                raise TaskError('BROWSER_IDENTITY_CHANGED','Varsayılan tarayıcı yürütme öncesinde değişti.',403)
            yield image

    @staticmethod
    def within(path,root):
        try:return ntpath.commonpath([ntpath.normcase(str(path)),ntpath.normcase(str(root))])==ntpath.normcase(str(root))
        except ValueError:return False

    @staticmethod
    def sensitive_component(part):
        value=part.casefold()
        return value.startswith('.') or bool(re.search(r'credential|password|secret|token|cookie|private|login',value)) or value in {'system volume information','$recycle.bin','recovery','windowsapps','microsoftedge','google','mozilla','ssh','aws','gnupg'}

    def validate_root_location(self,path):
        if not path.is_absolute() or str(path).startswith(('\\\\','//')) or any(self.sensitive_component(p) for p in path.parts[1:]):
            raise TaskError('ROOT_DENIED','Hassas, sistem veya desteklenmeyen dosya kökü.',403)
        profile=Path(os.environ.get('USERPROFILE',str(Path.home())))
        if self.within(profile,path) or path==Path(path.anchor):
            raise TaskError('ROOT_DENIED','Profilin tamamına veya üst dizinine izin verilmez.',403)
        protected=[self.platform().windows_directory()]
        protected += [Path(os.environ[k]) for k in ('PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMDATA','APPDATA') if k in os.environ]
        local=os.environ.get('LOCALAPPDATA')
        if local:
            local=Path(local);temp=local/'Temp'
            # Yalnızca açıkça seçilmiş bir Temp alt dizini test verisi olarak kullanılabilir.
            if self.within(path,local) and not (self.within(path,temp) and path!=temp):
                raise TaskError('ROOT_DENIED','Uygulama profilleri dosya kapsamı dışındadır.',403)
        if any(self.within(path,p) or self.within(p,path) for p in protected):
            raise TaskError('ROOT_DENIED','Sistem ve hassas dizinlere izin verilmez.',403)

    @contextmanager
    def root_guard(self,root_id):
        if root_id not in self.roots:
            raise TaskError('ROOT_DENIED','Bu dosya köküne açık izin verilmedi.',403)
        path,stamp=self.roots[root_id]
        self.validate_root_location(path)
        with self.platform().guarded(path) as info:
            if (info.volume,info.index_high,info.index_low)!=stamp or not info.attributes & 0x10:
                raise TaskError('ROOT_CHANGED','İzinli kökün kimliği değişti.',403)
            yield path

    @staticmethod
    def safe_relative(value):
        if type(value) is not str or not 1<=len(value)<=180 or value.startswith(('/', '\\')) or ':' in value or '\\' in value:
            raise TaskError('PATH_DENIED','Yalnızca güvenli göreli dosya yolu kabul edilir.',403)
        parts=value.split('/')
        if any(p in ('','.', '..') or p.endswith((' ','.')) or WindowsTools.sensitive_component(p) or not all(c.isalnum() or c in ' ._-' for c in p) for p in parts):
            raise TaskError('PATH_DENIED','Dosya yolu güvenli kapsamda değil.',403)
        name=parts[-1]
        if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(10)],*[f'LPT{i}' for i in range(10)]}:
            raise TaskError('PATH_DENIED','Windows device adları kabul edilmez.',403)
        if name.count('.')!=1 or not name.casefold().endswith('.txt') or not all(c.isalnum() or c in ' ._-' for c in name):
            raise TaskError('FILE_TYPE_DENIED','Yalnızca basit adlı .txt belgeleri desteklenir.',403)
        return parts

    @contextmanager
    def file_guard(self,args):
        parts=self.safe_relative(args.relative_path)
        with self.root_guard(args.root_id) as root:
            path=root.joinpath(*parts)
            if not self.within(path,root):
                raise TaskError('PATH_DENIED','Dosya izinli kökün dışında.',403)
            with self.platform().guarded(path) as info:
                size=(info.size_high<<32)|info.size_low
                if info.attributes & 0x10 or info.links!=1 or size>10*1024*1024:
                    raise TaskError('FILE_TYPE_DENIED','Dizin, hardlink veya fazla büyük dosya açılamaz.',403)
                if self.platform().fingerprint(info)!=args.identity:
                    raise TaskError('FILE_CHANGED','Dosya aramadan sonra değişti; yeniden arayın.',403)
                yield path,info

    @staticmethod
    def check_deadline(deadline):
        if time.monotonic()>=deadline:
            raise TaskError('WORKFLOW_TIMEOUT','Yürütme süresi doldu; yeni Windows isteği yapılmadı.')

    def search(self,args,deadline):
        matches=[];seen=0;truncated=False;end=min(deadline,time.monotonic()+self.search_seconds)
        with self.root_guard(args.root_id) as root:
            stack=[(root,0)]
            while stack:
                directory,depth=stack.pop()
                if time.monotonic()>=end or seen>=self.max_entries:
                    truncated=True;break
                try:
                    with self.platform().guarded(directory),os.scandir(directory) as entries:
                        for entry in entries:
                            seen+=1
                            if time.monotonic()>=end or seen>self.max_entries:
                                truncated=True;break
                            if self.sensitive_component(entry.name):continue
                            try:
                                with self.platform().guarded(Path(entry.path)) as info:
                                    if info.attributes & 0x10:
                                        if depth<self.max_depth:stack.append((Path(entry.path),depth+1))
                                        else:truncated=True
                                    elif args.query.casefold() in entry.name.casefold():
                                        relative=Path(entry.path).relative_to(root).as_posix()
                                        self.safe_relative(relative)
                                        if info.links!=1 or info.size_high or info.size_low>10*1024*1024:continue
                                        matches.append(FileMatch(args.root_id,relative,self.platform().fingerprint(info),info.size_low))
                                        if len(matches)>=self.max_results:truncated=True;break
                            except (TaskError,OSError):continue
                except (TaskError,OSError):continue
                if truncated and (len(matches)>=self.max_results or seen>=self.max_entries or time.monotonic()>=end):break
        return ExecutionResult('succeeded',f'{len(matches)} güvenli metin dosyası bulundu. Dosya içeriği okunmadı.'+(' Arama sınırına ulaşıldı.' if truncated else ''),False,ToolResultDetails('metadata_search',files=tuple(matches),truncated=truncated))
