from __future__ import annotations

import json
from pathlib import Path

from sciim_toolkit.models.project import ProjectSession


class SessionIOError(Exception):
    pass


def save_session(path: Path, session: ProjectSession, update_project_file: bool = True) -> None:
    try:
        session.touch()
        if update_project_file:
            session.project_file = str(path)
        payload = session.to_dict()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:
        raise SessionIOError(f"Failed to save session: {exc}") from exc


def load_session(path: Path) -> ProjectSession:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        session = ProjectSession.from_dict(data)
        session.project_file = str(path)
        return session
    except Exception as exc:
        raise SessionIOError(f"Failed to load session: {exc}") from exc
