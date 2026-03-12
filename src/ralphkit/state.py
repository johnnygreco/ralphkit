import json
import os
import shutil
from pathlib import Path

from ralphkit.config import STATE_DIR


class StateDir:
    def __init__(self, path: str | Path = STATE_DIR):
        self.root = Path(path)
        self.path = self.root  # default; overridden by setup()
        self.resumed = False

    @property
    def _runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def _current_link(self) -> Path:
        return self.root / "current"

    @property
    def active_path(self) -> Path:
        """Path that prompt templates should use (the real run directory)."""
        return self.path

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

    def _resolve_resume_target(self, resume_run: str | Path) -> Path:
        candidate = Path(resume_run).expanduser()
        if candidate.is_absolute():
            if candidate.is_dir():
                return candidate.resolve()
        elif len(candidate.parts) > 1 or str(resume_run).startswith("."):
            relative_candidate = (Path.cwd() / candidate).resolve()
            if relative_candidate.is_dir():
                return relative_candidate
        if str(resume_run).isdigit():
            run_dir = self._runs_dir / f"{int(str(resume_run)):03d}"
            if run_dir.is_dir():
                return run_dir.resolve()
        run_dir = self._runs_dir / str(resume_run)
        if run_dir.is_dir():
            return run_dir.resolve()
        raise FileNotFoundError(f"Run directory not found: {resume_run}")

    def setup(self, resume_run: str | Path | None = None) -> None:
        self.root.mkdir(exist_ok=True)
        self._runs_dir.mkdir(exist_ok=True)
        if resume_run is None:
            self.resumed = False
            self.path = self._create_new_run()
        else:
            self.resumed = True
            self.path = self._resolve_resume_target(resume_run)
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

    def write_json(self, name: str, data: dict) -> None:
        (self.path / name).write_text(json.dumps(data, indent=2) + "\n")

    def artifact_path(
        self,
        step_name: str,
        phase: str,
        iteration: int | None = None,
        *,
        suffix: str = "json",
    ) -> Path:
        parts = [phase]
        if iteration is not None:
            parts.append(str(iteration))
        parts.append(step_name)
        slug = "__".join(parts).replace("/", "_")
        return self.path / f"{slug}.{suffix}"

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

    def write_resume_marker(self, source: str) -> None:
        self.write_json(
            "resume.json",
            {
                "source": source,
            },
        )
