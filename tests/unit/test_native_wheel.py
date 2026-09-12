"""A wheel must ship the rate limiter compiled with its native callers."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import sysconfig
from zipfile import ZipFile

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_mypyc_wheel.py"
MODULES = (
    "dank_mids/helpers/_rate_limit",
    "dank_mids/helpers/_requester",
    "dank_mids/_vendor/aiolimiter/src/aiolimiter/__init__",
    "dank_mids/_vendor/aiolimiter/src/aiolimiter/leakybucket",
    "native__mypyc",
)


@pytest.mark.parametrize("missing", [None, *MODULES])
def test_wheel_rejects_missing_linked_module(tmp_path, missing, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_mypyc_wheel", SCRIPT)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    wheel = tmp_path / "native.whl"
    with ZipFile(wheel, "w") as archive:
        for module in MODULES:
            if module != missing:
                archive.writestr(module + sysconfig.get_config_var("EXT_SUFFIX"), b"")
            else:
                archive.writestr(module + ".cpython-39-other-platform.so", b"")
    targets = [module + ".py" for module in MODULES[:-1]]
    monkeypatch.setattr(checker, "load_mypyc_targets", lambda: targets)
    if missing is None:
        assert checker.check_wheel(wheel, targets) == []
        assert checker.main([str(SCRIPT), str(wheel)]) == 0
    else:
        failures = checker.check_wheel(wheel, targets)
        assert len(failures) == 1
        assert (
            missing in failures[0] if missing != "native__mypyc" else "native mypyc" in failures[0]
        )
        assert checker.main([str(SCRIPT), str(wheel)]) == 1


def test_native_rate_limiter_can_serve_a_request():
    code = """
import asyncio
from importlib.machinery import EXTENSION_SUFFIXES
from dank_mids import setup_dank_w3
from dank_mids.helpers import _rate_limit, _requester
from dank_mids._vendor.aiolimiter.src.aiolimiter import leakybucket

assert any(_rate_limit.__file__.endswith(suffix) for suffix in EXTENSION_SUFFIXES)
assert any(leakybucket.__file__.endswith(suffix) for suffix in EXTENSION_SUFFIXES)

async def verify():
    endpoint = 'http://127.0.0.1:1'
    await _rate_limit.rate_limit_inactive(endpoint)
    limiter = _rate_limit.limiters[endpoint]
    async with limiter:
        assert not limiter._waiters

asyncio.run(verify())
_requester.shutdown_http_requester()
"""
    subprocess.run(
        [sys.executable, "-c", code], check=True, text=True, capture_output=True, timeout=10
    )
