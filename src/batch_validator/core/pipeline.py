import asyncio
import csv
import json
import logging
import time

from playwright.async_api import async_playwright

from ..config import PipelineConfig
from ..scenarios.image_validator import ImageValidator
from ..scenarios.text_validator import TextValidator
from .checkpoint import Checkpoint
from .export import export_csv, export_excel, export_json
from .router import ValidationItem, route_items
from .vlm_fallback import VLMFallback

logger = logging.getLogger("batch_validator")


class ValidationPipeline:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.checkpoint = Checkpoint(config.checkpoint_dir)
        self.vlm = VLMFallback() if config.vlm_fallback else None
        self.text_validator = TextValidator(config.selectors, vlm=self.vlm)
        self.image_validator = ImageValidator(config.selectors, vlm=self.vlm)
        self.semaphore = asyncio.Semaphore(config.max_concurrent)

    async def run(self) -> None:
        start = time.time()
        raw_items = self._load_input()
        image_items, text_items = route_items(raw_items)

        image_remaining = self.checkpoint.remaining(image_items)
        text_remaining = self.checkpoint.remaining(text_items)
        total = len(image_remaining) + len(text_remaining)

        logger.info(
            f"Starting: {len(image_remaining)} image + {len(text_remaining)} text "
            f"({len(raw_items) - total} already checkpointed)"
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.config.headless)

            image_task = self._process_batch(browser, image_remaining, self.image_validator)
            text_task = self._process_batch(browser, text_remaining, self.text_validator)
            await asyncio.gather(image_task, text_task)

            await browser.close()

        self.checkpoint.save()
        self._write_output()

        elapsed = time.time() - start
        logger.info(
            f"Done in {elapsed:.1f}s — {total} items processed (vlm_fallback={'on' if self.vlm else 'off'})"
        )

    async def _process_batch(self, browser, items: list[ValidationItem], validator) -> None:
        tasks = [self._process_one(browser, item, validator) for item in items]
        await asyncio.gather(*tasks)

    async def _process_one(self, browser, item: ValidationItem, validator) -> None:
        async with self.semaphore:
            context = await browser.new_context()
            page = await context.new_page()
            page.set_default_timeout(self.config.timeout_ms)

            for attempt in range(self.config.retries + 1):
                try:
                    if self.config.selectors.login_url:
                        await page.goto(self.config.selectors.login_url)

                    result = await validator.validate(page, item)
                    self.checkpoint.mark(item.id, result)
                    break
                except Exception as e:
                    if attempt == self.config.retries:
                        logger.warning(
                            f"Failed after {self.config.retries + 1} attempts: {item.id} — {e}"
                        )
                        self.checkpoint.mark(
                            item.id,
                            {
                                "id": item.id,
                                "scenario": item.scenario,
                                "decision": "ERROR",
                                "error": str(e),
                            },
                        )
                    else:
                        logger.debug(f"Retry {attempt + 1} for {item.id}")
                        await asyncio.sleep(1)

            await context.close()

    def _load_input(self) -> list[dict]:
        path = self.config.input_path
        if path.suffix == ".json":
            with open(path, encoding="utf-8") as f:
                return json.load(f)

        items = []
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("id"):
                    items.append(dict(row))
        return items

    def _write_output(self) -> None:
        results = self.checkpoint.results
        export_json(results, self.config.output_path)
        export_csv(results, self.config.output_path)
        if self.config.excel:
            export_excel(results, self.config.output_path)
