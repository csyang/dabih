#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# release.sh
# Dabih — Build and publish a release to the NFS share
#
# Usage:
#   ./release.sh                   Test, build, package, and publish
#   ./release.sh --dry-run         Test, build and package but do not copy to the share
#   ./release.sh --skip-tests      Skip the pytest run
#   ./release.sh --skip-wheel      Skip the wheel + sdist build (source zip only)
#
# Prerequisites:
#   - Python >= 3.11
#   - pip install -e ".[dev]"      (pytest, build, pyslang)
#   - .release.env configured with NFS_RELEASE_PATH   (not needed for --dry-run)
#   - NFS share mounted at NFS_RELEASE_PATH           (not needed for --dry-run)
#
# What this script does:
#   1. Reads the version from pyproject.toml
#   2. Confirms the NFS share is reachable (skipped for --dry-run)
#   3. Runs the pytest suite
#   4. Builds the wheel and sdist into dist/   (python -m build)
#   5. Builds dist/dabih-v<version>-source.zip  (single dabih/ root folder)
#   6. Copies the three files to NFS_RELEASE_PATH/<version>/
#   7. Writes a release manifest (release.json) to the versioned directory
#   8. Updates NFS_RELEASE_PATH/latest.json to point at the new version
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}  →${RESET} $*"; }
success() { echo -e "${GREEN}  ✓${RESET} $*"; }
warn()    { echo -e "${YELLOW}  ⚠${RESET} $*"; }
error()   { echo -e "${RED}  ✗${RESET} $*" >&2; }
header()  { echo -e "\n${BOLD}$*${RESET}"; }

# ── Defaults ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
PYTHON="${PYTHON:-python3}"
DRY_RUN=false
SKIP_TESTS=false
SKIP_WHEEL=false

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      DRY_RUN=true;      shift ;;
    --skip-tests)   SKIP_TESTS=true;   shift ;;
    --skip-wheel)   SKIP_WHEEL=true;   shift ;;
    --help|-h)
      awk '/^# Usage/{p=1} /^# Prerequisites/{p=0} p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      error "Unknown argument: $1"
      exit 1 ;;
  esac
done

# ── Load .release.env (required only when publishing) ────────────────────────
ENV_FILE="$SCRIPT_DIR/.release.env"
NFS_RELEASE_PATH=""
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
elif [[ "$DRY_RUN" == "false" ]]; then
  error ".release.env not found."
  echo ""
  echo "  Create it by copying the example:"
  echo "    cp .release.env.example .release.env"
  echo "  Then set NFS_RELEASE_PATH to your NFS mount point."
  exit 1
fi

if [[ "$DRY_RUN" == "false" && -z "${NFS_RELEASE_PATH:-}" ]]; then
  error "NFS_RELEASE_PATH is not set in .release.env"
  exit 1
fi

# ── Read version from pyproject.toml ─────────────────────────────────────────
VERSION=$("$PYTHON" -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
PRODUCT="Dabih"
RELEASE_DATE=$(date -u +"%Y-%m-%d")
RELEASE_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
ZIP_NAME="dabih-v${VERSION//./_}-source.zip"

# ── Print release summary ─────────────────────────────────────────────────────
header "Dabih Release Script"
echo "  Product:   $PRODUCT v$VERSION"
echo "  Date:      $RELEASE_DATE"
echo "  NFS path:  ${NFS_RELEASE_PATH:-(not set)}"
[[ "$DRY_RUN"    == "true" ]] && echo -e "  ${YELLOW}Mode:      DRY RUN — nothing will be copied${RESET}"
[[ "$SKIP_TESTS" == "true" ]] && echo -e "  ${YELLOW}Tests:     SKIPPED${RESET}"
[[ "$SKIP_WHEEL" == "true" ]] && echo -e "  ${YELLOW}Wheel:     SKIPPED — source zip only${RESET}"
echo ""

# ── Confirm ───────────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == "false" ]]; then
  read -r -p "  Proceed with release? [y/N] " CONFIRM
  [[ "$(echo "$CONFIRM" | tr '[:upper:]' '[:lower:]')" == "y" ]] || { echo "  Cancelled."; exit 0; }
  echo ""
fi

# ── Step 1: NFS reachability check ───────────────────────────────────────────
header "Step 1 — NFS share check"
if [[ "$DRY_RUN" == "true" ]]; then
  info "Dry run: skipping NFS check"
else
  if [[ ! -d "$NFS_RELEASE_PATH" ]]; then
    # Try to create the base directory — will fail cleanly if NFS not mounted
    if ! mkdir -p "$NFS_RELEASE_PATH" 2>/dev/null; then
      error "Cannot reach NFS share: $NFS_RELEASE_PATH"
      error "Ensure the NFS share is mounted before running release."
      exit 1
    fi
  fi
  success "NFS share reachable: $NFS_RELEASE_PATH"
fi

# ── Step 2: Tests ─────────────────────────────────────────────────────────────
header "Step 2 — Tests"
if [[ "$SKIP_TESTS" == "true" ]]; then
  warn "Skipping tests"
else
  info "Running pytest..."
  "$PYTHON" -m pytest -q
  success "Tests passed"
fi

# ── Step 3: Build wheel + sdist ───────────────────────────────────────────────
header "Step 3 — Build wheel and sdist"
rm -rf dist/*.whl dist/*.tar.gz
mkdir -p dist
if [[ "$SKIP_WHEEL" == "true" ]]; then
  warn "Skipping wheel + sdist"
else
  if ! "$PYTHON" -c "import build" 2>/dev/null; then
    error "The 'build' package is not installed.  Run: pip install -e \".[dev]\""
    exit 1
  fi
  info "Running python -m build..."
  "$PYTHON" -m build --outdir dist/ .
  success "Build complete"
fi

# ── Step 4: Source zip ────────────────────────────────────────────────────────
header "Step 4 — Source archive"
rm -f dist/*-source.zip
"$PYTHON" - "$ZIP_NAME" <<'PYEOF'
import os, sys, zipfile
from pathlib import Path

zip_name = sys.argv[1]
root     = Path('.').resolve()
SKIP_DIRS  = {'.git', '__pycache__', '.pytest_cache', 'dist', 'build', '.venv', 'venv'}
SKIP_FILES = {'.release.env', '.DS_Store', 'Thumbs.db'}

def keep(p: Path) -> bool:
    parts = p.relative_to(root).parts
    if any(d in SKIP_DIRS or d.endswith('.egg-info') for d in parts[:-1]):
        return False
    return parts[-1] not in SKIP_FILES and not parts[-1].endswith('.pyc')

with zipfile.ZipFile(Path('dist') / zip_name, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith('.egg-info'))
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if keep(p):
                zf.write(p, 'dabih/' + p.relative_to(root).as_posix())   # single dabih/ root folder
                n += 1
print(f"    {n} files")
PYEOF
success "$ZIP_NAME"

# ── Step 5: Collect release files ────────────────────────────────────────────
header "Step 5 — Collect release files"
RELEASE_FILES=()
for F in dist/"$ZIP_NAME" dist/dabih-"$VERSION"-*.whl dist/dabih-"$VERSION".tar.gz; do
  [[ -f "$F" ]] && RELEASE_FILES+=("$F")
done
if [[ ${#RELEASE_FILES[@]} -eq 0 ]]; then
  error "No release files found in dist/"
  exit 1
fi
info "Found ${#RELEASE_FILES[@]} release file(s):"
for F in "${RELEASE_FILES[@]}"; do
  SIZE=$(du -sh "$F" | cut -f1)
  echo "    $SIZE  $(basename "$F")"
done

# ── Step 6: Copy to NFS ───────────────────────────────────────────────────────
header "Step 6 — Publish to NFS"
VERSIONED_DIR="${NFS_RELEASE_PATH:-}/$VERSION"

if [[ "$DRY_RUN" == "true" ]]; then
  info "Dry run: would copy to ${NFS_RELEASE_PATH:-<NFS_RELEASE_PATH>}/$VERSION/"
  for F in "${RELEASE_FILES[@]}"; do
    echo "    $(basename "$F")"
  done
else
  mkdir -p "$VERSIONED_DIR"
  for F in "${RELEASE_FILES[@]}"; do
    info "Copying $(basename "$F")..."
    cp "$F" "$VERSIONED_DIR/$(basename "$F")"
    success "$(basename "$F") → $VERSIONED_DIR/"
  done

  # ── Step 7: Write release manifest ────────────────────────────────────────
  header "Step 7 — Write release manifest"
  "$PYTHON" - "$VERSIONED_DIR" "$NFS_RELEASE_PATH" "$PRODUCT" "$VERSION" \
              "$RELEASE_DATE" "$RELEASE_TIME" "${RELEASE_FILES[@]}" <<'PYEOF'
import json, sys
from pathlib import Path
vdir, base, product, version, date, ts, *files = sys.argv[1:]
(Path(vdir) / 'release.json').write_text(json.dumps({
    "product": product, "version": version, "date": date, "timestamp": ts,
    "files": [Path(f).name for f in files],
}, indent=2) + "\n")
(Path(base) / 'latest.json').write_text(json.dumps({
    "version": version, "date": date, "timestamp": ts, "path": version,
}, indent=2) + "\n")
PYEOF
  success "release.json written"
  success "latest.json updated → v$VERSION"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
header "Release complete"
if [[ "$DRY_RUN" == "true" ]]; then
  echo -e "  ${YELLOW}Dry run — nothing was copied.  Artifacts are in dist/${RESET}"
else
  echo -e "  ${GREEN}Dabih v$VERSION published to:${RESET}"
  echo "  $VERSIONED_DIR/"
  echo ""
  echo "  Colleagues can install from:"
  echo "  $NFS_RELEASE_PATH/$VERSION/"
fi
echo ""
