#!/usr/bin/env bash
# Первичная настройка окружения
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Настройка Python ==="

if [ ! -d "$SCRIPT_DIR/.venv" ]; then
  echo "→ Создание виртуального окружения..."
  python3 -m venv "$SCRIPT_DIR/.venv"
fi

source "$SCRIPT_DIR/.venv/bin/activate"
echo "→ Установка зависимостей..."
pip install -r "$SCRIPT_DIR/requirements.txt" --quiet

echo ""
echo "=== Настройка Node.js ==="

if [ ! -d "$SCRIPT_DIR/app/node_modules" ]; then
  echo "→ npm install..."
  cd "$SCRIPT_DIR/app"
  npm install
else
  echo "→ node_modules уже есть"
fi

echo ""
echo "=== Готово ==="
echo "Для запуска: ./dev.sh"
