"""Lazy composition root; tek veri dizini için tek canlı backend sahibi."""
from pathlib import Path
from tempfile import TemporaryDirectory
import threading

from nova.domain.tasks import TaskError


class TaskRuntime:
    def __init__(self, path: Path | None, windows_config: Path | None = None):
        self.path = path
        self.windows_config = windows_config
        self.service = None
        self._temporary = None
        self._owner = None
        self._lock = threading.RLock()

    def get(self):
        with self._lock:
            if self.service is not None:
                return self.service
            if self.path is None:
                self._temporary = TemporaryDirectory(prefix="nova-tasks-")
                self.path = Path(self._temporary.name) / "tasks.sqlite3"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._owner = self.path.with_suffix(".owner").open("a+b")
            if self.path.with_suffix(".owner").stat().st_size == 0:
                self._owner.write(b"0"); self._owner.flush()
            self._owner.seek(0)
            try:
                import sys
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self._owner.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self._owner.close(); self._owner = None
                raise TaskError("TASK_STORE_BUSY", "Görev geçmişi başka bir NOVA oturumunda açık.", 503) from None
            try:
                from nova.application.tasks import TaskService
                from nova.application.tools import ToolRegistry
                from nova.infrastructure.windows_tools import WindowsTools
                self.service = TaskService(self.path,registry=ToolRegistry(WindowsTools(self.windows_config)))
                return self.service
            except Exception:
                self.close()
                raise

    def close(self):
        with self._lock:
            if self.service:
                self.service.close(); self.service = None
            if self._owner:
                self._owner.close(); self._owner = None
            if self._temporary:
                self._temporary.cleanup(); self._temporary = None
