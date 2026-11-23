import csv
import json
import logging
from pathlib import Path

logger = logging.getLogger("batch_validator")

DECISION_COLORS = {
    "PASS": "00d4aa",
    "FAIL": "ef4444",
    "FAIL_NO_IMAGE": "ef4444",
    "CONFLICT": "f59e0b",
    "REVIEW": "f59e0b",
    "REVIEW_MISSING_IMAGE": "f59e0b",
    "ERROR": "ef4444",
    "SKIP": "6b7280",
}


def export_json(results: list[dict], output_path: Path) -> None:
    summary = _build_summary(results)
    with open(output_path / "results.json", "w") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2)
    logger.info(f"JSON: {output_path / 'results.json'}")


def export_csv(results: list[dict], output_path: Path) -> None:
    fieldnames = [
        "id",
        "product_id",
        "scenario",
        "status",
        "decision",
        "annotation",
        "has_images",
        "error",
    ]
    with open(output_path / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    logger.info(f"CSV: {output_path / 'results.csv'}")


def export_excel(results: list[dict], output_path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Validation Results"

    headers = [
        "ID",
        "Product ID",
        "Scenario",
        "Status",
        "Decision",
        "Annotation",
        "Images",
        "Error",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, size=10)

    for r in results:
        ws.append(
            [
                r.get("id", ""),
                r.get("product_id", ""),
                r.get("scenario", ""),
                r.get("status", ""),
                r.get("decision", ""),
                r.get("annotation", ""),
                str(r.get("has_images", "")),
                r.get("error", ""),
            ]
        )

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        decision = row[4].value or ""
        color = DECISION_COLORS.get(decision, "6b7280")
        row[4].font = Font(color=color, bold=True, size=10)

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)

    excel_path = output_path / "results.xlsx"
    wb.save(excel_path)
    logger.info(f"Excel: {excel_path}")


def _build_summary(results: list[dict]) -> dict:
    return {
        "total": len(results),
        "pass": sum(1 for r in results if r.get("decision") == "PASS"),
        "fail": sum(1 for r in results if "FAIL" in r.get("decision", "")),
        "review": sum(1 for r in results if "REVIEW" in r.get("decision", "")),
        "error": sum(1 for r in results if r.get("decision") == "ERROR"),
        "conflict": sum(1 for r in results if r.get("decision") == "CONFLICT"),
    }
