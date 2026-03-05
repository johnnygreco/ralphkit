from pathlib import Path

from ralphkit.config import STATE_DIR


class StateDir:
    def __init__(self, path: str | Path = STATE_DIR):
        self.path = Path(path)

    def setup(self) -> None:
        self.path.mkdir(exist_ok=True)

    def clean(self) -> None:
        for name in [
            "review-result.md",
            "review-feedback.md",
            "work-summary.md",
            "work-complete.md",
            "RALPH-BLOCKED.md",
        ]:
            (self.path / name).unlink(missing_ok=True)

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
