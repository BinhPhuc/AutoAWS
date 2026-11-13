#!/usr/bin/env bash
# Build the Lambda code asset: backend app/ + its dependencies for Python 3.12 on x86_64
# Linux (Lambda runtime), into infra/cdk/build/lambda. Needs network (pip download).
#
#   ./build_lambda.sh            # deps reinstalled only when backend dependencies changed
#   ./build_lambda.sh --clean    # reinstall everything
#
# Kept light on the machine: low CPU/IO priority, no .pyc compilation (Lambda does not need
# it), and the thousands of dependency files are written once, not on every build. To cap
# memory as well: systemd-run --user --scope -p MemoryMax=2G -p MemorySwapMax=0 ./build_lambda.sh
# (MemorySwapMax=0: with zram swap, as on Fedora, the swapped pages still live in RAM).
# The editor must not watch build/ and cdk.out/ (tens of thousands of files): see README.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../.."
OUT="$HERE/build/lambda"
REQ="$HERE/build/requirements.txt"
STAMP="$OUT/.requirements.sha256"
PY="${PYTHON:-$ROOT/backend/.venv/bin/python}"
export PIP_DISABLE_PIP_VERSION_CHECK=1

# Run the heavy steps at the lowest priority so the desktop stays responsive
LOW=(nice -n 19)
command -v ionice >/dev/null && LOW+=(ionice -c 3)

mkdir -p "$HERE/build"
[[ "${1:-}" == "--clean" ]] && rm -rf "$OUT"

# Runtime dependencies from backend/pyproject.toml (no dev extras)
"$PY" - "$ROOT/backend/pyproject.toml" > "$REQ" <<'PY'
import sys, tomllib
print("\n".join(tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"]))
PY
want="$(sha256sum "$REQ" | cut -d' ' -f1)"

if [[ -f "$STAMP" && "$(cat "$STAMP")" == "$want" ]]; then
  echo "Dependencies unchanged: refreshing app/ only"
else
  echo "Installing dependencies (Lambda-compatible wheels)…"
  rm -rf "$OUT" && mkdir -p "$OUT"
  "${LOW[@]}" "$PY" -m pip install --quiet --no-compile --target "$OUT" \
    --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 \
    --only-binary=:all: -r "$REQ"
  echo "$want" > "$STAMP"
fi

# The backend code itself: small, replaced on every build
rm -rf "$OUT/app"
cp -r "$ROOT/backend/app" "$OUT/app"
find "$OUT/app" -name "__pycache__" -type d -prune -exec rm -rf {} +
du -sh "$OUT"
