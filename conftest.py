import sys
from pathlib import Path

# Several test modules under tests/ do `from scripts.xxx import yyy`,
# `from simulation.xxx import yyy`, `from ingestion.xxx import yyy`, or
# `from processing.xxx import yyy`. Those top-level directories (scripts/,
# simulation/, ingestion/, processing/) live at the repository root, but
# pytest's default rootdir insertion only adds the directory containing the
# first ancestor without an __init__.py relative to each test file -- for
# tests/ (which has no __init__.py) that is tests/ itself, not the repo root.
# Without the repo root on sys.path, those imports fail with
# "ModuleNotFoundError: No module named 'scripts'" (or 'simulation', etc.).
# A conftest.py at the repository root is loaded before test collection, so
# inserting the repo root here makes every one of those imports resolvable
# regardless of which directory pytest is invoked from.
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
