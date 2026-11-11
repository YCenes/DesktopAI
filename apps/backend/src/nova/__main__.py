"""Yalnızca host pipe'ından bootstrap edilen geliştirme backend'i."""

import asyncio
import json
import logging
import socket
import sys
import threading
import os
from pathlib import Path

from nova.infrastructure.config import Settings


def read_bootstrap(stream) -> str:
    line = stream.readline(4097)
    if len(line) > 4096 or not line.endswith("\n"):
        raise ValueError("Bootstrap mesajı geçersiz.")
    data = json.loads(line)
    if not isinstance(data, dict) or set(data) != {"protocol", "token"} or type(data["protocol"]) is not int or data["protocol"] != 1:
        raise ValueError("Bootstrap sözleşmesi geçersiz.")
    token = data["token"]
    if not isinstance(token, str):
        raise ValueError("Oturum yapılandırması geçersiz.")
    # Port bilinmeden de token formatı doğrulanır.
    Settings(session_token=token, port=1)
    return token


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        token = read_bootstrap(sys.stdin)
        # Hatalı bootstrap için ağır framework import'u veya socket açılışı yok.
        import uvicorn
        from nova.api.app import create_app

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if sys.platform == "win32":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            # Yalnızca güvenilir host/developer config; frontend yol seçemez.
            data_dir = Path(os.environ.get("NOVA_TASK_DATA_DIR") or str(Path(os.environ["LOCALAPPDATA"]) / "NOVA"))
            if not data_dir.is_absolute():
                raise ValueError("Veri dizini mutlak olmalı.")
            settings = Settings(session_token=token, port=listener.getsockname()[1], task_database=data_dir / "tasks.sqlite3")
            config = uvicorn.Config(
                create_app(settings), host=settings.host, port=settings.port,
                access_log=False, log_config=None, server_header=False,
                timeout_graceful_shutdown=2,
            )
            server = uvicorn.Server(config)
            stop_requested = threading.Event()

            def watch_parent() -> None:
                # Tek lifecycle mesajı; host çıkışındaki EOF de kapanışı ister.
                sys.stdin.readline(32)
                stop_requested.set()

            threading.Thread(target=watch_parent, daemon=True).start()
            print(json.dumps({"protocol": 1, "port": settings.port}), flush=True)

            async def serve() -> None:
                async def monitor_parent() -> None:
                    while not stop_requested.is_set():
                        await asyncio.sleep(0.05)
                    server.should_exit = True

                monitor = asyncio.create_task(monitor_parent())
                try:
                    await server.serve(sockets=[listener])
                finally:
                    monitor.cancel()
                    try:
                        await monitor
                    except asyncio.CancelledError:
                        pass

            asyncio.run(serve())
        return 0
    except Exception:
        # Exception metni bootstrap/token veya yerel yolu sızdırabilir.
        print("BACKEND_START_FAILED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
