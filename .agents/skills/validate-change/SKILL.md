---
name: validate-change
description: Run UnityScraper's lint, compile, version and test checks before committing or opening a pull request.
---

Run from the repository root, in order, and stop at the first failure:

1. `python -m ruff check .`
2. `python -m compileall -q .`
3. `python scripts/check_version.py`
4. `python -m unittest discover -s tests -t .`

If you changed a shell script, also run `sh -n <script>`.

Put new tests in a `tests/test_<area>.py` file; discovery picks them up automatically.
