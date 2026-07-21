#!/usr/bin/env bash
set -uo pipefail

REPO="Xikki-tar/lota-launcher"
RUNTIME_DIR="$HOME/.local/share/lota-launcher/runtime"
APPIMAGE_PATH="$RUNTIME_DIR/lota-launcher.AppImage"
ICON_PATH="$RUNTIME_DIR/lota-launcher.png"
VERSION_PATH="$RUNTIME_DIR/version"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_PATH="$DESKTOP_DIR/lota-launcher.desktop"

select_menu() {
  local options=("$@")
  local selected=0
  local key
  local esc=$'\x1b'
  local rendered=0

  tput civis < /dev/tty > /dev/tty

  while true; do
    if [ "$rendered" -eq 1 ]; then
      tput cuu "${#options[@]}" > /dev/tty
    fi
    rendered=1
    for i in "${!options[@]}"; do
      tput el > /dev/tty
      if [ "$i" -eq "$selected" ]; then
        printf "  \033[1;33m> %s\033[0m\n" "${options[$i]}" > /dev/tty
      else
        printf "    %s\n" "${options[$i]}" > /dev/tty
      fi
    done

    IFS= read -rsn1 key < /dev/tty
    if [ "$key" = "$esc" ]; then
      IFS= read -rsn2 -t 0.05 key < /dev/tty
      case "$key" in
        '[A') selected=$(( (selected - 1 + ${#options[@]}) % ${#options[@]} )) ;;
        '[B') selected=$(( (selected + 1) % ${#options[@]} )) ;;
      esac
    elif [ -z "$key" ]; then
      break
    fi
  done

  tput cnorm < /dev/tty > /dev/tty
  return "$selected"
}

fetch_release() {
  echo "-> Looking up the latest release..." >&2
  RESPONSE="$(curl -sSL -w '\n%{http_code}' "https://api.github.com/repos/$REPO/releases/latest")" || {
    echo "Could not reach GitHub (network error)." >&2
    return 1
  }

  HTTP_CODE="$(echo "$RESPONSE" | tail -1)"
  RELEASE_JSON="$(echo "$RESPONSE" | sed '$d')"

  case "$HTTP_CODE" in
    200) ;;
    404)
      echo "GitHub returned 404 - the repo is private or has no releases yet." >&2
      return 1
      ;;
    403)
      echo "GitHub returned 403 - likely rate-limited, try again later." >&2
      return 1
      ;;
    *)
      echo "GitHub API returned HTTP $HTTP_CODE." >&2
      return 1
      ;;
  esac

  APPIMAGE_URL="$(echo "$RELEASE_JSON" | grep -o '"browser_download_url": *"[^"]*\.AppImage"' | head -1 | sed -E 's/.*"(https[^"]*)"/\1/')"
  ICON_URL="$(echo "$RELEASE_JSON" | grep -o '"browser_download_url": *"[^"]*lota-launcher-icon\.png"' | head -1 | sed -E 's/.*"(https[^"]*)"/\1/')"
  REMOTE_TAG="$(echo "$RELEASE_JSON" | grep -o '"tag_name": *"[^"]*"' | head -1 | sed -E 's/.*"([^"]*)"$/\1/')"
  REMOTE_VERSION="${REMOTE_TAG#v}"

  if [ -z "$APPIMAGE_URL" ]; then
    echo "Latest release has no .AppImage asset attached." >&2
    return 1
  fi
  return 0
}

do_install() {
  fetch_release || return 1
  mkdir -p "$RUNTIME_DIR"

  echo "-> Downloading launcher..."
  TMP_APPIMAGE="$RUNTIME_DIR/.lota-launcher.AppImage.tmp.$$"
  if ! curl -fL --progress-bar -o "$TMP_APPIMAGE" "$APPIMAGE_URL"; then
    echo "Download failed." >&2
    rm -f "$TMP_APPIMAGE"
    return 1
  fi
  chmod +x "$TMP_APPIMAGE"
  mv -f "$TMP_APPIMAGE" "$APPIMAGE_PATH"

  if [ -n "$ICON_URL" ]; then
    curl -fsSL -o "$ICON_PATH" "$ICON_URL" || true
  fi

  echo "$REMOTE_VERSION" > "$VERSION_PATH"

  mkdir -p "$DESKTOP_DIR"
  cat > "$DESKTOP_PATH" <<EOF
[Desktop Entry]
Type=Application
Name=Lota Launcher
Exec="$APPIMAGE_PATH"
Icon=$ICON_PATH
Terminal=false
Categories=Game;
EOF
  chmod +x "$DESKTOP_PATH"
  command -v update-desktop-database > /dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" > /dev/null 2>&1

  echo "Installed: $APPIMAGE_PATH"
}

do_reinstall() {
  rm -rf "$RUNTIME_DIR"
  rm -f "$DESKTOP_PATH"
  do_install
}

do_update() {
  if [ ! -f "$APPIMAGE_PATH" ]; then
    echo "Not installed yet, installing instead..."
    do_install
    return
  fi
  fetch_release || return 1
  LOCAL_VERSION="$(cat "$VERSION_PATH" 2> /dev/null || echo "")"
  if [ "$REMOTE_VERSION" = "$LOCAL_VERSION" ]; then
    echo "Already up to date ($LOCAL_VERSION)."
    return
  fi
  do_install
}

do_delete() {
  rm -rf "$RUNTIME_DIR"
  rm -f "$DESKTOP_PATH"
  echo "Removed Lota Launcher."
}

echo "Lota Launcher"
echo
select_menu "Install" "Reinstall" "Update" "Delete"
choice=$?
echo

case "$choice" in
  0) do_install ;;
  1) do_reinstall ;;
  2) do_update ;;
  3) do_delete ;;
esac
