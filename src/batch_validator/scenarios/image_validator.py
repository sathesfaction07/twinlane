import logging

from playwright.async_api import Page

from ..config import SelectorConfig
from ..core.router import ValidationItem
from ..core.vlm_fallback import VLMFallback

logger = logging.getLogger("batch_validator")

KNOWN_STATUSES = {"approved", "restricted", "pending", "active", "inactive", "under review"}


class ImageValidator:
    def __init__(self, selectors: SelectorConfig, vlm: VLMFallback | None = None):
        self.selectors = selectors
        self.vlm = vlm

    async def validate(self, page: Page, item: ValidationItem) -> dict:
        product_id = item.attributes.get("product_id", item.id)

        await page.locator(self.selectors.search_input).fill(product_id)
        await page.locator(self.selectors.search_button).click()
        await page.locator(self.selectors.result_table).wait_for(timeout=15000)

        status = await self._read_status(page)
        has_images = await self._check_images(page)
        annotation = await page.locator(self.selectors.annotation_field).first.text_content()

        decision = self._evaluate(item, status, has_images, annotation)

        return {
            "id": item.id,
            "scenario": "image",
            "product_id": product_id,
            "status": status.strip() if status else "",
            "has_images": has_images,
            "annotation": annotation.strip() if annotation else "",
            "decision": decision,
        }

    async def _read_status(self, page: Page) -> str:
        locator = page.locator(self.selectors.status_cell).first
        text = await locator.text_content()

        if text and text.strip().lower() in KNOWN_STATUSES:
            return text.strip()

        if self.vlm and (not text or text.strip().lower() not in KNOWN_STATUSES):
            logger.info("Status text unclear, using VLM fallback")
            vlm_text = await self.vlm.read_element(page, locator, context="product status field")
            if vlm_text:
                return vlm_text

        return text.strip() if text else ""

    async def _check_images(self, page: Page) -> bool:
        container = page.locator(self.selectors.image_container)
        try:
            await container.wait_for(timeout=5000)
            images = await container.locator("img").count()
            return images > 0
        except Exception:
            return False

    def _evaluate(
        self, item: ValidationItem, status: str | None, has_images: bool, annotation: str | None
    ) -> str:
        if not status:
            return "SKIP"

        status_lower = (status or "").lower()

        if "restricted" in status_lower and not has_images:
            return "FAIL_NO_IMAGE"
        if "approved" in status_lower and not has_images:
            return "REVIEW_MISSING_IMAGE"
        if "restricted" in status_lower and has_images:
            return "FAIL"
        if "approved" in status_lower and has_images:
            return "PASS"
        return "REVIEW"
