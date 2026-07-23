from __future__ import annotations

import json
from pathlib import Path


class SettingsStore:
    """In-memory feature toggles, seeded from env-var defaults.

    When persist=False (e.g. ephemeral pod storage in k8s without a mounted
    volume), toggles made via the bot only last for the current process and
    revert to the env defaults on restart. When persist=True, toggles are
    written to `path` and reloaded on startup, overriding the env defaults.
    """

    def __init__(self, path: Path, persist: bool, defaults: dict[str, bool]) -> None:
        self._path = path
        self._persist = persist
        self._values = dict(defaults)
        if persist and path.exists():
            try:
                saved = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                saved = {}
            for key in self._values:
                if key in saved:
                    self._values[key] = bool(saved[key])

    def get(self, key: str) -> bool:
        return self._values[key]

    def set(self, key: str, value: bool) -> None:
        self._values[key] = value
        if self._persist:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._values))

    @property
    def persist(self) -> bool:
        return self._persist
