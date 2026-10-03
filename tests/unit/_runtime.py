"""Check the selected runtime without substituting modules in-process."""

import os
from importlib.machinery import EXTENSION_SUFFIXES
from types import ModuleType


def assert_test_runtime(module: ModuleType) -> None:
    suffixes = (
        (".py",) if os.getenv("DANK_MIDS_SOURCE_COVERAGE") == "1" else tuple(EXTENSION_SUFFIXES)
    )
    assert module.__file__ is not None and module.__file__.endswith(suffixes), module.__file__
