#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${DIST_DIR:-$SOURCE_DIR/dist}"
BUILD_TARGET="linux"

usage() {
  echo "Usage: $0 [--linux|--windows|--all] [--dist OUTPUT_DIRECTORY]"
  echo "Environment: PYTHON_BIN, WIN_PYTHON, DIST_DIR"
}

while (($#)); do
  case "$1" in
    --linux) BUILD_TARGET="linux" ;;
    --windows) BUILD_TARGET="windows" ;;
    --all) BUILD_TARGET="all" ;;
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

WORK_DIR="$(mktemp -d "$SOURCE_DIR/.pyinstaller-build.XXXXXX")"
cleanup() {
  if [[ -n "${WORK_DIR:-}" && "$WORK_DIR" == "$SOURCE_DIR"/.pyinstaller-build.* ]]; then
    rm -rf -- "$WORK_DIR"
  fi
}
trap cleanup EXIT

mkdir -p "$DIST_DIR"

common_assets() {
  mkdir -p "$DIST_DIR/plugins" "$DIST_DIR/OperationProjects"
  if [[ -d "$SOURCE_DIR/plugins" ]]; then
    cp -a "$SOURCE_DIR/plugins/." "$DIST_DIR/plugins/"
  fi
  if [[ -d "$SOURCE_DIR/qemu" ]]; then
    mkdir -p "$DIST_DIR/qemu"
    cp -a "$SOURCE_DIR/qemu/." "$DIST_DIR/qemu/"
  fi
  if [[ -d "$SOURCE_DIR/nasm" ]]; then
    mkdir -p "$DIST_DIR/nasm"
    cp -a "$SOURCE_DIR/nasm/." "$DIST_DIR/nasm/"
  fi
  if [[ -f "$SOURCE_DIR/LICENCE" ]]; then
    cp "$SOURCE_DIR/LICENCE" "$DIST_DIR/LICENCE"
  fi

  cat > "$DIST_DIR/linux-help.txt" <<'EOF'
On Linux, make the bundled programs executable before the first launch:

chmod +x OperationCrafter-Linux qemu/qemu-system-x86_64 nasm/nasm
EOF
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
  if ! command -v wine >/dev/null 2>&1 || ! command -v winepath >/dev/null 2>&1; then
    echo "Windows packaging requires wine and winepath." >&2
    exit 1
  fi
  if [[ -z "${WIN_PYTHON:-}" || ! -f "$WIN_PYTHON" ]]; then
    echo "Set WIN_PYTHON to a Windows Python executable accessible through Wine." >&2
    exit 1
  fi

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

case "$BUILD_TARGET" in
  linux) build_linux ;;
  windows) build_windows ;;
  all)
    build_linux
    build_windows
    ;;
esac

common_assets
echo "Packaging complete: $DIST_DIR"
