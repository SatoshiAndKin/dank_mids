# Repository instructions

- Use Conventional Commits titles and messages. In PR descriptions, state the change
  and relevant validation.
- Use the repository's formatter, linter, dependency locks, and configured test runner.
  Keep mypy configuration in `pyproject.toml` and pytest settings in its owning config;
  workflows and hooks invoke those configured checks.
- When code is compiled with mypyc, run tests against the compiled extensions and report
  how that runtime was confirmed.

## Compiled runtime and validation

- Treat tracked `.py` files as mypyc inputs. Wheels, setup, and tests use compiled
  extensions; do not substitute an interpreted runtime.
- Run relevant tests with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest <files>` after
  building extensions. New or edited code needs at least 90% coverage in `tests/unit`.
- If sandboxed asyncio/threaded checks fail on Unix socketpair wakeups, rerun them
  with host access before diagnosing a runtime regression.
- Patch external edges only; do not monkeypatch dank-mids internals. Use yield fixtures
  to clean shared mutable state. Keep test-only repair and production fixes in separate PRs.

## Preserved behavior and artifacts

- `WeakList` deliberately uses weakrefs. Empty batches/posts after calls are collected
  or drained are valid; do not retain calls with strong refs without a design change.
- Keep generated `build/**/*.c` and `build/**/*.h` changes for mypyc review. Exclude
  binary `.so`/`.pyd` extensions from PRs.
- Update the `dank_mids/_vendor/aiolimiter` submodule only when explicitly requested.
