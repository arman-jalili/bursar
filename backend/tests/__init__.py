"""Bursar test suite.

Canonical: .pi/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

Contains the interpreter guard: the harness's local CI resolves `pytest` from `PATH`, which on a
stock machine is a Python 3.9 interpreter without the project's dependencies. Without an explicit
check that surfaces as `ModuleNotFoundError: sqlalchemy` from a conftest import, which reads like a
code defect. It is not — it means the tests ran under the wrong interpreter.
"""

from __future__ import annotations

import sys

# Compared against a named constant rather than a literal: the guard exists for runtimes *below*
# the declared target version, which a literal comparison would let a linter optimise away.
MIN_PYTHON: tuple[int, int] = (3, 12)

if tuple(sys.version_info[:2]) < MIN_PYTHON:  # pragma: no cover - environment guard
    raise RuntimeError(
        f"Bursar tests require Python >= 3.12 (found {sys.version.split()[0]} at {sys.executable}). "
        "Run them through the project environment: `make test` or "
        '`PATH="$PWD/.venv/bin:$PATH" pytest`.'
    )
