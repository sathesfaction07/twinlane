import json
import logging
from pathlib import Path

logger = logging.getLogger("batch_validator")


class Checkpoint:
    def __init__(self, checkpoint_dir: Path):
        self.path = checkpoint_dir / "progress.json"
        self.completed: set[str] = set()
        self.results: list[dict] = []
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        with open(self.path) as f:
            state = json.load(f)
        self.completed = set(state.get("completed", []))
        self.results = state.get("results", [])
        logger.info(f"Checkpoint: {len(self.completed)} already processed")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"completed": list(self.completed), "results": self.results}, f)

    def mark(self, item_id: str, result: dict):
        self.completed.add(item_id)
        self.results.append(result)
        if len(self.completed) % 25 == 0:
            self.save()

    def is_done(self, item_id: str) -> bool:
        return item_id in self.completed

    def remaining(self, items: list) -> list:
        return [i for i in items if i.id not in self.completed]
