"""Dar Windows native primitives. Shell/terminal veya kullanıcı executable yolu yok."""
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes as w
import hashlib
import ntpath
import os
from pathlib import Path, PureWindowsPath
import subprocess

from nova.domain.tasks import TaskError


class FileInformation(ctypes.Structure):
    _fields_ = [("attributes", w.DWORD), ("created", w.FILETIME), ("accessed", w.FILETIME),
        ("written", w.FILETIME), ("volume", w.DWORD), ("size_high", w.DWORD), ("size_low", w.DWORD),
        ("links", w.DWORD), ("index_high", w.DWORD), ("index_low", w.DWORD)]


class BasicInformation(ctypes.Structure):
    _fields_=[('created',ctypes.c_longlong),('accessed',ctypes.c_longlong),('written',ctypes.c_longlong),('changed',ctypes.c_longlong),('attributes',w.DWORD)]


class WindowsNative:
    def __init__(self):
        if os.name != "nt":
            raise TaskError("WINDOWS_REQUIRED", "Bu araç yalnızca Windows'ta kullanılabilir.", 503)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateFileW.argtypes = [w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE]
        self.kernel.CreateFileW.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.GetFileInformationByHandle.argtypes = [w.HANDLE,ctypes.POINTER(FileInformation)]
        self.kernel.GetFileInformationByHandleEx.argtypes=[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD]
        self.kernel.GetFinalPathNameByHandleW.argtypes = [w.HANDLE,w.LPWSTR,w.DWORD,w.DWORD]
        self.kernel.GetDriveTypeW.argtypes = [w.LPCWSTR]
        self.kernel.GetWindowsDirectoryW.argtypes = [w.LPWSTR,w.UINT]

    def windows_directory(self) -> Path:
        buffer = ctypes.create_unicode_buffer(32768)
        if not self.kernel.GetWindowsDirectoryW(buffer,len(buffer)):
            raise TaskError("WINDOWS_IDENTITY_INVALID", "Windows dizini doğrulanamadı.")
        return Path(buffer.value)

    @contextmanager
    def guarded(self, path: Path):
        """Tüm ancestor'ları rename/reparse yarışına karşı açık tutar; leaf yazılamaz."""
        text = str(path)
        pure = PureWindowsPath(text)
        if (not pure.is_absolute() or text.startswith(('\\\\','//')) or len(text)>240
            or ':' in text[2:] or any(part in ('.','..') or part.endswith((' ','.')) for part in pure.parts[1:])):
            raise TaskError("PATH_DENIED", "Dosya yolu desteklenmiyor.", 403)
        if self.kernel.GetDriveTypeW(pure.anchor) != 3:
            raise TaskError("PATH_DENIED", "Yalnızca yerel sabit disk konumları desteklenir.", 403)
        with ExitStack() as stack:
            parents = list(reversed(path.parents)) + [path]
            leaf_info = None
            for item in parents:
                is_leaf = item == path
                # Dizinlere write sharing, rename/delete sharing yok. Leaf salt-okuma sharing.
                handle = self.kernel.CreateFileW(str(item),0x80000000,1 if is_leaf else 3,None,3,0x02300000,None)
                if handle == ctypes.c_void_p(-1).value:
                    raise TaskError("PATH_UNAVAILABLE", "Konum kilitli, erişilemiyor veya mevcut değil.", 403)
                stack.callback(self.kernel.CloseHandle,handle)
                info = FileInformation()
                final = ctypes.create_unicode_buffer(32768)
                if not self.kernel.GetFileInformationByHandle(handle,ctypes.byref(info)):
                    raise TaskError("PATH_DENIED", "Dosya kimliği doğrulanamadı.", 403)
                basic=BasicInformation()
                if not self.kernel.GetFileInformationByHandleEx(handle,0,ctypes.byref(basic),ctypes.sizeof(basic)):
                    raise TaskError('PATH_DENIED','Dosyanın değişiklik kimliği doğrulanamadı.',403)
                info.change_time=basic.changed
                if info.attributes & (0x400 | 0x1000 | 0x40000):
                    raise TaskError("REPARSE_DENIED", "Reparse, offline veya bulut konumuna izin verilmiyor.", 403)
                if not self.kernel.GetFinalPathNameByHandleW(handle,final,len(final),0):
                    raise TaskError("PATH_DENIED", "Dosyanın gerçek yolu doğrulanamadı.", 403)
                canonical = final.value
                if canonical.startswith('\\\\?\\'):
                    canonical=canonical[4:]
                if ntpath.normcase(canonical) != ntpath.normcase(str(item)):
                    raise TaskError("PATH_DENIED", "Konumun gerçek yolu istenen yolla eşleşmiyor.", 403)
                if is_leaf:
                    leaf_info = info
            yield leaf_info

    def fingerprint(self, info: FileInformation) -> str:
        data=(info.volume,info.index_high,info.index_low,info.size_high,info.size_low,
              info.written.dwHighDateTime,info.written.dwLowDateTime,info.links,info.change_time)
        return hashlib.sha256(repr(data).encode('ascii')).hexdigest()

    def launch_notepad(self, image: Path, document: Path | None = None) -> int:
        # Python Windows Popen doğrudan CreateProcessW kullanır. applicationName sabittir;
        # belge argümanı yalnızca kilitli ve doğrulanmış .txt yolundan gelir.
        return self._create_process(image, [str(document)] if document else [])

    def _create_process(self,image: Path, arguments: list[str]) -> int:
        environment={key:value for key,value in os.environ.items() if key.upper() in {
            'SYSTEMROOT','WINDIR','SYSTEMDRIVE','USERPROFILE','LOCALAPPDATA','APPDATA','TEMP','TMP','USERNAME','USERDOMAIN','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMDATA'}}
        environment['PATH']=str(self.windows_directory()/'System32')
        arguments=[str(image)] + arguments
        try:
            process=subprocess.Popen(arguments,executable=str(image),shell=False,close_fds=True,
                cwd=str(image.parent),env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError:
            raise TaskError("APP_LAUNCH_FAILED", "İzinli uygulamanın başlatma isteği başarısız oldu.") from None
        return process.pid

    def default_browser(self) -> Path:
        library=ctypes.WinDLL('shlwapi',use_last_error=True)
        query=library.AssocQueryStringW
        query.argtypes=[w.DWORD,w.DWORD,w.LPCWSTR,w.LPCWSTR,w.LPWSTR,ctypes.POINTER(w.DWORD)]
        query.restype=w.LONG
        size=w.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
        # IS_PROTOCOL | VERIFY, ASSOCSTR_EXECUTABLE. Registry command string yürütülmez.
        if query(0x1040,2,'https','open',buffer,ctypes.byref(size))!=0:
            raise TaskError('BROWSER_UNAVAILABLE','Varsayılan HTTPS tarayıcısı güvenle çözümlenemedi.')
        return Path(buffer.value)

    def launch_search(self,image: Path,url: str) -> int:
        return self._create_process(image,[url])
