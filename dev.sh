#!/usr/bin/env bash
# Запуск в режиме разработки: Python бэкенд + Tauri UI
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT_FILE="$SCRIPT_DIR/.dev-port"

# Активируем venv если есть
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  source "$SCRIPT_DIR/.venv/bin/activate"
elif [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
  source "$SCRIPT_DIR/venv/bin/activate"
fi

# Чистим старый port-file
rm -f "$PORT_FILE"

echo "→ Запуск Python бэкенда..."
python "$SCRIPT_DIR/backend.py" &
BACKEND_PID=$!

# Ждём пока бэкенд напишет порт (до 10 сек)
for i in $(seq 1 50); do
  [ -f "$PORT_FILE" ] && break
  sleep 0.2
done

if [ ! -f "$PORT_FILE" ]; then
  echo "✗ Бэкенд не запустился (нет .dev-port)"
  kill "$BACKEND_PID" 2>/dev/null || true
  exit 1
fi

PORT=$(cat "$PORT_FILE")
echo "✓ Бэкенд слушает на порту $PORT"

# Убиваем бэкенд при выходе
cleanup() {
  echo ""
  echo "→ Остановка бэкенда (PID $BACKEND_PID)..."
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "→ Запуск Tauri..."
cd "$SCRIPT_DIR/app"
VITE_BACKEND_PORT="$PORT" WEBKIT_DISABLE_DMABUF_RENDERER=1 npm run tauri dev
