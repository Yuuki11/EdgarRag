"""Tests for benchmark governance, reasoning, retrieval, and leakage guards."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.data.benchmarking import (
    build_split_metadata,
    extract_metrics,
    extract_quarters,
    financebench_row_to_manifest_entry,
    normalize_tuple,
)
from backend.data.answer_evaluator import parse_numeric
from backend.data.xbrl_reasoning import (
    absolute_change,
    direct_lookup,
    ebitda_margin,
    percentage_change,
    ratio,
)


def test_financebench_manifest_entry_extracts_eval_tuple():
    row = {
        "financebench_id": "fb_001",
        "company": "Apple Inc.",
        "doc_name": "AAPL_2023_10K",
        "doc_period": 2023,
        "question_type": "metrics-generated",
        "question_reasoning": "Information extraction",
        "question": "What was Apple Inc.'s revenue in FY2023?",
        "dataset_subset_label": "OPEN_SOURCE",
    }
    company_to_ticker = {"apple inc": "AAPL"}
    entry = financebench_row_to_manifest_entry(row, company_to_ticker, ["revenue", "net income"])
    assert entry["ticker"] == "AAPL"
    assert entry["eval_policy"] == "eval_only"
    assert entry["normalized_tuple"]["years"] == [2023]
    assert entry["normalized_tuple"]["metrics"] == ["revenue"]
    assert entry["normalized_tuple"]["operation"] == "lookup"


def test_extract_metrics_does_not_match_eps_inside_pepsico():
    metrics = extract_metrics(
        "As of FY2023Q1, why did Pepsico raise full year guidance for FY2023?",
        ["eps", "revenue", "operating income"],
    )
    assert "eps" not in metrics


def test_extract_quarters_parses_fy_quarter_forms():
    quarters = extract_quarters("As of FY2023Q1, by how many points did guidance change?")
    assert quarters[0].year == 2023
    assert quarters[0].period == "Q1"


def test_parse_numeric_requires_word_boundary_for_million_suffix():
    assert parse_numeric("11,588\nNet income from operating activities in FY2019. [Source 1]") == 11588.0


def test_build_split_metadata_for_secqa_tuple():
    tuple_obj = normalize_tuple(
        ticker="AAPL",
        years=[2023],
        metrics=["revenue"],
        operation="lookup",
    )
    metadata = build_split_metadata("xbrl_qa", tuple_obj=tuple_obj)
    assert metadata["dataset_role"] in {"train", "internal_secqa_dev", "heldout_secqa_test"}
    assert metadata["tuple_key"] == tuple_obj.to_key()


@patch("backend.data.xbrl_reasoning.get_metric")
@patch("backend.data.xbrl_reasoning.search_metric")
def test_xbrl_reasoning_numeric_operations(mock_search, mock_get_metric):
    class Fact:
        def __init__(self, concept, value, year, unit="USD"):
            self.concept = concept
            self.value = value
            self.unit = unit
            self.fiscal_year = year
            self.fiscal_period = "FY"
            self.filed = f"{year}-12-31"
            self.form = "10-K"

    def fake_get_metric(ticker, metric, year, period="FY"):
        mapping = {
            ("AAPL", "revenue", 2022): Fact("Revenues", 100.0, 2022),
            ("AAPL", "revenue", 2023): Fact("Revenues", 125.0, 2023),
            ("AAPL", "gross profit", 2023): Fact("GrossProfit", 50.0, 2023),
        }
        return mapping.get((ticker, metric, year))

    mock_get_metric.side_effect = fake_get_metric
    mock_search.return_value = []

    lookup = direct_lookup("AAPL", "revenue", 2023)
    assert lookup is not None
    assert lookup.value == 125.0

    delta = absolute_change("AAPL", "revenue", 2022, 2023)
    assert delta is not None
    assert delta.value == 25.0

    pct = percentage_change("AAPL", "revenue", 2022, 2023)
    assert pct is not None
    assert round(pct.value, 2) == 25.0

    gross_margin = ratio("AAPL", "gross profit", "revenue", 2023)
    assert gross_margin is not None
    assert round(gross_margin.value, 4) == 0.4


@patch("backend.data.xbrl_reasoning.get_metric")
@patch("backend.data.xbrl_reasoning.search_metric")
def test_ebitda_margin_returns_ratio_value_not_double_percent(mock_search, mock_get_metric):
    class Fact:
        def __init__(self, concept, value, year, unit="USD"):
            self.concept = concept
            self.value = value
            self.unit = unit
            self.fiscal_year = year
            self.fiscal_period = "FY"
            self.filed = f"{year}-12-31"
            self.form = "10-K"

    def fake_get_metric(ticker, metric, year, period="FY"):
        mapping = {
            ("NFLX", "operating income", 2015, "FY"): Fact("OperatingIncomeLoss", 306996000, 2015),
            ("NFLX", "depreciation", 2015, "FY"): Fact("DepreciationDepletionAndAmortization", 62283000, 2015),
            ("NFLX", "revenue", 2015, "FY"): Fact("Revenues", 6779511000, 2015),
        }
        return mapping.get((ticker, metric, year, period))

    mock_get_metric.side_effect = fake_get_metric
    mock_search.return_value = []

    result = ebitda_margin("NFLX", 2015)
    assert result is not None
    assert round(float(result.value) * 100, 1) == 5.4


@patch("backend.data.filing_downloader.resolve_ticker")
@patch("backend.data.filing_downloader.get_filing_index")
@patch("backend.data.filing_downloader._fetch_submission_file")
def test_find_10k_filing_uses_archived_submission_files(
    mock_archive,
    mock_index,
    mock_resolve,
):
    from backend.data.filing_downloader import find_10k_filing

    mock_resolve.return_value = ("0000320193", "Apple Inc.")
    mock_index.return_value = {
        "filings": {
            "recent": {
                "form": [],
                "accessionNumber": [],
                "filingDate": [],
                "reportDate": [],
                "primaryDocument": [],
            },
            "files": [{"name": "CIK0000320193-submissions-001.json"}],
        }
    }
    mock_archive.return_value = {
        "form": ["10-K"],
        "accessionNumber": ["0000320193-19-000119"],
        "filingDate": ["2019-10-31"],
        "reportDate": ["2018-09-29"],
        "primaryDocument": ["a10-k20189292018.htm"],
    }

    filing = find_10k_filing("AAPL", 2018)
    assert filing is not None
    assert filing["filing_date"] == "2019-10-31"
    assert filing["url"].endswith("/320193/000032019319000119/a10-k20189292018.htm")


def test_hierarchical_retrieval_with_metadata_filters(tmp_path, monkeypatch):
    from backend.data import retrieval

    chunks_dir = tmp_path / "chunks" / "AAPL" / "2023"
    chunks_dir.mkdir(parents=True)
    sample_chunks = [
        {
            "text": "Risk factors include supply chain constraints and foreign exchange exposure.",
            "ticker": "AAPL",
            "year": 2023,
            "section": "item_1a",
            "section_name": "Risk Factors",
            "chunk_index": 0,
            "filing_date": "2023-11-03",
            "form_type": "10-K",
            "source_url": "https://example.com",
            "token_count": 30,
        },
        {
            "text": "Revenue increased because services revenue grew.",
            "ticker": "AAPL",
            "year": 2023,
            "section": "item_7",
            "section_name": "Management's Discussion and Analysis",
            "chunk_index": 1,
            "filing_date": "2023-11-03",
            "form_type": "10-K",
            "source_url": "https://example.com",
            "token_count": 20,
        },
    ]
    (chunks_dir / "chunks.json").write_text(json.dumps(sample_chunks), encoding="utf-8")
    monkeypatch.setattr(retrieval, "CHUNKS_DIR", tmp_path / "chunks")

    docs = retrieval.retrieve_documents(
        "What risk factors did Apple mention in 2023?",
        ticker="AAPL",
        years=[2023],
    )
    assert len(docs) == 1

    passages = retrieval.retrieve_passages("What risk factors did Apple mention?", docs)
    assert passages[0]["section"] == "item_1a"
    assert passages[0]["doc_type"] == "10-K"
    assert passages[0]["section_family"] == "risk"

    curated = retrieval.curate_evidence(passages, ticker="AAPL", years=[2023])
    assert curated["needs_complementary_retrieval"] is False
    assert len(curated["passages"]) >= 1


@patch("backend.data.answer_pipeline._answer_via_rag", return_value=("", [], ""))
@patch("backend.data.answer_pipeline.compute_xbrl_answer")
def test_answer_pipeline_merges_doc_period_with_question_years(mock_compute, mock_rag):
    from backend.data.answer_pipeline import answer_question

    captured = {}

    def fake_compute(plan):
        captured.update(plan)
        return None

    mock_compute.side_effect = fake_compute

    result = answer_question(
        question=(
            "What is the FY2019 fixed asset turnover ratio for Activision Blizzard? "
            "Fixed asset turnover ratio is defined as: FY2019 revenue / "
            "(average PP&E between FY2018 and FY2019)."
        ),
        ticker="ATVI",
        years=[2019],
    )

    assert captured["operation"] == "ratio_avg_balance"
    assert captured["years"] == [2018, 2019]
    assert captured["metrics"] == ["revenue", "net ppe"]
    assert result.fallback_used is True


@patch("backend.data.answer_pipeline._answer_via_rag", return_value=("", [], ""))
@patch("backend.data.answer_pipeline.compute_xbrl_answer")
def test_answer_pipeline_sets_quarter_period_in_xbrl_plan(mock_compute, mock_rag):
    from backend.data.answer_pipeline import answer_question

    captured = {}

    def fake_compute(plan):
        captured.update(plan)
        return None

    mock_compute.side_effect = fake_compute

    answer_question(
        question="What is Amazon's FY2023Q1 revenue?",
        ticker="AMZN",
        years=[2023],
    )

    assert captured["period"] == "Q1"
    assert captured["years"] == [2023]


def test_leakage_checker_fails_on_overlap(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    train_path = tmp_path / "train.jsonl"

    tuple_key = "AAPL|2023|revenue|lookup"
    manifest_path.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "eval_policy": "eval_only",
                        "tuple_key": tuple_key,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    train_path.write_text(
        json.dumps(
            {
                "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
                "metadata": {
                    "normalized_tuple": {
                        "ticker": "AAPL",
                        "years": [2023],
                        "metrics": ["revenue"],
                        "operation": "lookup",
                    }
                },
            }
        ) + "\n",
        encoding="utf-8",
    )

    script = Path(__file__).resolve().parents[2] / "scripts" / "check_benchmark_leakage.py"
    result = subprocess.run(
        [sys.executable, str(script), str(train_path), "--manifest", str(manifest_path)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 1
    assert "BENCHMARK LEAKAGE DETECTED" in result.stdout
