"""Dry-run selector validation and the CLI, without launching a browser.

validate_selectors runs its own logic for real (login check, per-selector status, skipped
and erroring selectors, the health summary) against a stand-in for Playwright. The CLI tests
check option handling and that each mode calls the right thing.
"""

import asyncio

import pytest
from click.testing import CliRunner

from batch_validator import cli
from batch_validator.config import PipelineConfig
from batch_validator.core import dryrun

SELECTORS = """\
login_url: "http://ui.test/login"
search_input: "#product-search"
search_button: "button.search"
result_table: "table.results"
status_cell: ""
image_container: ".images"
annotation_field: ".annotation"
"""


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    # PipelineConfig creates its output and checkpoint folders on construction.
    monkeypatch.chdir(tmp_path)


def make_config(tmp_path, selectors=SELECTORS):
    path = tmp_path / "selectors.yaml"
    path.write_text(selectors, encoding="utf-8")
    return PipelineConfig(input_path=tmp_path / "in.csv", output_path=tmp_path / "out",
                          selectors_path=path, checkpoint_dir=tmp_path / ".cp")


class Locator:
    def __init__(self, count):
        self._count = count

    async def count(self):
        if isinstance(self._count, Exception):
            raise self._count
        return self._count


class Page:
    def __init__(self, counts, goto_error=None):
        self.counts, self.goto_error, self.visited = counts, goto_error, []

    def set_default_timeout(self, ms):
        self.timeout = ms

    async def goto(self, url):
        if self.goto_error:
            raise self.goto_error
        self.visited.append(url)

    async def title(self):
        return "Login"

    def locator(self, selector):
        return Locator(self.counts.get(selector, 0))


class Browser:
    def __init__(self, page):
        self.page, self.closed = page, False

    async def new_page(self):
        return self.page

    async def close(self):
        self.closed = True


class Playwright:
    def __init__(self, browser):
        self.chromium = self
        self.browser = browser

    async def launch(self, headless):
        self.headless = headless
        return self.browser

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def run_dry(monkeypatch, config, page):
    browser = Browser(page)
    monkeypatch.setattr(dryrun, "async_playwright", lambda: Playwright(browser))
    return asyncio.run(dryrun.validate_selectors(config)), browser


class TestDryRun:
    def test_reports_each_selector_found_missing_skipped_or_erroring(self, monkeypatch,
                                                                       tmp_path):
        page = Page({"#product-search": 1, "button.search": 2, "table.results": 0,
                     ".images": RuntimeError("detached"), ".annotation": 3})
        results, browser = run_dry(monkeypatch, make_config(tmp_path), page)

        assert results["login_url"] == {"status": "ok", "title": "Login"}
        assert results["search_input"]["status"] == "found"
        assert results["search_button"]["count"] == 2
        assert results["result_table"]["status"] == "not_found"
        assert results["status_cell"] == {"status": "skipped", "reason": "not configured"}
        assert results["image_container"]["status"] == "error"
        assert "detached" in results["image_container"]["error"]
        assert page.visited == ["http://ui.test/login"]
        assert browser.closed

    def test_an_unreachable_login_page_stops_the_check(self, monkeypatch, tmp_path):
        page = Page({}, goto_error=ConnectionError("refused"))
        results, browser = run_dry(monkeypatch, make_config(tmp_path), page)
        assert results == {"login_url": {"status": "failed", "error": "refused"}}
        assert browser.closed

    def test_no_login_url_means_nothing_to_check(self, monkeypatch, tmp_path):
        config = make_config(tmp_path, selectors='search_input: "#x"\n')
        monkeypatch.setattr(dryrun, "async_playwright",
                            lambda: pytest.fail("must not launch a browser"))
        result = asyncio.run(dryrun.validate_selectors(config))
        assert "No login_url configured" in result["error"]


class TestCli:
    def write_inputs(self, tmp_path):
        (tmp_path / "in.csv").write_text("id,product_id,category\nBV-1,SKU-1,toys\n",
                                         encoding="utf-8")
        (tmp_path / "selectors.yaml").write_text(SELECTORS, encoding="utf-8")

    def test_dry_run_prints_each_check_and_never_starts_the_pipeline(self, monkeypatch,
                                                                       tmp_path):
        self.write_inputs(tmp_path)

        async def fake_validate(config):
            return {"login_url": {"status": "ok"}, "result_table": {"status": "not_found"}}

        monkeypatch.setattr(cli, "validate_selectors", fake_validate)
        monkeypatch.setattr(cli, "ValidationPipeline",
                            lambda config: pytest.fail("pipeline must not run"))
        result = CliRunner().invoke(cli.main, ["--input", "in.csv", "--selectors",
                                               "selectors.yaml", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "✓ login_url" in result.output
        assert "✗ result_table" in result.output

    def test_options_become_the_pipeline_config(self, monkeypatch, tmp_path):
        self.write_inputs(tmp_path)
        seen = {}

        class StandInPipeline:
            def __init__(self, config):
                seen["config"] = config

            async def run(self):
                seen["ran"] = True

        monkeypatch.setattr(cli, "ValidationPipeline", StandInPipeline)
        result = CliRunner().invoke(cli.main, [
            "--input", "in.csv", "--output", "results", "--selectors", "selectors.yaml",
            "--concurrent", "3", "--no-headless", "--retries", "4", "--vlm", "--excel",
        ])
        assert result.exit_code == 0, result.output
        config = seen["config"]
        assert seen["ran"]
        assert (config.max_concurrent, config.headless, config.retries) == (3, False, 4)
        assert config.vlm_fallback and config.excel
        assert config.selectors.search_input == "#product-search"
        assert (tmp_path / "results").is_dir()

    def test_input_is_required(self):
        result = CliRunner().invoke(cli.main, [])
        assert result.exit_code != 0
        assert "--input" in result.output
