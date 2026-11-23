from batch_validator.config import SelectorConfig
from batch_validator.core.router import ValidationItem
from batch_validator.scenarios.image_validator import ImageValidator
from batch_validator.scenarios.text_validator import TextValidator


class TestTextEvaluation:
    def setup_method(self):
        self.validator = TextValidator(SelectorConfig())

    def test_approved_passes(self):
        item = ValidationItem(id="1", scenario="text", attributes={})
        assert self.validator._evaluate(item, "Approved", "some note") == "PASS"

    def test_restricted_fails(self):
        item = ValidationItem(id="1", scenario="text", attributes={})
        assert self.validator._evaluate(item, "Restricted", "") == "FAIL"

    def test_conflict_detected(self):
        item = ValidationItem(id="1", scenario="text", attributes={})
        assert self.validator._evaluate(item, "Restricted", "Previously Approved") == "CONFLICT"

    def test_empty_status_skips(self):
        item = ValidationItem(id="1", scenario="text", attributes={})
        assert self.validator._evaluate(item, "", "") == "SKIP"

    def test_unknown_status_reviews(self):
        item = ValidationItem(id="1", scenario="text", attributes={})
        assert self.validator._evaluate(item, "Pending", "") == "REVIEW"


class TestImageEvaluation:
    def setup_method(self):
        self.validator = ImageValidator(SelectorConfig())

    def test_approved_with_image_passes(self):
        item = ValidationItem(id="1", scenario="image", attributes={})
        assert self.validator._evaluate(item, "Approved", True, "") == "PASS"

    def test_restricted_no_image_special_fail(self):
        item = ValidationItem(id="1", scenario="image", attributes={})
        assert self.validator._evaluate(item, "Restricted", False, "") == "FAIL_NO_IMAGE"

    def test_approved_no_image_needs_review(self):
        item = ValidationItem(id="1", scenario="image", attributes={})
        assert self.validator._evaluate(item, "Approved", False, "") == "REVIEW_MISSING_IMAGE"

    def test_restricted_with_image_fails(self):
        item = ValidationItem(id="1", scenario="image", attributes={})
        assert self.validator._evaluate(item, "Restricted", True, "") == "FAIL"

    def test_empty_status_skips(self):
        item = ValidationItem(id="1", scenario="image", attributes={})
        assert self.validator._evaluate(item, "", False, "") == "SKIP"
