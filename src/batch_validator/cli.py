import asyncio
import logging
from pathlib import Path

import click

from .config import PipelineConfig
from .core.dryrun import validate_selectors
from .core.pipeline import ValidationPipeline

logging.basicConfig(
    level="INFO",
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"%(module)s","msg":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)


@click.command()
@click.option("--input", "input_path", required=True, type=click.Path(exists=True))
@click.option("--output", "output_path", default="output", type=click.Path())
@click.option("--selectors", "selectors_path", default="config/selectors.yaml", type=click.Path())
@click.option("--concurrent", default=5, type=int, help="Max parallel browser contexts")
@click.option("--headless/--no-headless", default=True)
@click.option("--retries", default=2, type=int)
@click.option(
    "--vlm/--no-vlm",
    "vlm_fallback",
    default=False,
    help="Use Claude Vision when text extraction is ambiguous",
)
@click.option(
    "--excel/--no-excel", default=False, help="Generate Excel output with color-coded decisions"
)
@click.option(
    "--dry-run", is_flag=True, help="Validate selectors against live UI without processing items"
)
def main(
    input_path,
    output_path,
    selectors_path,
    concurrent,
    headless,
    retries,
    vlm_fallback,
    excel,
    dry_run,
):
    config = PipelineConfig(
        input_path=Path(input_path),
        output_path=Path(output_path),
        selectors_path=Path(selectors_path),
        max_concurrent=concurrent,
        headless=headless,
        retries=retries,
        vlm_fallback=vlm_fallback,
        excel=excel,
    )

    if dry_run:
        results = asyncio.run(validate_selectors(config))
        for name, status in results.items():
            icon = "✓" if status.get("status") in ("ok", "found") else "✗"
            click.echo(f"  {icon} {name}: {status}")
        return

    pipeline = ValidationPipeline(config)
    asyncio.run(pipeline.run())


if __name__ == "__main__":
    main()
