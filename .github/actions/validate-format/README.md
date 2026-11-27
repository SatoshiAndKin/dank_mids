# Formatting validation

This action runs the formatter toolchain previously selected by
[lint-all-the-things v0.3.0](https://github.com/BobTheBuidler/lint-all-the-things/tree/8812bca24dd9c045a5e8240dc391d54213585aad).
It retains its pinned Python, JSON, YAML, Markdown, and TOML formatters.
The implementation checks the resulting diff and has no commit, push, or
pull-request creation step. The caller supplies read-only repository permission.

Markdown retains the existing autofix-only contract. Remaining findings
are informational; any formatter changes fail the diff check.
