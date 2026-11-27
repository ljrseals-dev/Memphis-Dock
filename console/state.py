from __future__ import annotations

import threading

from dockcore.models import DockState, Mode, PlanJob


class Store:
    def __init__(self) -> None:
        self.state = DockState()
        self.jobs: dict[str, PlanJob] = {}
        self.mode: Mode = Mode.SUPERVISED
        self.lock = threading.RLock()


STORE = Store()
