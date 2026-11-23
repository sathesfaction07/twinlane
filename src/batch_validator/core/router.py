import logging
from dataclasses import dataclass

logger = logging.getLogger("batch_validator")


@dataclass
class ValidationItem:
    id: str
    scenario: str  # "image" or "text"
    attributes: dict
    status: str = "pending"
    result: dict | None = None


IMAGE_INDICATORS = ["image_url", "photo_required", "visual_check"]


def route_items(items: list[dict]) -> tuple[list[ValidationItem], list[ValidationItem]]:
    image_items = []
    text_items = []

    for item in items:
        scenario = classify_scenario(item)
        vi = ValidationItem(
            id=item.get("id", ""),
            scenario=scenario,
            attributes=item,
        )
        if scenario == "image":
            image_items.append(vi)
        else:
            text_items.append(vi)

    logger.info(f"Routed {len(items)} items: {len(image_items)} image, {len(text_items)} text")
    return image_items, text_items


def classify_scenario(item: dict) -> str:
    for indicator in IMAGE_INDICATORS:
        if item.get(indicator):
            return "image"

    if item.get("category", "").lower() in ("media", "visual_content", "photography"):
        return "image"

    return "text"
