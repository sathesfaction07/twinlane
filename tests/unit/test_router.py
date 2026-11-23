from batch_validator.core.router import classify_scenario, route_items


class TestClassifyScenario:
    def test_image_url_routes_to_image(self):
        assert classify_scenario({"id": "1", "image_url": "http://example.com/img.jpg"}) == "image"

    def test_photo_required_routes_to_image(self):
        assert classify_scenario({"id": "1", "photo_required": True}) == "image"

    def test_visual_check_routes_to_image(self):
        assert classify_scenario({"id": "1", "visual_check": True}) == "image"

    def test_media_category_routes_to_image(self):
        assert classify_scenario({"id": "1", "category": "media"}) == "image"

    def test_plain_item_routes_to_text(self):
        assert classify_scenario({"id": "1", "title": "Normal product"}) == "text"

    def test_empty_image_url_routes_to_text(self):
        assert classify_scenario({"id": "1", "image_url": ""}) == "text"


class TestRouteItems:
    def test_splits_correctly(self):
        items = [
            {"id": "1", "image_url": "http://img.jpg"},
            {"id": "2", "title": "text only"},
            {"id": "3", "photo_required": True},
            {"id": "4", "category": "electronics"},
        ]
        image, text = route_items(items)
        assert len(image) == 2
        assert len(text) == 2
        assert image[0].id == "1"
        assert image[1].id == "3"
        assert text[0].id == "2"
        assert text[1].id == "4"

    def test_empty_input(self):
        image, text = route_items([])
        assert image == []
        assert text == []

    def test_all_image(self):
        items = [{"id": str(i), "image_url": "x"} for i in range(5)]
        image, text = route_items(items)
        assert len(image) == 5
        assert len(text) == 0
