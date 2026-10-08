# Fork changes against upstream 4.20.215

The baseline is upstream commit `88e06a54b5fb9f26f64752617c3a1f2e6460d26f`.
The merge preserves fork and upstream history. Upstream owns Web3 v7 dispatch,
response envelopes and IDs, waiter tracking, bounded shutdown, Hatchling, uv,
and the pinned aiolimiter submodule (`441d80fca626e1eab5bad63c19a32167a915cb19`).

## Retained runtime repairs

| Source | Required behavior | Regression tests |
| --- | --- | --- |
| `_block.py`, `controller.py`, `semaphores.py`, `eth.py` | Retain hash and canonical selectors through header lookup, admission, batch grouping and direct RPC; validate the returned header hash; propagate header RPC errors with their original details; retain upstream response IDs. | `test_block_identity.py`, `test_hash_rpc.py`, `test_hash_header_errors.py` |
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
`ffd7e2cc096bbfa79dd15d0f0ee0c65f0382c303`. It retains transaction timestamp
schemas and isolated native build repairs, uses canonical RPC string trace enums,
and decodes block reward traces without invented transaction fields.

## Requester thread lifetime

Requester methods stay compiled, while `HTTPRequesterThread` keeps the Python
object layout of its `threading.Thread` base. The native class destructor did not
clear inherited weak references; debug-allocator imports/teardown crashed on
Python 3.12–3.13, and stopped instances left invalid weak references. The regression
creates, stops and collects multiple threads and checks their weak references in
a fresh debug-allocator process. Existing startup, cancellation and bounded
shutdown tests retain their assertions.

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
Every workflow has a path filter. Generated-C commits run once per human
change; bot-triggered follow-up runs do not recursively commit compiler output
and cancel their own platform matrix. Archive tests use an explicitly configured
operator network instead of duplicating secret-dependent hosted matrices.
The wheel checker derives the required native suffix from each wheel's own tags
and rejects missing or wrong-ABI modules and shared runtimes.

## Local validation

Fresh compiled builds and complete unit/import-audit runs passed on macOS ARM64
Python 3.10, 3.11, 3.12 and 3.13. The final 3.12 and 3.13 runs passed 373 tests each (3 skipped),
and 3.10 passed 375 (1 skipped), with `PYTHONMALLOC=debug`.
Linux ARM64 Python 3.12 also passed 373 tests (3 skipped) under the debug allocator. All 37 declared native
modules and the middleware removal contract are checked by the import audit.
A fresh macOS 3.12 wheel passed the ABI checker and all 38 installed-wheel import
audits. The 3.10 native run terminates normally with Python fault handling enabled;
the previous segmentation fault does not recur with upstream's native caller walk.

The separate Python 3.12 source coverage profile runs the complete `tests/unit`
suite: 334 passed, 4 skipped. It measures retained changes without treating source
execution as native-runtime evidence. Against upstream, 220 of 222 added/changed executable lines in runtime/build helpers were
covered (99.10%, using `git diff --ignore-all-space` against upstream).
The two uncovered lines are the existing Python 3.10 caller formatting statement
and the relocated tomli import; both belong to Python 3.10 compatibility paths.
The new requester-layout import and decorator are covered. Whole-package coverage is approximately 69%, and is
not a claim of 90% whole-package coverage.

Reproduce source coverage in a copy without generated binaries using
`tests/source_coverage/pytest.ini` as the copy's root config and
`DANK_MIDS_SOURCE_COVERAGE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest`.
Native checks run separately after a fresh build with
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONFAULTHANDLER=1 python -m pytest`.

Hosted Linux/macOS/Windows Python 3.10–3.13 builds, complete unit suites and
compiled import audits passed all 37 jobs with the debug allocator enabled,
including generated-C verification.
The 12-cell mypy matrix, lint and source distribution checks also passed.

Linux ARM64 archive integration passed all 33 tests against the native pricing
dependency image. The batching workload queues both historical block groups
together in an isolated process, admits all SDK calls, caps multicalls at 1,000
to avoid live provider payload limits, and measures ID deltas instead of treating
zero-based IDs as counts. Its original density assertions remain intact:
12,515 call IDs, 14 multicalls and 13 requests. Controlled HTTP tests separately
exercise default batching capacity, exact IDs, execution counts, selectors and
cancellation with both small and 200-call groups.

## Downstream acceptance

The tested immutable SDK dependency is
`90baeae436f4d359538b11988c13a86004e2e087`. Its runtime matches the fully tested
`fa4b454fb8d33c2f412709da4daca522cd4f7e47`; the intervening change pins the
reproducible evmspec build. Subsequent commits contain generated C and the CI
recursion guard, without changing runtime source.

Pricing revision `8c8387ec15f4f8a119214df5971f10b79cfb6962` retains current
fork master `cb4a12376b807b1b9f27d9963f0c457edf02fda7`, Web3 v7 middleware,
owned HTTP attempts, and native dependency repairs. Its complete freshly compiled
Linux ARM64 suite passed 2,664 tests with 17 skips under the debug allocator.
It also repairs a reproducible Pony query-translator race and prevents simulated
IronBank interest accrual from changing subsequent oracle reads in a multicall.
Separate Python source coverage covers all 40 changed runtime statements (100%).
Brownie's existing native bytecode-memory and explorer-timeout regressions passed
all 77 cases. The SDK archive suite passed all 33 cases against the same archive.

The final immutable Linux ARM64 server image passed 346 tests and four subtests,
strict mypy, Ruff, formatting, deptry and the lock check. All eight Ethereum HTTP
scenarios passed: health, historical USDC/WETH, cached reads, ordered duplicate
batches, single/mixed amounts, and preservation of the spot cache after amount
quotes. Independent native calls preserved raw amounts 1,000,001 and 2,000,001
and the canonical hash of Ethereum block 18,000,000.

Final Base acceptance is explicitly deferred at the user's request after the
original archive provider exhausted its quota. Earlier Base observations are not
acceptance of this final dependency image. Archive validation uses a populated
catalog snapshot and does not establish empty-cache startup performance.
Two evmspec trace-enum failures also reproduce on the original compiled schema
revision; the fresh macOS and Linux ARM64 builds both pass the other 365 cases.
Those results describe the earlier migration validation. The SDK sync and header
repair merged in PR #10; pricing and server dependency upgrades also merged.
Original draft branches remain retained until replacement validation passes.

## Header lookup error propagation

Before checking for a missing hash-selected block, route error responses through
the existing SDK error handler. Callers retain the original error code, message,
arbitrary data (including omitted data) and header-request context. A genuine null
header still raises `BlockNotFound`. Errors remain uncached; the next lookup may
recover, and successful immutable header metadata is then reused.

The controlled HTTP regressions exercise the actual compiled controller, both
canonical-selector settings, null/string/list/object/omitted error data, repeated
failures, recovery and unchanged hash-bound calls. The original implementation
reproduces the reported `BlockNotFound` defect. A fresh macOS ARM64 Python 3.12
build passes the complete configured suite: 384 passed, 3 skipped, including
compiled import audits. The separate full unit source profile passes 345 cases
with 4 skips and covers all three added executable lines (100%). Configured mypy
passes all 60 source files. Git dependency metadata and release publishing
configuration are unchanged by this repair.

## Static documentation and trace schema refresh

Sphinx AutoAPI parses SDK source files. Documentation builds install only pinned
documentation dependencies and require no Brownie runtime, network connection,
RPC endpoint, or secret. CI uploads the HTML artifact and does not publish Pages.
Generated HTML stays outside Git; written guides remain in `docs/`.

The refreshed native schema accepts call types `call`, `delegatecall`, and
`staticcall`, and reward types `block` and `uncle`. It rejects numeric enum values.
Transaction traces still require transaction identity; block rewards require
block identity and their actual author/value/reward-type fields.

A fresh macOS ARM64 Python 3.12 SDK build with this schema passes all 384 tests
with three skips under the debug allocator. Its installed wheel passes ABI and
external-origin import audits. The configured type check passes all 60 files.
Hosted platform matrix results belong to the PR checks.
