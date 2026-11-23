# ADR-001: Dual-Scenario Processing Architecture

## Status
Accepted

## Context
Validation items fall into two fundamentally different categories: those that can be validated purely from text/attribute data (status field, annotation history) and those that require image verification (checking if product photos exist, match description, or violate policy). Processing them identically wastes time — image checks are slower (extra network requests, DOM rendering) and unnecessary for 60-70% of items that only need text validation.

## Decision
Split the pipeline into two parallel tracks at the routing layer. Items are classified into "image" or "text" scenario before processing begins. Each scenario has its own validator with different page interactions and decision logic.

## Why

**Performance:** Image validation takes ~8 seconds per item (wait for image container, count loaded images, verify render). Text validation takes ~3 seconds. Running everything through the image path would add 5 seconds per item to the 60-70% that don't need it. On a 1000-item batch, that's 3500-5000 wasted seconds.

**Decision logic differs:** A text item that's "Restricted" is a FAIL. An image item that's "Restricted" with no images is FAIL_NO_IMAGE (different follow-up action). An approved item missing images needs REVIEW_MISSING_IMAGE. These decisions only make sense in the image context.

**Both tracks run concurrently.** The pipeline doesn't process all text items first then image items — both pools are fed to `asyncio.gather` simultaneously. A batch of 500 text + 200 image items finishes in the time of the slower pool (the 200 image items at 5 concurrent), not the sum of both.

## Alternatives Considered

1. **Single path, skip image check based on flag** — simpler code but muddies the decision logic. The `_evaluate` method would need `if scenario == "image"` branches everywhere.
2. **Separate CLI commands** (`twinlane text` / `twinlane image`) — forces the user to pre-split their input and run twice. Worse UX.
3. **Router as middleware** (check mid-processing) — too late. By the time you know an item doesn't need image checks, you've already loaded the page. The routing must happen *before* browser interaction.
