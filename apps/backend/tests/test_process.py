"""Gerçek Python child testleri; Rust host testi yerine geçmez."""

import json
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time

import httpx
import pytest


class StartupTimeout(Exception):
    pass


def read_line_with_timeout(stream, timeout):
    result = queue.Queue()
    threading.Thread(target=lambda: result.put(stream.readline(4097)), daemon=True).start()
    try:
        return result.get(timeout=timeout)
    except queue.Empty:
        raise StartupTimeout from None


def spawn_backend():
    return subprocess.Popen(
        [sys._base_executable, "-I", "-S", "-u", str(Path(__file__).parents[3] / "scripts" / "dev_backend.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )


@pytest.fixture
def running_backend():
    process = spawn_backend()
    token = secrets.token_hex(32)
    try:
        process.stdin.write(json.dumps({"protocol": 1, "token": token}) + "\n")
        process.stdin.flush()
        line = read_line_with_timeout(process.stdout, 45)
        handshake = json.loads(line)
        assert set(handshake) == {"protocol", "port"}
        assert handshake["protocol"] == 1
        assert token not in line
        address = f"http://127.0.0.1:{handshake['port']}"
        with httpx.Client(base_url=address, headers={"Authorization": f"Bearer {token}"}, trust_env=False, timeout=0.5) as client:
            deadline = time.monotonic() + 45
            while True:
                try:
                    if client.get("/api/v1/ready").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic() >= deadline:
                    pytest.fail("Backend readiness zaman aşımı")
                time.sleep(0.05)
            yield process, client, token, address
    finally:
        if process.poll() is None:
            process.stdin.close()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=4)
        process.stdout.close()
        process.stderr.close()


def test_real_child_health_auth_and_secrets(running_backend):
    process, client, token, address = running_backend
    assert client.get("/api/v1/health").json()["app_version"] == "0.1.0"
    assert client.get("/api/v1/health", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.get("/api/v1/health", headers={"Origin": "http://evil.example"}).status_code == 403
    assert token not in " ".join(process.args)
    assert token not in address


@pytest.mark.parametrize("shutdown", ["message", "eof"])
def test_process_cleanup_by_message_or_parent_eof(running_backend, shutdown):
    process, client, token, _ = running_backend
    if shutdown == "message":
        process.stdin.write("shutdown\n")
        process.stdin.flush()
    else:
        process.stdin.close()
    assert process.wait(timeout=4) == 0
    assert token not in process.stdout.read()
    assert token not in process.stderr.read()
    with pytest.raises(httpx.TransportError):
        client.get("/api/v1/health")


def test_unexpected_process_termination_is_observable(running_backend):
    process, client, _, _ = running_backend
    process.kill()
    process.wait(timeout=4)
    assert process.poll() is not None
    with pytest.raises(httpx.TransportError):
        client.get("/api/v1/ready")


def test_silent_child_startup_timeout_and_cleanup():
    # Test double; timeout helper testi Rust supervisor timeout kanıtı değildir.
    process = subprocess.Popen([sys._base_executable, "-I", "-S", "-u", "-c", "import time; time.sleep(30)"], stdout=subprocess.PIPE, text=True)
    try:
        with pytest.raises(StartupTimeout):
            read_line_with_timeout(process.stdout, 0.1)
    finally:
        process.kill()
        process.wait(timeout=4)
        process.stdout.close()
    assert process.poll() is not None


def test_invalid_bootstrap_leaves_no_secret_output():
    process = spawn_backend()
    marker = secrets.token_hex(32)
    try:
        stdout, stderr = process.communicate(json.dumps({"protocol": 9, "token": marker}) + "\n", timeout=8)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=4)
    assert process.returncode == 1
    assert not stdout
    assert stderr.strip() == "BACKEND_START_FAILED"
    assert marker not in stderr
