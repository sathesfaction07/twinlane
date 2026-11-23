import logging

from playwright.async_api import async_playwright

from ..config import PipelineConfig

logger = logging.getLogger("batch_validator")


async def validate_selectors(config: PipelineConfig) -> dict:
    results = {}
    selectors = config.selectors

    if not selectors.login_url:
        return {"error": "No login_url configured. Set it in selectors.yaml to run dry-run."}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.headless)
        page = await browser.new_page()
        page.set_default_timeout(10000)

        try:
            await page.goto(selectors.login_url)
            results["login_url"] = {"status": "ok", "title": await page.title()}
        except Exception as e:
            results["login_url"] = {"status": "failed", "error": str(e)}
            await browser.close()
            return results

        checks = {
            "search_input": selectors.search_input,
            "search_button": selectors.search_button,
            "result_table": selectors.result_table,
            "status_cell": selectors.status_cell,
            "image_container": selectors.image_container,
            "annotation_field": selectors.annotation_field,
        }

        for name, selector in checks.items():
            if not selector:
                results[name] = {"status": "skipped", "reason": "not configured"}
                continue
            try:
                locator = page.locator(selector)
                count = await locator.count()
                results[name] = {
                    "status": "found" if count > 0 else "not_found",
                    "selector": selector,
                    "count": count,
                }
            except Exception as e:
                results[name] = {"status": "error", "selector": selector, "error": str(e)}

        await browser.close()

    healthy = sum(1 for r in results.values() if r.get("status") in ("ok", "found"))
    total = len(results)
    logger.info(f"Dry-run: {healthy}/{total} selectors healthy")
    return results
