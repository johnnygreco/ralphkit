from pathlib import Path


class StateDir:
    def __init__(self, path: str | Path = ".ralph"):
        self.path = Path(path)

    def setup(self) -> None:
        self.path.mkdir(exist_ok=True)

    def clean(self) -> None:
        for name in [
            "review-result.txt",
            "review-feedback.txt",
            "work-summary.txt",
            "work-complete.txt",
            "RALPH-BLOCKED.md",
        ]:
            (self.path / name).unlink(missing_ok=True)

    def write_task(self, content: str) -> None:
        (self.path / "task.md").write_text(content)

    def write_iteration(self, n: int) -> None:
        (self.path / "iteration.txt").write_text(str(n))

    def _read(self, name: str, strip: bool = False) -> str | None:
        try:
            content = (self.path / name).read_text()
            return content.strip() if strip else content
        except FileNotFoundError:
            return None

    def read_review_result(self) -> str | None:
        return self._read("review-result.txt", strip=True)

    def read_work_summary(self) -> str | None:
        return self._read("work-summary.txt")

    def read_review_feedback(self) -> str | None:
        return self._read("review-feedback.txt")

    def is_blocked(self) -> str | None:
        return self._read("RALPH-BLOCKED.md")

    def clean_for_next_iteration(self) -> None:
        for name in ["work-complete.txt", "review-result.txt", "work-summary.txt"]:
            (self.path / name).unlink(missing_ok=True)
