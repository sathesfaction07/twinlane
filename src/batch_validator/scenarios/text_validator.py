import logging

from playwright.async_api import Page

from ..config import SelectorConfig
from ..core.router import ValidationItem
from ..core.vlm_fallback import VLMFallback

logger = logging.getLogger("batch_validator")

KNOWN_STATUSES = {"approved", "restricted", "pending", "active", "inactive", "under review"}


class TextValidator:
    def __init__(self, selectors: SelectorConfig, vlm: VLMFallback | None = None):
        self.selectors = selectors
        self.vlm = vlm

    async def validate(self, page: Page, item: ValidationItem) -> dict:
        product_id = item.attributes.get("product_id", item.id)

        await page.locator(self.selectors.search_input).fill(product_id)
        await page.locator(self.selectors.search_button).click()
        await page.locator(self.selectors.result_table).wait_for(timeout=15000)

        status = await self._read_status(page)
        annotation = await page.locator(self.selectors.annotation_field).first.text_content()

        decision = self._evaluate(item, status, annotation)

        return {
            "id": item.id,
            "scenario": "text",
            "product_id": product_id,
            "status": status.strip() if status else "",
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

    def _evaluate(self, item: ValidationItem, status: str | None, annotation: str | None) -> str:
        if not status:
            return "SKIP"

        status_lower = (status or "").lower()
        if "restricted" in status_lower and "approved" in (annotation or "").lower():
            return "CONFLICT"
        if "approved" in status_lower:
            return "PASS"
        if "restricted" in status_lower:
            return "FAIL"
        return "REVIEW"
