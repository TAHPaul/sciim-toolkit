from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


class UserSettingsError(Exception):
    pass


APP_DIR_NAME_MACOS = "SciIm Toolkit"
APP_DIR_NAME_GENERIC = "sciim-toolkit"


@dataclass
class UserSettings:
    autosave_enabled: bool = True
    autosave_interval_ms: int = 60000
    recent_projects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["autosave_interval_ms"] = max(1000, min(int(self.autosave_interval_ms), 600000))
        payload["recent_projects"] = [str(Path(p)) for p in self.recent_projects[:10]]
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> "UserSettings":
        autosave_enabled = bool(data.get("autosave_enabled", True))
        autosave_interval_ms = int(data.get("autosave_interval_ms", 60000))
        autosave_interval_ms = max(1000, min(autosave_interval_ms, 600000))

        raw_recent = data.get("recent_projects", [])
        recent_projects: list[str] = []
        if isinstance(raw_recent, list):
            for value in raw_recent:
                if not value:
                    continue
                recent_projects.append(str(Path(str(value))))

        return cls(
            autosave_enabled=autosave_enabled,
            autosave_interval_ms=autosave_interval_ms,
            recent_projects=recent_projects[:10],
        )


def _legacy_settings_path() -> Path:
    return Path.home() / ".sciim_toolkit" / "settings.json"


def user_config_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME_MACOS

    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_DIR_NAME_GENERIC

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / APP_DIR_NAME_GENERIC
    return Path.home() / ".config" / APP_DIR_NAME_GENERIC


def user_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME_MACOS

    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_DIR_NAME_GENERIC

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / APP_DIR_NAME_GENERIC
    return Path.home() / ".local" / "share" / APP_DIR_NAME_GENERIC


def autosave_drafts_dir() -> Path:
    return user_data_dir() / "autosave"


def user_settings_path() -> Path:
    return user_config_dir() / "settings.json"


def _read_settings_file(path: Path) -> UserSettings:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return UserSettings()
    return UserSettings.from_dict(data)


def load_user_settings(path: Path | None = None) -> UserSettings:
    settings_path = path or user_settings_path()
    legacy_path = _legacy_settings_path()

    if settings_path.exists():
        try:
            return _read_settings_file(settings_path)
        except Exception as exc:
            raise UserSettingsError(f"Failed to load user settings: {exc}") from exc

    if settings_path != legacy_path and legacy_path.exists():
        try:
            settings = _read_settings_file(legacy_path)
            save_user_settings(settings, settings_path)
            return settings
        except Exception as exc:
            raise UserSettingsError(f"Failed to migrate legacy settings: {exc}") from exc

    return UserSettings()


def save_user_settings(settings: UserSettings, path: Path | None = None) -> None:
    settings_path = path or user_settings_path()
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    except Exception as exc:
        raise UserSettingsError(f"Failed to save user settings: {exc}") from exc
