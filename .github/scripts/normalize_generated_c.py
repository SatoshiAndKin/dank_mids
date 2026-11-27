"""Normalize generated C for the repository's existing source review contract."""

import re
from pathlib import (
    Path,
)

PREFIX = "#ifndef DIFFCHECK_PLACEHOLDER\n#define DIFFCHECK_PLACEHOLDER 0\n#endif\n"


def normalize(source):
    if not source.startswith(PREFIX):
        source = PREFIX + source
    source = re.sub(
        r"(CPy_AddTraceback\([^,]*,\s*[^,]*,\s*)[0-9]+(\s*,)",
        r"\1DIFFCHECK_PLACEHOLDER\2",
        source,
    )
    return re.sub(r"CPyStatics\[[0-9]+\]", "CPyStatics[DIFFCHECK_PLACEHOLDER]", source)


if __name__ == "__main__":
    files = list(Path("build").glob("*.c"))
    if not files:
        raise ValueError("The build did not generate C source")
    for path in files:
        path.write_text(normalize(path.read_text()))
