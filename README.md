# Lota Launcher

Desktop launcher for Lota — Minecraft modpack builds, account/friends, and auto-updates, for Linux, Windows, and macOS.

## Download

Grab the latest build from [Releases](https://github.com/Xikki-tar/lota-launcher/releases).

- **Linux (AppImage)**
  ```
  curl -fsSL https://raw.githubusercontent.com/Xikki-tar/lota-launcher/main/packaging/download-linux.sh | bash
  ```
  Interactive menu — install, reinstall, update, or delete. Installs to `~/.local/share/lota-launcher/runtime`, with a desktop entry and icon set up automatically.
- **Windows** — `.exe` (NSIS) or `.msi` installer, or the portable `.zip` (no install needed)
- **macOS** — `.dmg` or `.zip` (Apple Silicon only for now, unsigned — Gatekeeper will warn on first launch)

## Features

- Library of modpack builds — install, update, launch
- Account, skins, friends
- Auto-update on all three platforms

## Development

```
./setup.sh   # first-time setup: Python venv + npm install
./dev.sh     # runs the Python backend + Tauri dev
```

Requires Python 3.12+, Node 20+, and a Rust toolchain.

## Building

- **Linux**: `./packaging/build-appimage.sh`
- **Windows / macOS**: built in CI (`.github/workflows/windows-build.yml`, `macos-build.yml`) — trigger manually from the Actions tab, or push a version tag (`git tag v0.1.1 && git push origin v0.1.1`) to also publish the build to a GitHub Release.

## Architecture

- **`app/`** — Tauri (Rust) desktop app + React frontend
- **`backend.py`** — Python/Flask backend, runs as a sidecar process spawned by the Tauri app
- **`updater/`** — standalone Rust/Tauri updater used only on Windows (Windows can't replace its own running `.exe`, so the launcher hands off to this separate binary first, which updates and relaunches it). Linux and macOS update themselves in place through the running app instead.

## License

See [LICENSE](LICENSE). Source is available for viewing and pull requests; redistribution, forking outside of contributing, and commercial or competing use are not permitted without permission.
