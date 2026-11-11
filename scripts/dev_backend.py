"""Dev giriş noktası: Windows venv redirector'ü yerine doğrudan base Python.

Host bu dosyayı -I -S -u ile çağırır. Site discovery/env/PYTHONPATH kullanılmaz;
yalnızca bu depoya ait venv paketleri ve backend kaynağı import yoluna eklenir.
"""
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parents[1]
packages = root / ".venv" / "Lib" / "site-packages"
source = root / "apps" / "backend" / "src"
if not packages.is_dir() or not source.is_dir():
    print("BACKEND_ENV_UNAVAILABLE", file=sys.stderr)
    raise SystemExit(1)
sys.path[:0] = [str(source), str(packages)]
runpy.run_module("nova", run_name="__main__")
