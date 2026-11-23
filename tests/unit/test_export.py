from batch_validator.core.export import _build_summary, export_csv, export_excel, export_json

SAMPLE_RESULTS = [
    {
        "id": "1",
        "product_id": "SKU-1",
        "scenario": "text",
        "status": "Approved",
        "decision": "PASS",
        "annotation": "",
    },
    {
        "id": "2",
        "product_id": "SKU-2",
        "scenario": "image",
        "status": "Restricted",
        "decision": "FAIL",
        "annotation": "",
        "has_images": True,
    },
    {
        "id": "3",
        "product_id": "SKU-3",
        "scenario": "text",
        "status": "Restricted",
        "decision": "CONFLICT",
        "annotation": "Previously Approved",
    },
    {
        "id": "4",
        "product_id": "SKU-4",
        "scenario": "text",
        "status": "",
        "decision": "ERROR",
        "error": "timeout",
    },
]


class TestExport:
    def test_json_output(self, tmp_path):
        export_json(SAMPLE_RESULTS, tmp_path)
        assert (tmp_path / "results.json").exists()

    def test_csv_output(self, tmp_path):
        export_csv(SAMPLE_RESULTS, tmp_path)
        content = (tmp_path / "results.csv").read_text()
        assert "SKU-1" in content
        assert "PASS" in content

    def test_excel_output(self, tmp_path):
        export_excel(SAMPLE_RESULTS, tmp_path)
        assert (tmp_path / "results.xlsx").exists()

    def test_summary_counts(self):
        summary = _build_summary(SAMPLE_RESULTS)
        assert summary["total"] == 4
        assert summary["pass"] == 1
        assert summary["fail"] == 1
        assert summary["conflict"] == 1
        assert summary["error"] == 1
