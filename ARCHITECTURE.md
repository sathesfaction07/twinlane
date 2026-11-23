# BatchValidator — Technical Architecture

## Overview

BatchValidator is a headless browser automation tool that validates product listings in bulk against a compliance platform. It splits items into parallel processing tracks (image-dependent and text-only) before launching browsers, runs validation via Playwright async contexts with semaphore-controlled concurrency, and checkpoints progress incrementally so crashes lose at most 25 items of work. Results are exported to JSON, CSV, and optionally color-coded Excel.

**Design principle:** Failure isolation. One bad record must never abort the batch. Every item is wrapped in retry + exception handling so a malformed product ID or platform timeout produces ERROR, not a stack trace that kills 500 remaining items.

---

## System Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                           CLI (batch-validator)                         │
│  Args: --input, --output, --concurrent, --vlm, --excel, --dry-run      │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         DRY-RUN GATE (Optional)                         │
│  Validate selectors against live UI without processing items            │
│  Checks: login_url, search_input, status_cell, image_container, etc    │
│  Returns: {selector_name: {status: ok|not_found|error, count: N}}      │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │ if not dry-run
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        PIPELINE ORCHESTRATOR                            │
│  1. Load input (CSV or JSON)                                            │
│  2. Route items to scenarios                                            │
│  3. Filter via checkpoint (skip already-processed)                      │
│  4. Launch Playwright browser                                           │
│  5. Gather (image_task, text_task) in parallel                          │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       ROUTER (classify_scenario)                        │
│  Classify each item as "image" or "text":                               │
│   - image: item has image_url, photo_required, or visual_check flag    │
│   - image: category is "media", "visual_content", or "photography"     │
│   - text: none of the above                                             │
│  Returns: (image_items, text_items)                                     │
└────────────────┬──────────────────────────────────┬────────────────────┘
                 │                                   │
                 ▼                                   ▼
┌──────────────────────────────┐  ┌──────────────────────────────────────┐
│   IMAGE POOL                  │  │   TEXT POOL                          │
│   ImageValidator              │  │   TextValidator                      │
│   - Navigate to product       │  │   - Navigate to product              │
│   - Read status + annotation  │  │   - Read status + annotation         │
│   - Check image container     │  │   - Decide: PASS/FAIL/CONFLICT/      │
│   - Decide: PASS / FAIL /     │  │     REVIEW/SKIP                      │
│     FAIL_NO_IMAGE /           │  │                                      │
│     REVIEW_MISSING_IMAGE      │  └──────────────┬───────────────────────┘
│                               │                 │
└──────────────┬────────────────┘                 │
               │ Both pools processed via         │
               │ asyncio.gather() concurrently    │
               └──────────────┬───────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────────┐
│             BROWSER CONTEXTS (Semaphore: max 5 concurrent)              │
│  Each item gets isolated context → no cookie cross-contamination        │
│  Retries: 2 + 1 (3 attempts total) with 1s backoff                      │
│  Timeout: 30s per page operation                                        │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼ optional VLM fallback
┌────────────────────────────────────────────────────────────────────────┐
│                   VLM FALLBACK (if --vlm enabled)                       │
│  Fires when status text is ambiguous or extraction fails                │
│  Screenshots element → AWS Bedrock Claude Sonnet → returns text         │
│  Model: us.anthropic.claude-sonnet-4-6-20250514-v1:0                    │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     CHECKPOINT (.checkpoints/progress.json)             │
│  Read at startup: {"completed": ["id1", "id2"], "results": [...]}      │
│  Write every 25 items (incremental save)                                │
│  Resume: filter remaining(items) = [i for i in items if not is_done(i)]│
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    EXPORT (JSON + CSV + Excel)                          │
│  JSON: {summary: {total, pass, fail, review, error}, results: [...]}   │
│  CSV: flat file (id, product_id, scenario, status, decision, ...)      │
│  Excel (optional): color-coded decision column (PASS=teal, FAIL=red)    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. CLI (`src/batch_validator/cli.py`)

Entry point: `batch-validator` console command. Built with Click.

| Flag | Type | Default | Purpose |
|:--|:--|:--|:--|
| `--input` | Path | required | CSV or JSON input file |
| `--output` | Path | `output/` | Output directory for results |
| `--selectors` | Path | `config/selectors.yaml` | CSS selector configuration |
| `--concurrent` | int | 5 | Max parallel browser contexts |
| `--headless` / `--no-headless` | bool | `True` | Show browser for debugging |
| `--retries` | int | 2 | Retry count per item (3 total attempts) |
| `--vlm` / `--no-vlm` | bool | `False` | Enable Claude Vision fallback |
| `--excel` / `--no-excel` | bool | `False` | Generate color-coded Excel output |
| `--dry-run` | flag | `False` | Validate selectors without processing items |

If `--dry-run` is set, the CLI runs `validate_selectors()` and exits. Otherwise, it constructs `PipelineConfig` and launches `ValidationPipeline.run()`.

### 2. Core (`src/batch_validator/core/`)

**pipeline.py — ValidationPipeline**

Orchestrator. Loads input, routes items, launches Playwright browser, processes both pools concurrently via `asyncio.gather()`, closes browser, writes output.

```python
async def run(self) -> None:
    raw_items = self._load_input()
    image_items, text_items = route_items(raw_items)
    image_remaining = self.checkpoint.remaining(image_items)
    text_remaining = self.checkpoint.remaining(text_items)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=self.config.headless)
        image_task = self._process_batch(browser, image_remaining, self.image_validator)
        text_task = self._process_batch(browser, text_remaining, self.text_validator)
        await asyncio.gather(image_task, text_task)
        await browser.close()

    self.checkpoint.save()
    self._write_output()
```

Each item is processed via `_process_one()`: acquire semaphore, new browser context, retry loop (3 attempts), call validator, mark checkpoint, close context. Exceptions are caught at the retry boundary — after exhausting retries, the result is marked as ERROR with the exception message.

**router.py — Scenario classification**

`classify_scenario(item: dict) -> str` returns `"image"` or `"text"`. Checks three signals: (1) item has `image_url`, `photo_required`, or `visual_check` attribute; (2) category is `"media"`, `"visual_content"`, or `"photography"`. If none match, returns `"text"`.

`route_items(items)` returns `(image_items, text_items)` as lists of `ValidationItem` dataclass instances.

**checkpoint.py — Checkpoint**

Incremental progress persistence. Stores `{"completed": ["id1", "id2", ...], "results": [{...}, ...]}` in `.checkpoints/progress.json`. Loads at startup, writes after every 25 items via `mark(item_id, result)`. Resume logic: `remaining(items) = [i for i in items if i.id not in self.completed]`.

**dryrun.py — validate_selectors()**

Opens the `login_url`, attempts to locate each configured selector (search_input, search_button, result_table, status_cell, image_container, annotation_field). Returns a dict mapping selector names to `{status: ok|found|not_found|error, selector: "...", count: N}`. Used to verify selector health before processing.

**export.py — Output formatters**

- `export_json()`: writes `results.json` with summary + results list
- `export_csv()`: writes `results.csv` with flat schema (id, product_id, scenario, status, decision, annotation, has_images, error)
- `export_excel()`: writes `results.xlsx` with openpyxl, applies font colors per decision (PASS=00d4aa, FAIL=ef4444, REVIEW/CONFLICT=f59e0b, ERROR=ef4444, SKIP=6b7280), auto-sizes columns

**vlm_fallback.py — VLMFallback**

Boto3 Bedrock client wrapper. When text extraction returns empty or unrecognized status, screenshots the element (or full page fallback), base64-encodes, sends to Claude Sonnet with prompt "Read the text content visible in this screenshot. Return ONLY the text you can see." Temperature 0, max_tokens 200. Returns extracted text or None on failure.

### 3. Scenario Validators (`src/batch_validator/scenarios/`)

| Scenario | Input Signals | Checks | Decisions | Failure Modes |
|:--|:--|:--|:--|:--|
| **text** | No image indicators, non-visual category | Navigate, read status + annotation | PASS (approved), FAIL (restricted), CONFLICT (restricted status + approved annotation), REVIEW (ambiguous), SKIP (empty status) | Network timeout, selector mismatch → ERROR |
| **image** | `image_url`, `photo_required`, visual_check flag, or category in (media, photography, visual_content) | Navigate, read status + annotation, check image container | PASS (approved + images), FAIL (restricted + images), FAIL_NO_IMAGE (restricted + no images), REVIEW_MISSING_IMAGE (approved + no images), REVIEW (ambiguous), SKIP (empty status) | Network timeout, selector mismatch, image container timeout → ERROR |

Both validators inherit similar structure: `validate(page, item)` → navigate, read status (with optional VLM fallback), read annotation, evaluate decision logic, return result dict.

**TextValidator._evaluate()** logic:
- Empty status → SKIP
- "restricted" in status AND "approved" in annotation → CONFLICT
- "approved" in status → PASS
- "restricted" in status → FAIL
- Else → REVIEW

**ImageValidator._evaluate()** logic:
- Empty status → SKIP
- "restricted" + no images → FAIL_NO_IMAGE
- "approved" + no images → REVIEW_MISSING_IMAGE
- "restricted" + has images → FAIL
- "approved" + has images → PASS
- Else → REVIEW

VLM fallback fires in `_read_status()` when `text_content()` returns empty or a string not in `KNOWN_STATUSES` (`{"approved", "restricted", "pending", "active", "inactive", "under review"}`).

---

## Data Flow

```
1. User runs: batch-validator --input data/batch.csv --output results/ --vlm --excel
2. CLI constructs PipelineConfig, loads SelectorConfig from config/selectors.yaml
3. Pipeline loads input CSV → 500 items
4. Router classifies: 180 image, 320 text
5. Checkpoint reads .checkpoints/progress.json → 50 already completed
6. Remaining: 150 image + 300 text = 450 items
7. Pipeline launches Chromium browser (headless)
8. Two parallel tasks start: image_task (150 items), text_task (300 items)
9. Semaphore limits 5 concurrent contexts across both tasks
10. Each item: new context → navigate → extract status (VLM fallback if unclear) → read annotation → check images (if image scenario) → evaluate decision → checkpoint.mark(id, result)
11. After item #25 completes, checkpoint saves to disk (first incremental save)
12. [Crash occurs at item #122]
13. User re-runs same command
14. Checkpoint reads 121 completed items → 329 remaining
15. Resume: 59 image + 270 text
16. Processing continues from item #122
17. All 450 items complete (original 500 - 50 already done)
18. Checkpoint final save
19. Export: results.json + results.csv + results.xlsx (color-coded)
20. CLI logs: "Done in 247.3s — 450 items processed (vlm_fallback=on)"
```

---

## Failure Isolation and Resume Design

**Core guarantee:** A batch of 1000 items never dies because item 37 has a malformed product ID or item 459 triggers a platform timeout. Every item is isolated.

### Isolation Mechanism

Each item is processed in its own `try/except` block inside `_process_one()` with a retry loop. After 3 attempts, the exception is caught and the result is recorded as `{"decision": "ERROR", "error": str(e)}`. The outer `asyncio.gather()` continues — one ERROR does not cancel sibling tasks. This costs context switches (each item is a coroutine) but buys resilience.

**Honest cost:** A misconfigured selector looks identical to bad input data. If `selectors.yaml` points to `.old-status-cell` but the platform now uses `.status-badge`, every item will ERROR with "locator timeout." The system cannot distinguish "this product has no status field" from "I'm looking for the wrong CSS selector." This is why dry-run exists — it checks the selectors once, up front, instead of letting you discover the problem after the whole batch has already run.

### Checkpoint Strategy

The checkpoint file (`.checkpoints/progress.json`) is written **incrementally**, not at the end. Every 25 items, the current state is serialized to disk. Why 25?

- **Per-item** (every result): too much I/O for no benefit. The `results` array is re-serialized on every write, so cost grows with the size of the batch already completed.
- **Per-batch** (after all items): a crash near the end throws away everything. On a long batch that is the difference between losing a minute and losing the whole run.
- **Every 25**: bounds worst-case lost work to 25 items regardless of batch size, while keeping writes infrequent enough that serialization cost stays negligible.

The number itself is a round default, not a tuned value. If your per-item cost is high, lower it; the only thing 25 buys is a bound on rework.

The checkpoint stores two lists: `completed` (set of processed item IDs) and `results` (full result dicts). Resume logic filters input items: `remaining = [i for i in items if i.id not in checkpoint.completed]`. This means you can add new items to the input CSV between runs — only unprocessed items will run.

### Resume Decision Logic

When `ValidationPipeline.run()` starts, it calls `checkpoint.remaining(items)` for both image and text pools. The checkpoint is loaded once at startup. If the checkpoint file doesn't exist, `completed` is empty and all items are processed. If it exists, items with IDs in `completed` are skipped. After processing, `checkpoint.save()` writes the final state. This means:

1. First run: process all → checkpoint final state
2. Crash mid-run: checkpoint contains partial state (up to last 25-item boundary)
3. Resume: read checkpoint → skip completed IDs → process remaining → merge new results → save final state

The checkpoint does **not** track in-flight items. If item #101 is half-processed when you SIGTERM, it is not in `completed`. On resume, it will re-run. This is safe because item processing is idempotent (reading status from the compliance platform has no side effects).

### Dry-Run Design

`--dry-run` validates selector health before processing. It navigates to `login_url`, locates each configured selector, reports found/not_found/error. Why this matters:

- The selectors target someone else's UI, so they break on a schedule you do not control.
- A broken selector does not fail loudly on one item — it fails on *every* item, and each failure looks like bad input data rather than a config problem.
- Dry-run touches one page and checks each selector once, so it is cheap enough to run before every batch as a sanity check.

If a selector is broken, update `config/selectors.yaml` and dry-run again. The selectors are volatile (any frontend deploy can break them); the validation logic is stable. This separation means an operations person can fix selectors without touching Python.

### Dual-Scenario Split (ADR-001)

Image validation does strictly more work per item than text validation: it waits for an image container to render and counts loaded images, on top of everything the text path already does. Those waits are the slowest part of the operation, because they depend on network-loaded assets rather than DOM text that is already present.

Routing matters because the text items are typically the larger share of a batch. Sending them down the image path would make the majority of the batch pay the image-wait cost for a check that does not apply to them. The exact multiplier depends on the target UI and the image/text mix in your input, so no fixed figure is claimed here — but the asymmetry is structural, not marginal.

The router classifies items **before** browser launch. Text items never wait for image containers. The decision is explicit: does this item have image signals (URL, photo_required flag, visual category)? If not, it's text-only.

**Why not branch mid-validation?** By the time the page is loaded and you can see the item needs no image check, the image-container wait has already happened — you pay the timeout before you learn it was unnecessary. Routing at the input layer front-loads the decision to the one point where it is free.

**Cost:** Two validator classes that share most of their navigation and extraction logic. The duplication is real, and a stricter reading of DRY would say to unify them. The part that differs — image handling and the decision rules that follow from it — is the part most likely to change independently, which is what tipped the decision toward two classes.

### VLM Fallback

Playwright's `text_content()` extracts text from the DOM. Usually correct. Exceptions: status rendered via CSS pseudo-elements, SVG badges, or machine-readable codes in the DOM while the visible text differs. When `_read_status()` extracts text not in `KNOWN_STATUSES`, the VLM fallback screenshots the element and asks Claude to read it.

**When it fires:** Only when `_read_status()` returns text that is not in `KNOWN_STATUSES`. In the common case the status cell contains plain text and the fallback never runs. It is triggered by UI changes — badges, icons, pseudo-element content — not by data quality. How often that happens depends entirely on the target UI, so this repo does not claim a rate.

**Cost:** One screenshot plus one vision-model call per triggered item, so cost scales with trigger count rather than batch size. Because it only fires on unrecognised status text, a batch where the UI is behaving costs nothing extra. This is the reason the fallback is keyed on an unknown-value check rather than run on every item — running it unconditionally would multiply both cost and wall-clock time across the whole batch for no benefit.

**Limitation:** If the screenshot fails (element not visible, page not loaded), VLM returns None and the validator uses the empty string. The item will likely be marked SKIP. VLM fallback is best-effort, not a guarantee.

---

## Configuration

PipelineConfig is a Python dataclass with SelectorConfig nested:

```python
@dataclass
class PipelineConfig:
    input_path: Path = Path("input.csv")
    output_path: Path = Path("output/")
    selectors_path: Path = Path("config/selectors.yaml")
    max_concurrent: int = 5
    checkpoint_dir: Path = Path(".checkpoints")
    timeout_ms: int = 30000
    headless: bool = True
    retries: int = 2
    vlm_fallback: bool = False
    excel: bool = False
    selectors: SelectorConfig = field(default_factory=SelectorConfig)

@dataclass
class SelectorConfig:
    login_url: str = ""
    search_input: str = ""
    search_button: str = ""
    result_table: str = ""
    status_cell: str = ""
    image_container: str = ""
    annotation_field: str = ""
    comment_box: str = ""
    submit_button: str = ""

    @classmethod
    def from_yaml(cls, path: Path) -> "SelectorConfig":
        # Loads selectors from YAML, returns instance
```

All selectors live in `config/selectors.yaml` (YAML key names match dataclass field names). No environment variables — configuration is explicit via CLI flags and YAML file. This is deliberate: selector config is the volatile part (it tracks a UI you do not control) while pipeline config is stable. Keeping them in separate places means a UI change is a YAML edit, not a code change, and it keeps the blast radius small when selectors break.

---

## Running

```bash
# Install and setup
pip install -e ".[dev]"
playwright install chromium

# Standard batch run
batch-validator --input data/sample_input.csv --output results/

# With VLM fallback for ambiguous text extraction
batch-validator --input data/sample_input.csv --output results/ --vlm

# Generate Excel output with color-coded decisions
batch-validator --input data/sample_input.csv --output results/ --excel

# Validate selectors before processing (dry-run)
batch-validator --input data/sample_input.csv --output results/ --dry-run

# Custom concurrency and show browser window for debugging
batch-validator --input data/batch.csv --output results/ --concurrent 3 --no-headless

# Resume after crash (automatically skips checkpointed items)
batch-validator --input data/batch.csv --output results/
```

Output files (in `--output` directory):
- `results.json` — summary + full results array
- `results.csv` — flat CSV for spreadsheet import
- `results.xlsx` — (if `--excel`) color-coded decision column (green=PASS, red=FAIL, amber=REVIEW)

---

## Testing

```bash
pytest tests/ -v                    # All tests (27 total)
pytest tests/unit/ -v               # Fast, no browser automation
pytest tests/ --cov=src             # With coverage report
```

Test coverage: router classification logic (image vs text split), checkpoint persistence and resume filtering, decision evaluation for both validators (PASS/FAIL/CONFLICT/REVIEW/SKIP/FAIL_NO_IMAGE/REVIEW_MISSING_IMAGE), export formatting (JSON/CSV/Excel color mapping). No live browser tests — validators are tested with mock page objects and decision logic is unit-tested directly via `_evaluate()` methods.
