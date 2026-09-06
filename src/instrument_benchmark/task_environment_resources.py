from __future__ import annotations

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TaskEnvironmentResources:
    candidate_root: Path
    evidence_root: Path
    transport_root: Path
    _identity: tuple[int, int]

    @classmethod
    def allocate(cls, run_root: Path) -> TaskEnvironmentResources:
        if os.getuid() == 0 or os.getgid() == 0:
            raise ValueError("task environment requires a non-root host UID/GID")
        roots = (run_root / "candidate", run_root / "task-evidence")
        for path in roots:
            path.mkdir(parents=True, exist_ok=False, mode=0o700)
        transport = Path(tempfile.mkdtemp(prefix="ib-", dir="/tmp")).resolve()
        identity = transport.stat()
        resources = cls(*roots, transport, (identity.st_dev, identity.st_ino))
        if len(str(transport / "task.sock").encode()) > 100:
            resources.close_transport()
            raise ValueError("task environment socket path exceeds 100 bytes")
        return resources

    def close_transport(self) -> None:
        try:
            current = self.transport_root.lstat()
        except FileNotFoundError:
            return
        if (
            not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != self._identity
        ):
            raise ValueError("task environment transport directory was replaced")
        # This exact mkdtemp directory belongs to this attempt, never to the user.
        shutil.rmtree(self.transport_root)
