#!/usr/bin/env bash
set -uo pipefail

REPO="Xikki-tar/lota-launcher"

echo "-> Looking up the latest release..."
RESPONSE="$(curl -sSL -w '\n%{http_code}' "https://api.github.com/repos/$REPO/releases/latest")" || {
  echo "Could not reach GitHub (network error)." >&2
  exit 1
}

HTTP_CODE="$(echo "$RESPONSE" | tail -1)"
RELEASE_JSON="$(echo "$RESPONSE" | sed '$d')"

case "$HTTP_CODE" in
  200) ;;
  404)
    echo "GitHub returned 404 - the repo is private or has no releases yet." >&2
    exit 1
    ;;
  403)
    echo "GitHub returned 403 - likely rate-limited, try again later." >&2
    exit 1
    ;;
  *)
    echo "GitHub API returned HTTP $HTTP_CODE." >&2
    exit 1
    ;;
esac

URL="$(echo "$RELEASE_JSON" | grep -o '"browser_download_url": *"[^"]*\.AppImage"' | head -1 | sed -E 's/.*"(https[^"]*)"/\1/')"
if [ -z "$URL" ]; then
  echo "Latest release has no .AppImage asset attached." >&2
  exit 1
fi

NAME="$(basename "$URL")"
echo "-> Downloading $NAME..."
if ! curl -fsSL -o "$NAME" "$URL"; then
  echo "Download failed." >&2
  exit 1
fi
chmod +x "$NAME"

echo "Done: ./$NAME"
echo "Run it with: ./$NAME"
