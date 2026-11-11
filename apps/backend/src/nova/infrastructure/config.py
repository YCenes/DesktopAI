from dataclasses import dataclass, field
import re
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    session_token: str = field(repr=False)
    port: int
    host: str = "127.0.0.1"
    task_database: Path | None = None
    windows_tools_config: Path | None = None

    def __post_init__(self) -> None:
        if self.host != "127.0.0.1":
            raise ValueError("Yalnızca loopback adresi kullanılabilir.")
        if not 1 <= self.port <= 65535:
            raise ValueError("Backend portu geçersiz.")
        if not re.fullmatch(r"[a-f0-9]{64}", self.session_token):
            raise ValueError("Oturum yapılandırması geçersiz.")

    @property
    def authority(self) -> str:
        return f"{self.host}:{self.port}"
