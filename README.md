# Twinlane

Validates product listings in bulk against a compliance platform using headless browser automation. The key architectural choice: items are split into two processing tracks (image-dependent and text-only) before any browser work begins, because image validation is 3x slower and irrelevant for most items.

---

## The Problem

Compliance teams need to validate hundreds of product listings daily against a web-based classification platform. Each validation requires navigating to the product, checking its status, reading annotation history, and — for some products — verifying that images exist and match. Manually, this takes 5-7 minutes per product. At 500 items per day, that's 40+ hours of repetitive clicking.

The wrinkle: not all products need the same checks. About 30-40% need image verification (products with photos, media categories, visual-check flags). The rest only need text/attribute validation. Running everything through the slower image path wastes thousands of seconds per batch.

---

## How It Works

**Step 1 — Route**

Before any browser touches anything, each item is classified into a scenario: `image` or `text`. The classification looks at three signals: does the item have an `image_url`? Is `photo_required` set? Is the category one that implies visual content (media, photography, visual_content)? If none of these match, it's text-only.

**Step 2 — Parallel processing with async browser contexts**

Both pools (image items and text items) are processed concurrently. Each item gets its own Playwright browser context (isolated cookies, no cross-contamination between items). A semaphore limits concurrency to 5 contexts at a time — enough to saturate the target platform's response time without overwhelming it.

**Step 3 — Scenario-specific validation**

The **text validator** navigates to the product, reads the status and annotation fields, and decides: PASS (approved), FAIL (restricted), CONFLICT (status says restricted but annotation says approved — suspicious), REVIEW (ambiguous status), or SKIP (no data).

The **image validator** does the same plus checks if images actually loaded in the container. This produces additional decisions: FAIL_NO_IMAGE (restricted and no images — common for fraudulent listings) and REVIEW_MISSING_IMAGE (approved but images didn't load — might be a temporary issue).

**Step 4 — Checkpoint and output**

Results are checkpointed every 25 items. On crash or interruption, re-running picks up where it left off. Final output is a JSON file with per-item results and a summary (counts of PASS/FAIL/REVIEW/ERROR).

---

## Architecture

```
CSV Input
    │
    ▼
┌─────────────────────────────┐
│         Router               │
│  classify_scenario(item)     │
│  "image" or "text"           │
└─────────┬───────────┬───────┘
          │           │
          ▼           ▼
┌─────────────┐ ┌─────────────┐
│ Image Pool  │ │  Text Pool  │       Both pools processed
│ (30-40%)    │ │  (60-70%)   │       via asyncio.gather()
└──────┬──────┘ └──────┬──────┘
       │               │
       ▼               ▼
┌─────────────────────────────┐
│  Playwright Browser Contexts │
│  (max 5 concurrent)          │
│  Semaphore-controlled        │
└─────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  Checkpoint (every 25 items) │
└─────────────────────────────┘
       │
       ▼
  results.json + summary
```

---

## Project Structure

```
twinlane/
├── src/batch_validator/
│   ├── cli.py                  Click entry point
│   ├── config.py               Pipeline + selector config (YAML-driven)
│   ├── core/
│   │   ├── router.py           Scenario classification (image vs text)
│   │   ├── checkpoint.py       Save/resume state across crashes
│   │   └── pipeline.py         Orchestrator (browser launch, gather, output)
│   └── scenarios/
│       ├── text_validator.py   Navigate + read status + decide
│       └── image_validator.py  Navigate + read status + check images + decide
├── config/selectors.yaml       All CSS selectors externalized
├── tests/unit/                 Router, checkpoint, and decision logic tests
├── data/sample_input.csv       Demo dataset
├── docs/adr/                   Dual-scenario decision record
└── pyproject.toml
```

---

## Running

```bash
pip install -e ".[dev]"
playwright install chromium

# Standard run
twinlane --input data/sample_input.csv --output results/

# With VLM fallback (screenshots ambiguous elements → asks Claude to read them)
twinlane --input data/sample_input.csv --output results/ --vlm

# Generate Excel with color-coded decisions
twinlane --input data/sample_input.csv --output results/ --excel

# Validate selectors are still working (no items processed)
twinlane --input data/sample_input.csv --output results/ --dry-run
```

Options:
```
--concurrent 5              Max parallel browser contexts
--headless/--no-headless    Show browser window for debugging
--retries 2                 Retry count on failure
--vlm/--no-vlm              VLM fallback for ambiguous text extraction
--excel/--no-excel          Export results.xlsx with colored decision column
--dry-run                   Check selector health without processing items
--selectors config/selectors.yaml
```

---

## Output Formats

Every run produces:
- `results.json` — full results with summary counts
- `results.csv` — flat CSV for spreadsheet use

With `--excel`:
- `results.xlsx` — color-coded decisions (green=PASS, red=FAIL, amber=REVIEW), auto-sized columns

---

## Testing

```bash
pytest tests/ -v            # 27 tests
pytest tests/ --cov=src     # coverage
```

Tests cover routing logic, checkpoint persistence, decision evaluation for both validators, and export formatting (JSON/CSV/Excel).

---

## Selector Configuration

All CSS selectors live in `config/selectors.yaml`:

```yaml
search_input: "#product-search"
search_button: "button[data-action='search']"
result_table: "table.results"
status_cell: "td.status"
image_container: ".product-images"
annotation_field: ".annotation-text"
```

When the target platform's UI changes, you update the YAML — not the Python code. This is a deliberate separation: the selectors are volatile (any frontend deploy can change them), the validation logic is stable.

---

## Tradeoffs and Decisions I Made Along the Way

**The dual-scenario split happens before browser launch, not during**

I initially had a single validator that checked for images mid-validation — load the page, check if image container exists, branch accordingly. The problem: by the time you know the item doesn't need image checks, you've already waited for the image container to time out (5 seconds of wasted wait on a `wait_for` that's never going to resolve). Routing at the input layer means text items never even look for image containers. On a 1000-item batch with 70% text items, this saves ~3500 seconds.

**Semaphore at 5, not 10 or 20**

Each browser context consumes ~100MB of RAM and holds an open connection to the target platform. At 5 concurrent, that's 500MB — comfortable on an 8GB machine. At 10, you're at 1GB and starting to compete with the OS. More importantly, the target platform starts returning slower responses above 5 concurrent sessions from the same IP. I found 5 by observing response times: below 5 they're stable at ~2s, above 5 they creep toward 5-8s as the platform rate-limits. The semaphore is the cheapest possible rate limiter.

**YAML selector config instead of constants in code**

The original version had selectors hardcoded. Every time the platform deployed a UI update (roughly monthly), I had to change the Python code, run tests, and redeploy. Moving selectors to YAML means an operations person can update them without touching Python. The config loads at startup — no hot-reload during a run, which would be dangerous (changing selectors mid-batch could produce inconsistent results).

**Checkpoint every 25 items, not per-item or per-batch**

Per-item: too much disk I/O. At 5 concurrent items completing every ~3 seconds, that's a JSON write every 600ms. The file grows with every result, and serializing a 500-item results list takes measurable time. Per-batch: risky — if you're processing 200 items and crash at item 150, you lose all 150 results. Every 25 is the sweet spot: at most you lose 25 items of work (~75 seconds at 3s/item), and the writes happen every ~15 seconds — invisible overhead.

**CONFLICT as a distinct decision (not just FAIL)**

A product that shows "Restricted" in status but "Approved" in annotation history is more interesting than a simple restriction — it suggests either a data inconsistency or a reversal that happened between the status snapshot and the annotation write. Flagging these separately (instead of just FAIL) means an investigator can filter for conflicts specifically, which are often the highest-value findings in a batch run.

**VLM fallback for when text extraction fails**

Playwright's `text_content()` returns whatever the DOM says the text is. Usually that's correct. But sometimes the status is rendered via CSS pseudo-elements, or it's an SVG badge, or the DOM text is a machine-readable code while the visible text is different. When the extracted text doesn't match any known status pattern, the VLM fallback screenshots the element and asks Claude to read what's visually displayed. This costs ~$0.003 per screenshot and adds ~2 seconds — so it only fires when normal extraction produces something unexpected. On a typical 500-item batch, it might fire 5-10 times.

**Dry-run mode for selector health**

The target platform deploys UI updates roughly monthly. When selectors break, you find out by getting 100% ERROR results on a real batch — wasting 10 minutes of processing time. Dry-run opens the page, checks each selector once, and reports which ones are healthy. Takes 5 seconds. I run it before every batch as a sanity check. If a selector is broken, I update the YAML and dry-run again — no wasted processing.

**Excel output with color-coded decisions**

JSON is for programmatic consumption. CSV is for quick filtering. But the people who review batch results live in Excel and want to visually scan for red (FAIL) rows. The Excel export uses openpyxl to set font colors per decision — PASS in teal, FAIL/ERROR in red, REVIEW/CONFLICT in amber. It's a small touch but it means reviewers don't need to add conditional formatting every time they open the file.

---

## Stack

Python 3.11, Playwright (async), Click, PyYAML, openpyxl, boto3 (for VLM fallback), pytest.
