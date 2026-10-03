# Fork changes against upstream 4.20.215

The baseline is upstream commit `88e06a54b5fb9f26f64752617c3a1f2e6460d26f`.
The merge preserves fork and upstream history. Upstream owns Web3 v7 dispatch,
response envelopes and IDs, waiter tracking, bounded shutdown, Hatchling, uv,
and the pinned aiolimiter submodule (`441d80fca626e1eab5bad63c19a32167a915cb19`).

## Retained runtime repairs

| Source | Required behavior | Regression tests |
| --- | --- | --- |
| `_block.py`, `controller.py`, `semaphores.py`, `eth.py` | Retain hash and canonical selectors through header lookup, admission, batch grouping and direct RPC; validate the returned header hash; retain upstream response IDs. | `test_block_identity.py`, `test_hash_rpc.py` |
| `brownie_patch/{_method,call,overloaded,types}.py` | Pass selectors unchanged through direct, overloaded and mapped Brownie calls. | `test_brownie_hash_selector.py` |
| `types.py` | Select historical/modern block schemas per response independently of key order; decode by hash; preserve arbitrary error data. | `test_block_decoding.py`, `test_rpc_error_data.py` |
| `_batch.py`, `_requests.py` | Enclosing batches own embedded multicalls; failed singleton multicalls terminate through the original direct request, including embedded JSON responses; historical multicalls retain state identity. | `test_gc_batch_contract.py`, `test_multicall_singleton.py`, `test_historical_multicall.py` |
| `_requests.py`, `_tasks.py`, `helpers/_requester.py` | Release retry exceptions and finished tasks; cancel owned HTTP attempts on all exits; bridge caller cancellation to the requester loop while retaining upstream bounded shutdown. | `test_http_retry_release.py`, `test_requester_ownership.py`, `requester_thread/` |
| `helpers/_rate_limit.py`, `controller.py` | Resume rate-limited callers together; a warning timeout must preserve dispatched work. | `test_rate_limit_admission.py`, `test_gc_batch_contract.py` |
| `_exceptions.py` | Parse provider-specific retry metadata only when its shape matches, retaining arbitrary RPC error context. | `test_rpc_error_data.py`, `test_brownie_patch_errors.py` |
| `logging.py`, `_tasks.py`, `brownie_patch/__init__.py`, `helpers/_codec.py`, `helpers/hashing.py` | Public Python annotation aliases, awaitable annotation compatibility, Brownie exports, native-safe decoder naming and AttributeDict cached hashing. | logging parity suite, `test_brownie_patch_errors.py`, `test_helpers_attrdict_compat.py`, HTTP decoding regressions |

Weakly owned calls remain weakly owned. Empty batches/posts after collection or
draining are expected. Generated artifacts come from upstream/CI, not local builds.
The evmspec transaction repair remains pinned at
`f0df0d9d8e4e7a7000580054ce2c0b6b6193a14c`.

## Native checksum ownership

Pin cchecksum to `fff7e1fe87f4679ec96de1cebb1cdd8f5e94be44`. Published
0.4.4 and 0.4.5 return a dangling pointer from their private address-normalization
helper. A single scalar checksum fails under `PYTHONMALLOC=debug`; bulk strings
share the same path. The repair returns owned bytes, preserving public checksums,
validation and ordering. Its regression compares native scalar/bulk results with
eth-utils under concurrent calls and forced collection. All 22 upstream cases
pass under the debug allocator after a fresh extension build. SDK unit/import
matrices now also enable that allocator to make invalid lifetimes observable.
The fork identifies this backport as 0.4.4+ownedbuffer1, preserving upstream
ABI dependencies that require cchecksum 0.4.4. The 0.4.4 and 0.4.5 runtime
sources match; the fork retains the current build compiler and packaging.

## Build and verification changes

All mypy flags and targets live in `pyproject.toml`. The existing upstream mypyc
error suppressions moved there unchanged. Incremental mypy checking is disabled:
typed-envs generates type names that cannot safely survive the mypy cache.
Pytest targets/flags live in repository configuration; CI invokes plain pytest.
Native artifact caching includes source, ABI, platform and build inputs.
Every workflow has a path filter. Archive tests use an explicitly configured
operator network instead of duplicating secret-dependent hosted matrices.
The wheel checker derives the required native suffix from each wheel's own tags
and rejects missing or wrong-ABI modules and shared runtimes.

## Local validation

Fresh compiled builds and complete unit/import-audit runs passed on macOS ARM64
Python 3.10, 3.11, 3.12 and 3.13. The final 3.12 run passed 372 tests (3 skipped).
Linux ARM64 Python 3.12 also passed 372 tests (3 skipped). All 37 declared native
modules and the middleware removal contract are checked by the import audit.
A fresh macOS 3.12 wheel passed the ABI checker and all 38 installed-wheel import
audits. The 3.10 native run terminates normally with Python fault handling enabled;
the previous segmentation fault does not recur with upstream's native caller walk.

The separate Python 3.12 source coverage profile runs the complete `tests/unit`
suite: 333 passed, 4 skipped. It measures retained changes without treating source
execution as native-runtime evidence. Against upstream, 263 of 264 added/changed
executable lines in runtime/build helpers were covered (99.62%, ignoring purely
formatting changes). The sole uncovered line imports tomli on Python 3.10 in an
unchanged, relocated upstream helper; the new config-loading statements and all
runtime edits are covered. Whole-package coverage is approximately 69%, and is
not a claim of 90% whole-package coverage.

Reproduce source coverage in a copy without generated binaries using
`tests/source_coverage/pytest.ini` as the copy's root config and
`DANK_MIDS_SOURCE_COVERAGE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest`.
Native checks run separately after a fresh build with
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONFAULTHANDLER=1 python -m pytest`.

Hosted Linux/macOS/Windows Python 3.10–3.13 builds, complete unit suites and
compiled import audits passed all 37 jobs, including generated-C verification.
The 12-cell mypy matrix, lint and source distribution checks also passed.

Linux ARM64 archive integration passed all 33 tests against the native pricing
dependency image. The batching workload queues both historical block groups
together in an isolated process, admits all SDK calls, caps multicalls at 1,000
to avoid live provider payload limits, and measures ID deltas instead of treating
zero-based IDs as counts. Its original density assertions remain intact:
12,515 call IDs, 14 multicalls and 13 requests. Controlled HTTP tests separately
exercise default batching capacity, exact IDs, execution counts, selectors and
cancellation with both small and 200-call groups.

Downstream's immutable Linux ARM64 server image passed all 333 server tests and
Ethereum/Base health, historical price, batch, exact-amount and spot-cache checks.
Base's first cold amount request reached the existing 300-second deadline during
catalog loading and passed after loading; the deadline remains unchanged.
Full native pricing acceptance remains required. After the original provider's
monthly capacity was exhausted, an independent archive run completed 2,310 passing
cases and 17 skips with one batch/individual fOUSG price discrepancy. Three full
token-list replays at the failed block and all ten concurrent historical
batch/individual tests passed unchanged. A complete repeat captures price-path
traces with unchanged assertions and retry limits. It uses a separate populated
catalog snapshot, encrypted loopback archive access, eight concurrent cases and a
1,000-call multicall limit; it does not prove empty-cache startup performance.
Deployment is a separate operation.
