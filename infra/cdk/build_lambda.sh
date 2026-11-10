#!/usr/bin/env bash
# Build the Lambda code asset: backend app/ + its dependencies for Python 3.12 on x86_64
# Linux (Lambda runtime), into infra/cdk/build/lambda. Needs network (pip download).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../.."
OUT="$HERE/build/lambda"
PY="${PYTHON:-$ROOT/backend/.venv/bin/python}"

rm -rf "$OUT" && mkdir -p "$OUT"
# Runtime dependencies from backend/pyproject.toml (no dev extras), Lambda-compatible wheels.
"$PY" - "$ROOT/backend/pyproject.toml" > "$HERE/build/requirements.txt" <<'PY'
import sys, tomllib
print("\n".join(tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"]))
PY
"$PY" -m pip install --quiet --target "$OUT" \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 \
  --only-binary=:all: -r "$HERE/build/requirements.txt"
cp -r "$ROOT/backend/app" "$OUT/app"
find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} +
du -sh "$OUT"
