#!/usr/bin/env sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

cd "$PROJECT_DIR"

supports_project_python() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

if [ "${PYTHON_BIN+x}" = x ]; then
  if ! supports_project_python "$PYTHON_BIN"; then
    echo "PYTHON_BIN must point to Python 3.11 or newer." >&2
    exit 1
  fi
else
  PYTHON_BIN=python3
  if ! supports_project_python "$PYTHON_BIN"; then
    PYTHON_BIN=
    for candidate in python3.15 python3.14 python3.13 python3.12 python3.11; do
      if command -v "$candidate" >/dev/null 2>&1 && supports_project_python "$candidate"; then
        PYTHON_BIN=$candidate
        break
      fi
    done
  fi
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "CareerFlow requires Python 3.11 or newer. Install it or set PYTHON_BIN to its executable." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
fi

if ! supports_project_python .venv/bin/python; then
  echo "The existing .venv uses Python older than 3.11. Recreate that environment with a supported Python version." >&2
  exit 1
fi

.venv/bin/python -m pip install --disable-pip-version-check -e .
exec .venv/bin/python run.py
