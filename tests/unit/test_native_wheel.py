"""A wheel must ship the rate limiter compiled with its native callers."""

import importlib.util
import subprocess
import sys
import sysconfig
from pathlib import Path
from zipfile import ZipFile

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_mypyc_wheel.py"
MODULES = (
    "dank_mids/helpers/_rate_limit",
    "dank_mids/helpers/_requester",
    "dank_mids/_vendor/aiolimiter/src/aiolimiter/__init__",
    "dank_mids/_vendor/aiolimiter/src/aiolimiter/leakybucket",
    "dank_mids__mypyc",
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
    monkeypatch.setattr(checker, "expand_mypyc_targets", lambda root: targets)
    if missing is None:
        assert checker.check_wheel(wheel, targets) == []
        assert checker.main([str(SCRIPT), str(wheel)]) == 0
    else:
        failures = checker.check_wheel(wheel, targets)
        assert len(failures) == 1
        assert (
            missing in failures[0]
            if missing != "dank_mids__mypyc"
            else "runtime artifact" in failures[0]
        )
        assert checker.main([str(SCRIPT), str(wheel)]) == 1


def test_native_rate_limiter_can_serve_a_request():
    code = """
import asyncio
from tests.unit._runtime import assert_test_runtime
from dank_mids import setup_dank_w3
from dank_mids.helpers import _rate_limit, _requester
from dank_mids._vendor.aiolimiter.src.aiolimiter import leakybucket

assert_test_runtime(_rate_limit)
assert_test_runtime(leakybucket)

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


@pytest.mark.parametrize(
    "tag,suffix",
    [
        ("cp310-cp310-macosx_11_0_arm64", ".cpython-310-darwin.so"),
        ("cp311-cp311-manylinux_2_17_x86_64", ".cpython-311-x86_64-linux-gnu.so"),
        ("cp312-cp312-manylinux_2_17_aarch64", ".cpython-312-aarch64-linux-gnu.so"),
        ("cp313-cp313-win_amd64", ".cp313-win_amd64.pyd"),
    ],
)
def test_wheel_checks_its_own_abi_and_platform(tmp_path, tag, suffix):
    spec = importlib.util.spec_from_file_location("checker", SCRIPT)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    wheel = tmp_path / ("dank_mids-4.20.215-" + tag + ".whl")
    for wrong in (False, True):
        with ZipFile(wheel, "w") as archive:
            archive.writestr("dank_mids__mypyc" + suffix, b"")
            archive.writestr(
                "dank_mids/_batch" + (".cpython-39-wrong.so" if wrong else suffix), b""
            )
        assert checker.check_wheel(wheel, ["dank_mids/_batch.py"]) == (
            [f"{wheel.name}: missing compiled artifact for dank_mids/_batch.py"] if wrong else []
        )


@pytest.mark.parametrize("tag", ["py3-none-any", "cp312-cp313-win_amd64", "cp312-cp312-unknown"])
def test_wheel_rejects_unsupported_native_tags(tmp_path, tag):
    spec = importlib.util.spec_from_file_location("checker", SCRIPT)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    with pytest.raises(ValueError, match="unsupported native wheel"):
        checker.wheel_extension_suffix(tmp_path / ("dank_mids-4.20.215-" + tag + ".whl"))
