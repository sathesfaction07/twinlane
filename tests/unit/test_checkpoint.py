from batch_validator.core.checkpoint import Checkpoint
from batch_validator.core.router import ValidationItem


class TestCheckpoint:
    def test_fresh_start(self, tmp_path):
        cp = Checkpoint(tmp_path)
        assert len(cp.completed) == 0

    def test_mark_and_check(self, tmp_path):
        cp = Checkpoint(tmp_path)
        cp.mark("item-1", {"id": "item-1", "decision": "PASS"})
        assert cp.is_done("item-1")
        assert not cp.is_done("item-2")

    def test_save_and_reload(self, tmp_path):
        cp = Checkpoint(tmp_path)
        cp.mark("a", {"id": "a", "decision": "PASS"})
        cp.mark("b", {"id": "b", "decision": "FAIL"})
        cp.save()

        cp2 = Checkpoint(tmp_path)
        assert cp2.is_done("a")
        assert cp2.is_done("b")
        assert len(cp2.results) == 2

    def test_remaining_filters(self, tmp_path):
        cp = Checkpoint(tmp_path)
        cp.mark("a", {"id": "a"})

        items = [
            ValidationItem(id="a", scenario="text", attributes={}),
            ValidationItem(id="b", scenario="text", attributes={}),
            ValidationItem(id="c", scenario="image", attributes={}),
        ]
        remaining = cp.remaining(items)
        assert len(remaining) == 2
        assert all(i.id != "a" for i in remaining)
