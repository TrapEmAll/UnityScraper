---
name: validate-change
description: Run UnityScraper's lint, compile, version and test checks before committing or opening a pull request.
---

Run from the repository root, in order, and stop at the first failure:

1. `python -m ruff check .`
2. `python -m compileall -q .`
3. `python scripts/check_version.py`
4. `python -m tests.test_unityscraper`
5. `python -m tests.test_integration`

If you changed a shell script, also run `sh -n <script>`.

When adding tests, add the new `unittest.TestCase` class to the `run_tests()`
list in the same file; classes missing from that list do not run in CI.
