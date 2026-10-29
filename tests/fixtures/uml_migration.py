"""One-shot, locked and recoverable conversion; never touches business data."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

from fpl_config import FIELDS, ConfigurationError, flatten, read_config


def encode(document: dict) -> str:
    lines = ["# Future Props Lab — 私有配置，请勿提交或分享。", ""]
    for section, entries in document.items():
        lines.append(f"[{section}]")
        for name, value in entries.items():
            # The supported scalar/array subset has compatible JSON/TOML encoding.
            encoded = json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
            lines.append(f"{name} = {encoded}")
        lines.append("")
    return "\n".join(lines)


def publish(path: Path, content: str) -> None:
    """Publish a fully flushed 0600 file without replacing an existing config."""
    fd, temporary = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def convert_legacy(path: Path, validate: Callable[[dict], object], *, apply: bool = False) -> dict:
    """Existing TOML wins. A backup is durable before publication or legacy removal."""
    if path.exists():
        validate(read_config(path))
        return {"status": "already_toml", "config": str(path)}
    legacy = path.with_name(".env")
    if not legacy.exists():
        raise ConfigurationError("未找到旧 .env；请从 config.example.toml 创建配置")
    if path.is_symlink() or legacy.is_symlink():
        raise ConfigurationError("配置转换不接受符号链接")
    if not apply:
        document, excluded = legacy_document(legacy)
        validate(flatten(document))
        return {"status": "ready", "config": str(path), "excluded_fields": excluded}
    lock_fd = os.open(path.with_name(".config-migration.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            validate(read_config(path))
            return {"status": "already_toml", "config": str(path)}
        original = legacy.read_bytes()
        document, excluded = legacy_document(legacy)
        values = flatten(document)
        validate(values)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup = legacy.with_name(f".env.backup-{stamp}-{uuid4().hex[:8]}")
        os.chmod(legacy, 0o600)
        publish(backup, original.decode("utf-8"))
        if legacy.read_bytes() != original:
            raise ConfigurationError("旧配置在转换中发生变化，已停止；请重试")
        publish(path, encode(document))
        if read_config(path) != values:
            raise ConfigurationError("配置转换校验失败，请保留现场并恢复旧配置")
        # A concurrent editor must never have its new input removed.
        if legacy.read_bytes() == original:
            legacy.unlink()
        return {
            "status": "converted",
            "config": str(path),
            "backup": str(backup),
            "excluded_fields": excluded,
        }


def legacy_document(path: Path) -> tuple[dict, list[str]]:
    values = dotenv_values(path, interpolate=False)
    if values.get("FPL_STUDIO_TOKEN", ""):
        raise ConfigurationError("旧 FPL_STUDIO_TOKEN 非空，请先迁移为账号认证")
    if not values.get("FPL_SECRETS_KEY"):
        raise ConfigurationError("旧配置缺失加密密钥，请恢复原密钥；不会生成替代密钥")
    document = {}
    recognized = set()
    for section, fields in FIELDS.items():
        entries = {}
        for name, (field, kind) in fields.items():
            env_name = field.upper()
            recognized.add(env_name)
            if env_name not in values or values[env_name] is None:
                continue
            raw = values[env_name]
            if "${" in raw:
                raise ConfigurationError("旧配置含变量插值，请先将其明确为实际值再转换")
            try:
                if kind is int:
                    value = int(raw)
                elif kind is bool:
                    if raw.lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                        raise ValueError
                    value = raw.lower() in ("true", "1", "yes", "on")
                elif kind is list:
                    separator = "," if name == "cors_origins" else os.pathsep
                    value = [item.strip() for item in raw.split(separator) if item.strip()]
                else:
                    value = raw
            except ValueError:
                raise ConfigurationError(f"旧配置的 {env_name} 类型错误") from None
            entries[name] = value
        if entries:
            document[section] = entries
    # Never include unknown input names in output: a malformed key can contain a secret.
    excluded = sorted(set(values) - recognized)
    known_obsolete = {"APP_HOST", "APP_PORT", "FPL_MANAGEMENT_API_KEY", "FPL_STUDIO_TOKEN"}
    safe_excluded = [name if name in known_obsolete else "unknown_field" for name in excluded]
    return document, safe_excluded
