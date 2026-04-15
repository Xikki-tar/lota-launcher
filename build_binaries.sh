#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYINSTALLER="$VENV_DIR/bin/pyinstaller"

if [[ ! -x "$PYINSTALLER" ]]; then
  echo "PyInstaller not found in $VENV_DIR."
  echo "Run:"
  echo "  cd $ROOT_DIR"
  echo "  source .venv/bin/activate"
  echo "  python -m pip install -r requirements.txt"
  echo "  python -m pip install pyinstaller"
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
  --name launcher \
  --add-data "assets:assets" \
  --add-data "assets/steve.png:assets" \
  launcher.py

echo "Building updater..."
"$PYINSTALLER" \
  --noconfirm \
  --clean \
  --onefile \
  --name updater \
  updater.py

echo "Building installer..."
"$PYINSTALLER" \
  --noconfirm \
  --clean \
  --onefile \
  --name installer \
  --add-data "assets:assets" \
  installer.py

echo
echo "Build complete. Files:"
find "$ROOT_DIR/dist" -maxdepth 1 -type f | sort
echo
echo "Run installer with:"
echo "  LOTA_API_BASES=https://ru.lota.work,https://eu.lota.work $ROOT_DIR/dist/installer"
