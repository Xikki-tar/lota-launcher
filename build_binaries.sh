#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"
PYINSTALLER="$VENV_DIR/bin/pyinstaller"
APP_ICON="$ROOT_DIR/assets/logo.ico"

if [[ ! -x "$PYINSTALLER" ]]; then
  echo "PyInstaller not found in $VENV_DIR."
  echo "Run:"
  echo "  cd $ROOT_DIR"
  echo "  source .venv/bin/activate"
  echo "  python -m pip install -r requirements.txt"
  echo "  python -m pip install pyinstaller"
  exit 1
fi

if ! "$PYTHON" -m nuitka --version >/dev/null 2>&1; then
  echo "Nuitka not found in $VENV_DIR."
  echo "Run:"
  echo "  source .venv/bin/activate"
  echo "  python -m pip install nuitka"
  exit 1
fi

if [[ ! -f "$APP_ICON" ]]; then
  echo "App icon not found: $APP_ICON"
  exit 1
fi

cd "$ROOT_DIR"

echo "Cleaning previous build artifacts..."
rm -rf build dist
find "$ROOT_DIR" -maxdepth 1 -type f -name '*.spec' -delete

echo "Building launcher..."
"$PYINSTALLER" \
  --noconfirm \
  --clean \
  --onefile \
  --windowed \
  --name Lota-launcher \
  --icon "$APP_ICON" \
  --add-data "assets:assets" \
  launcher.py

echo "Building updater..."
"$PYINSTALLER" \
  --noconfirm \
  --clean \
  --onefile \
  --windowed \
  --name updater \
  --icon "$APP_ICON" \
  --add-data "assets:assets" \
  updater.py

echo "Building installer with Nuitka..."
"$PYTHON" -m nuitka \
  --onefile \
  --enable-plugin=pyside6 \
  --include-data-dir=assets=assets \
  --output-filename=installer \
  --output-dir=dist \
  --assume-yes-for-downloads \
  installer.py

echo
echo "Build complete. Files:"
find "$ROOT_DIR/dist" -maxdepth 1 -type f | sort
echo
echo "Run installer with:"
echo "  LOTA_API_BASES=https://ru.lota.work,https://eu.lota.work $ROOT_DIR/dist/installer"
