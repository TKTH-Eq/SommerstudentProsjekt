from pathlib import Path

from src.ingest.load_data import build_pdf_subset


def test_build_pdf_subset_creates_csv_and_json(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = tmp_path / "exports"

    result = build_pdf_subset(
        input_dir=repo_root / "data" / "raw" / "P&ID",
        output_dir=output_dir,
    )

    assert result["csv_path"].exists()
    assert result["json_path"].exists()
    assert result["row_count"] > 0
    assert result["document_count"] > 0
    assert "U999-1-000--PT-100-01" in result["sample_tags"]
