#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${DIST_DIR:-$SOURCE_DIR/dist}"
BUILD_TARGET="linux"

usage() {
  echo "Usage: $0 [--linux|--windows|--all|--assets-only] [--dist OUTPUT_DIRECTORY]"
  echo "Environment: PYTHON_BIN, WIN_PYTHON, DIST_DIR"
}

while (($#)); do
  case "$1" in
    --linux) BUILD_TARGET="linux" ;;
    --windows) BUILD_TARGET="windows" ;;
    --all) BUILD_TARGET="all" ;;
    --assets-only) BUILD_TARGET="assets" ;;
    --dist)
      shift
      if (($# == 0)); then
        echo "--dist requires a directory" >&2
        exit 2
      fi
      DIST_DIR="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "$SOURCE_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$SOURCE_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

mkdir -p "$DIST_DIR"

common_assets() {
  mkdir -p "$DIST_DIR/plugins" "$DIST_DIR/OperationProjects"
  if [[ -d "$SOURCE_DIR/plugins" ]]; then
    cp -a "$SOURCE_DIR/plugins/." "$DIST_DIR/plugins/"
  fi
  if [[ ! -d "$SOURCE_DIR/qemu" ]]; then
    echo "Required QEMU directory was not found: $SOURCE_DIR/qemu" >&2
    return 1
  fi
  if [[ ! -d "$SOURCE_DIR/nasm" ]]; then
    echo "Required NASM directory was not found: $SOURCE_DIR/nasm" >&2
    return 1
  fi

  mkdir -p "$DIST_DIR/qemu" "$DIST_DIR/nasm"
  cp -a "$SOURCE_DIR/qemu/." "$DIST_DIR/qemu/"
  cp -a "$SOURCE_DIR/nasm/." "$DIST_DIR/nasm/"

  local required_asset
  for required_asset in \
    "qemu/qemu-system-x86_64" \
    "qemu/qemu-system-x86_64.exe" \
    "nasm/nasm" \
    "nasm/nasm.exe"
  do
    if [[ ! -f "$DIST_DIR/$required_asset" ]]; then
      echo "Asset copy failed; missing: $DIST_DIR/$required_asset" >&2
      return 1
    fi
  done
  if [[ -f "$SOURCE_DIR/LICENCE" ]]; then
    cp "$SOURCE_DIR/LICENCE" "$DIST_DIR/LICENCE"
  fi

  cat > "$DIST_DIR/linux-help.txt" <<'EOF'
On Linux, make the bundled programs executable before the first launch:

chmod +x OperationCrafter-Linux qemu/qemu-system-x86_64 nasm/nasm
EOF

  chmod +x "$DIST_DIR/qemu/qemu-system-x86_64" "$DIST_DIR/nasm/nasm"
  echo "Copied and verified QEMU and NASM in: $DIST_DIR"
}

windows_python_ready() {
  local candidate="$1"
  [[ -f "$candidate" ]] && \
    WINEDEBUG=-all wine "$candidate" -c \
      "import PyInstaller, PyQt6" >/dev/null 2>&1
}

find_windows_python() {
  if [[ -n "${WIN_PYTHON:-}" ]]; then
    if windows_python_ready "$WIN_PYTHON"; then
      return 0
    fi
    echo "WIN_PYTHON is not usable or is missing PyInstaller/PyQt6: $WIN_PYTHON" >&2
    return 1
  fi

  local -a candidates=()
  local windows_profile=""
  local drive_prefix path_after_users candidate

  candidates+=(
    "$SOURCE_DIR/venv/Scripts/python.exe"
    "$SOURCE_DIR/.venv/Scripts/python.exe"
  )

  if [[ "$SOURCE_DIR" == */Users/* ]]; then
    drive_prefix="${SOURCE_DIR%%/Users/*}"
    path_after_users="${SOURCE_DIR#*/Users/}"
    windows_profile="$drive_prefix/Users/${path_after_users%%/*}"
    shopt -s nullglob
    candidates+=(
      "$windows_profile"/AppData/Local/Programs/Python/Python*/python.exe
    )
    shopt -u nullglob
  fi

  for candidate in "${candidates[@]}"; do
    if windows_python_ready "$candidate"; then
      WIN_PYTHON="$candidate"
      export WIN_PYTHON
      echo "Using Windows Python: $WIN_PYTHON"
      return 0
    fi
  done

  echo "No Wine-accessible Windows Python with PyInstaller and PyQt6 was found." >&2
  echo "Install the Windows dependencies or set WIN_PYTHON explicitly." >&2
  return 1
}

preflight_windows() {
  if ! command -v wine >/dev/null 2>&1 || ! command -v winepath >/dev/null 2>&1; then
    echo "Windows packaging requires wine and winepath." >&2
    return 1
  fi
  find_windows_python
}

build_linux() {
  "$PYTHON_BIN" -m PyInstaller "$SOURCE_DIR/main.py" \
    --name "OperationCrafter-Linux" \
    --onefile --windowed --noconfirm \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR/linux-work" \
    --specpath "$WORK_DIR" \
    --add-data "$SOURCE_DIR/icon-blue.png:." \
    --add-data "$SOURCE_DIR/app:app" \
    --paths "$SOURCE_DIR" \
    --collect-all PyQt6 \
    --hidden-import glob \
    --hidden-import json \
    --hidden-import shutil
}

build_windows() {
  local win_source win_dist win_work
  win_source="$(winepath -w "$SOURCE_DIR")"
  win_dist="$(winepath -w "$DIST_DIR")"
  win_work="$(winepath -w "$WORK_DIR")"

  wine "$WIN_PYTHON" -m PyInstaller "${win_source}\\main.py" \
    --name "OperationCrafter-Windows" \
    --exclude PyQt5 --exclude PySide6 \
    --onefile --windowed --noconfirm \
    --distpath "$win_dist" \
    --workpath "${win_work}\\windows-work" \
    --specpath "$win_work" \
    --add-data "${win_source}\\icon-blue.png;." \
    --icon "${win_source}\\icon-blue.ico" \
    --add-data "${win_source}\\app;app" \
    --paths "$win_source" \
    --collect-all PyQt6 \
    --hidden-import glob \
    --hidden-import json \
    --hidden-import shutil
}

# Check the Windows toolchain before spending time on the Linux half of --all.
case "$BUILD_TARGET" in
  windows|all) preflight_windows ;;
esac

# Copy support tools before PyInstaller so a later build failure cannot leave an
# otherwise successful executable without its QEMU and NASM directories.
common_assets

if [[ "$BUILD_TARGET" == "assets" ]]; then
  echo "Asset packaging complete: $DIST_DIR"
  exit 0
fi

WORK_DIR="$(mktemp -d "$SOURCE_DIR/.pyinstaller-build.XXXXXX")"
cleanup() {
  if [[ -n "${WORK_DIR:-}" && "$WORK_DIR" == "$SOURCE_DIR"/.pyinstaller-build.* ]]; then
    rm -rf -- "$WORK_DIR"
  fi
}
trap cleanup EXIT

case "$BUILD_TARGET" in
  linux) build_linux ;;
  windows) build_windows ;;
  all)
    build_linux
    build_windows
    ;;
esac

echo "Packaging complete: $DIST_DIR"
