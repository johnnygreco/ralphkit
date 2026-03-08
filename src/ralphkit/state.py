import json
import os
import shutil
from pathlib import Path

from ralphkit.config import STATE_DIR


class StateDir:
    def __init__(self, path: str | Path = STATE_DIR):
        self.root = Path(path)
        self.path = self.root  # default; overridden by setup()

    @property
    def _runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def _current_link(self) -> Path:
        return self.root / "current"

    @property
    def active_path(self) -> Path:
        """Path that prompt templates should use (the 'current' symlink)."""
        return self._current_link

    def _numeric_run_dirs(self) -> list[Path]:
        """Return all numbered run directories in sorted order."""
        if not self._runs_dir.is_dir():
            return []
        dirs = []
        for entry in self._runs_dir.iterdir():
            if entry.is_dir():
                try:
                    int(entry.name)
                    dirs.append(entry)
                except ValueError:
                    pass
        dirs.sort()
        return dirs

    def _next_run_number(self) -> int:
        dirs = self._numeric_run_dirs()
        if not dirs:
            return 1
        return int(dirs[-1].name) + 1

    def _create_new_run(self) -> Path:
        num = self._next_run_number()
        run_dir = self._runs_dir / f"{num:03d}"
        run_dir.mkdir(parents=True)
        return run_dir

    def _update_current_link(self) -> None:
        link = self._current_link
        # Use relative target so the symlink works if the tree is moved
        target = Path("runs") / self.path.name
        try:
            link.unlink()
        except FileNotFoundError:
            pass
        os.symlink(target, link)

    def list_runs(self) -> list[Path]:
        """Return all numbered run directories in order."""
        return self._numeric_run_dirs()

    def setup(self) -> None:
        self.root.mkdir(exist_ok=True)
        self._runs_dir.mkdir(exist_ok=True)
        self.path = self._create_new_run()
        self._update_current_link()

    def read_task(self) -> str | None:
        return self._read("task.md")

    def write_task(self, content: str) -> None:
        (self.path / "task.md").write_text(content)

    def write_iteration(self, n: int) -> None:
        (self.path / "iteration.txt").write_text(str(n))

    def _read(self, name: str) -> str | None:
        try:
            return (self.path / name).read_text()
        except FileNotFoundError:
            return None

    def is_blocked(self) -> str | None:
        return self._read("RALPH-BLOCKED.md")

    def clean_for_next_iteration(self) -> None:
        for name in ["RALPH-BLOCKED.md"]:
            (self.path / name).unlink(missing_ok=True)

    # ── Plan management ───────────────────────────────────────────

    def read_plan(self) -> dict | None:
        """Read and parse tickets.json. Returns None if missing or invalid JSON."""
        raw = self._read("tickets.json")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def write_plan(self, data: dict) -> None:
        """Write dict as JSON to tickets.json."""
        (self.path / "tickets.json").write_text(json.dumps(data, indent=2) + "\n")

    def copy_plan(self, source: Path) -> None:
        """Copy an external file into the state dir as tickets.json."""
        shutil.copy2(source, self.path / "tickets.json")
