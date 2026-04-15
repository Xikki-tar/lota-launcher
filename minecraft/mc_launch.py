from __future__ import annotations

import os
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path

from minecraft.mc_client import PreparedVersion, _os_name


def _maven_path_from_name(name: str) -> str | None:
    ext = "jar"
    if "@" in name:
        name, ext = name.split("@", 1)
        ext = ext or "jar"
    parts = name.split(":")
    if len(parts) < 3:
        return None
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else None
    group_path = group.replace(".", "/")
    base = f"{group_path}/{artifact}/{version}"
    filename = f"{artifact}-{version}"
    if classifier:
        filename += f"-{classifier}"
    filename += f".{ext}"
    return f"{base}/{filename}"


@dataclass
class LaunchSpec:
    argv: list[str]
    cwd: Path


def _offline_uuid(username: str) -> str:
    name = f"OfflinePlayer:{username}"
    return str(uuid.uuid3(uuid.NAMESPACE_DNS, name))


def _classpath(prepared: PreparedVersion) -> str:
    libs = []
    for lib in prepared.version_json.get("libraries", []) or []:
        downloads = lib.get("downloads") or {}
        artifact = downloads.get("artifact") or {}
        path = artifact.get("path")
        if path:
            p = prepared.libraries_dir / path
            if p.exists():
                libs.append(str(p))
                continue
        name = lib.get("name")
        if name:
            rel = _maven_path_from_name(str(name))
            if rel:
                p = prepared.libraries_dir / rel
                if p.exists():
                    libs.append(str(p))
    version_jar = prepared.versions_dir / prepared.version_id / f"{prepared.version_id}.jar"
    if version_jar.exists():
        libs.append(str(version_jar))
    sep = ";" if _os_name() == "windows" else ":"
    return sep.join(libs)


def _apply_rules(rules: list[dict] | None) -> bool:
    if not rules:
        return True
    allowed = False
    for rule in rules:
        action = rule.get("action", "allow")
        os_rule = rule.get("os")
        ok = True
        if isinstance(os_rule, dict) and os_rule.get("name"):
            ok = os_rule.get("name") == _os_name()
        if ok:
            allowed = action == "allow"
        elif action == "disallow":
            allowed = False
    return allowed


def _expand_args(args: list, subs: dict) -> list[str]:
    out: list[str] = []
    for entry in args:
        if isinstance(entry, str):
            out.append(_substitute(entry, subs))
            continue
        if isinstance(entry, dict):
            if not _apply_rules(entry.get("rules")):
                continue
            value = entry.get("value")
            if isinstance(value, list):
                for v in value:
                    out.append(_substitute(str(v), subs))
            elif value is not None:
                out.append(_substitute(str(value), subs))
    return out


def _filter_game_args(args: list[str]) -> list[str]:
    cleaned: list[str] = []
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if not arg:
            continue
        if arg == "--demo":
            continue
        if arg.startswith("--") and i + 1 < len(args) and args[i + 1] == "":
            skip_next = True
            continue
        cleaned.append(arg)
    return cleaned


def _substitute(text: str, subs: dict) -> str:
    for k, v in subs.items():
        text = text.replace("${" + k + "}", str(v))
    return text


def build_launch_spec(
    prepared: PreparedVersion,
    username: str,
    java_path: str,
    mem_min_mb: int,
    mem_max_mb: int,
    jvm_args: str | None = None,
    game_dir_override: Path | None = None,
    resolution_width: int | None = None,
    resolution_height: int | None = None,
) -> LaunchSpec:
    username = username or "Player"
    access_token = "0"
    uuid_str = _offline_uuid(username)
    asset_index = (prepared.version_json.get("assetIndex") or {}).get("id") or "legacy"
    game_dir = game_dir_override or prepared.game_dir

    width = str(resolution_width or 1280)
    height = str(resolution_height or 720)

    subs = {
        "auth_player_name": username,
        "version_name": prepared.version_id,
        "game_directory": str(game_dir),
        "assets_root": str(prepared.assets_dir),
        "assets_index_name": asset_index,
        "auth_uuid": uuid_str,
        "auth_access_token": access_token,
        "user_type": "legacy",
        "version_type": prepared.version_json.get("type", "release"),
        "classpath": _classpath(prepared),
        "classpath_separator": ";" if _os_name() == "windows" else ":",
        "library_directory": str(prepared.libraries_dir),
        "natives_directory": str(prepared.natives_dir),
        "launcher_name": "LOTA Launcher",
        "launcher_version": "1.0",
        "clientid": "0",
        "user_properties": "{}",
        "resolution_width": width,
        "resolution_height": height,
        "quickPlayPath": "",
        "quickPlaySingleplayer": "",
        "quickPlayMultiplayer": "",
        "quickPlayRealms": "",
        "auth_xuid": "",
    }

    cmd = [java_path]
    cmd += [f"-Xms{mem_min_mb}M", f"-Xmx{mem_max_mb}M"]

    # Forge on Java 17 needs reflective access flags
    default_opens = [
        "--add-opens", "java.base/java.lang=ALL-UNNAMED",
        "--add-opens", "java.base/java.lang.invoke=ALL-UNNAMED",
        "--add-opens", "java.base/java.util=ALL-UNNAMED",
        "--add-opens", "java.base/java.net=ALL-UNNAMED",
        "--add-exports", "java.base/jdk.internal.misc=ALL-UNNAMED",
    ]

    if jvm_args:
        cmd += shlex.split(jvm_args, posix=_os_name() != "windows")

    # ensure defaults are present (unless user already provided them)
    joined = " ".join(cmd)
    if "java.base/java.lang.invoke=ALL-UNNAMED" not in joined:
        cmd += default_opens

    args = prepared.version_json.get("arguments")
    if isinstance(args, dict):
        jvm_list = _expand_args(args.get("jvm") or [], subs)
        cmd += jvm_list
        if not any(x in ("-cp", "-classpath") for x in jvm_list):
            cmd += ["-cp", subs["classpath"]]
        cmd.append(prepared.version_json.get("mainClass"))
        game_list = _expand_args(args.get("game") or [], subs)
        cmd += _filter_game_args(game_list)
    else:
        legacy = prepared.version_json.get("minecraftArguments", "")
        cmd += ["-cp", subs["classpath"]]
        cmd.append(prepared.version_json.get("mainClass"))
        cmd += _filter_game_args(_expand_args(legacy.split(), subs))

    cmd = [c for c in cmd if c]
    return LaunchSpec(argv=cmd, cwd=game_dir)
