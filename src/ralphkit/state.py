import os
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

    def clean(self) -> None:
        for name in [
            "review-result.md",
            "review-feedback.md",
            "work-summary.md",
            "work-complete.md",
            "RALPH-BLOCKED.md",
        ]:
            (self.path / name).unlink(missing_ok=True)

    def read_task(self) -> str | None:
        return self._read("task.md")

    def write_task(self, content: str) -> None:
        (self.path / "task.md").write_text(content)

    def write_iteration(self, n: int) -> None:
        (self.path / "iteration.md").write_text(str(n))

    def _read(self, name: str, strip: bool = False) -> str | None:
        try:
            content = (self.path / name).read_text()
            return content.strip() if strip else content
        except FileNotFoundError:
            return None

    def read_review_result(self) -> str | None:
        return self._read("review-result.md", strip=True)

    def read_work_summary(self) -> str | None:
        return self._read("work-summary.md")

    def read_review_feedback(self) -> str | None:
        return self._read("review-feedback.md")

    def is_blocked(self) -> str | None:
        return self._read("RALPH-BLOCKED.md")

    def clean_for_next_iteration(self) -> None:
        for name in ["work-complete.md", "review-result.md", "work-summary.md"]:
            (self.path / name).unlink(missing_ok=True)
