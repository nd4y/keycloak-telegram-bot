from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


class SeenUsersStore:
    """Persists which Keycloak user IDs have already been notified about,
    so the polling loop only reports genuinely new registrations."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            data = json.loads(self._path.read_text())
        else:
            data = {"seen": [], "baseline_done": False}
        self._seen: set[str] = set(data.get("seen", []))
        self._baseline_done: bool = data.get("baseline_done", False)

    @property
    def baseline_done(self) -> bool:
        return self._baseline_done

    def seed_baseline(self, user_ids: Iterable[str]) -> None:
        self._seen.update(user_ids)
        self._baseline_done = True
        self._save()

    def is_new(self, user_id: str) -> bool:
        return user_id not in self._seen

    def mark_seen(self, user_id: str) -> None:
        self._seen.add(user_id)
        self._save()

    def _save(self) -> None:
        self._path.write_text(json.dumps({
            "seen": sorted(self._seen),
            "baseline_done": self._baseline_done,
        }))


class LoginPollState:
    """Tracks the timestamp (ms) of the most recently notified login event,
    so the polling loop only reports logins that happened after the last check."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            data = json.loads(self._path.read_text())
        else:
            data = {"last_time": 0}
        self._last_time: int = data.get("last_time", 0)

    @property
    def last_time(self) -> int:
        return self._last_time

    def advance(self, new_last_time: int) -> None:
        if new_last_time > self._last_time:
            self._last_time = new_last_time
            self._path.write_text(json.dumps({"last_time": self._last_time}))
