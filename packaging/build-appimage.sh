#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/app"
TAURI_DIR="$APP_DIR/src-tauri"
BIN_DIR="$TAURI_DIR/binaries"
PY_BUILD_DIR="$ROOT_DIR/build/appimage"

RUST_TARGET_TRIPLE="$(rustc -vV | sed -n 's/host: //p')"
if [ -z "$RUST_TARGET_TRIPLE" ]; then
  echo "✗ Не удалось определить target triple (нет rustc?)" >&2
  exit 1
fi

echo "=== 1/4: Python-окружение ==="
if [ ! -d "$ROOT_DIR/.venv" ]; then
  python3 -m venv "$ROOT_DIR/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT_DIR/.venv/bin/activate"
pip install --quiet -r "$ROOT_DIR/requirements.txt"
pip install --quiet pyinstaller

echo "=== 2/4: Сборка backend.py в бинарник (PyInstaller) ==="
rm -rf "$PY_BUILD_DIR"
pyinstaller "$ROOT_DIR/backend.py" \
  --name backend \
  --onefile \
  --noconfirm \
  --clean \
  --exclude-module PySide6 \
  --add-data "$ROOT_DIR/assets:assets" \
  --distpath "$PY_BUILD_DIR/dist" \
  --workpath "$PY_BUILD_DIR/work" \
  --specpath "$PY_BUILD_DIR"

mkdir -p "$BIN_DIR"
cp "$PY_BUILD_DIR/dist/backend" "$BIN_DIR/backend-$RUST_TARGET_TRIPLE"
chmod +x "$BIN_DIR/backend-$RUST_TARGET_TRIPLE"

echo "=== 3/4: Зависимости фронтенда ==="
if [ ! -d "$APP_DIR/node_modules" ]; then
  (cd "$APP_DIR" && npm install)
fi

export NO_STRIP=1

patch_gtk_plugin_for_builtin_pixbuf_loaders() {
  local plugin_script="${XDG_CACHE_HOME:-$HOME/.cache}/tauri/linuxdeploy-plugin-gtk.sh"
  [ -f "$plugin_script" ] || return 0
  grep -q "builtin_loaders_guard" "$plugin_script" && return 0

  sed -i \
    -e 's|^copy_tree "\$gdk_pixbuf_binarydir" "\$APPDIR/"$|if [ -d "$gdk_pixbuf_binarydir" ]; then copy_tree "$gdk_pixbuf_binarydir" "$APPDIR/"; else echo "WARNING: builtin_loaders_guard: $gdk_pixbuf_binarydir missing, gdk-pixbuf likely has built-in loaders, skipping"; fi|' \
    -e 's|^if \[ -x "\$gdk_pixbuf_query" \]; then$|if [ -d "$gdk_pixbuf_binarydir" ] \&\& [ -x "$gdk_pixbuf_query" ]; then|' \
    -e 's#^sed -i "s|\$gdk_pixbuf_moduledir/||g" "\$APPDIR/\$gdk_pixbuf_cache_file"$#[ -f "$APPDIR/$gdk_pixbuf_cache_file" ] \&\& &#' \
    "$plugin_script"
  echo "→ Пропатчен linuxdeploy-plugin-gtk.sh под builtin gdk-pixbuf лоадеры"
}

echo "=== 4/4: Сборка Tauri AppImage ==="
if ! (cd "$APP_DIR" && npm run tauri build -- --bundles appimage --verbose); then
  echo "→ Первая попытка не удалась, патчим linuxdeploy-plugin-gtk.sh на всякий случай и пробуем снова..."
  patch_gtk_plugin_for_builtin_pixbuf_loaders
  (cd "$APP_DIR" && npm run tauri build -- --bundles appimage --verbose)
fi

APPIMAGE_DIR="$TAURI_DIR/target/release/bundle/appimage"
echo ""
echo "✓ Готово:"
find "$APPIMAGE_DIR" -maxdepth 1 -iname "*.AppImage"
