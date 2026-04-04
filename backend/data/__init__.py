"""backend.data — SEC EDGAR data pipeline modules.

The package exports common helpers lazily so importing one lightweight module
does not force all optional runtime dependencies to be installed up front.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str | None]] = {
    "FilingChunk": ("backend.data.models", "FilingChunk"),
    "CompanyInfo": ("backend.data.models", "CompanyInfo"),
    "XBRLFact": ("backend.data.models", "XBRLFact"),
    "Section": ("backend.data.models", "Section"),
    "SECTION_NAMES": ("backend.data.models", "SECTION_NAMES"),
    "NormalizedTuple": ("backend.data.benchmarking", "NormalizedTuple"),
    "resolve_ticker": ("backend.data.ticker_resolver", "resolve_ticker"),
    "fetch_company_facts": ("backend.data.xbrl_fetcher", "fetch_company_facts"),
    "get_metric": ("backend.data.xbrl_fetcher", "get_metric"),
    "search_metric": ("backend.data.xbrl_fetcher", "search_metric"),
    "resolve_metric": ("backend.data.xbrl_fetcher", "resolve_metric"),
    "ComputedAnswer": ("backend.data.xbrl_reasoning", "ComputedAnswer"),
    "COMPUTED_METRICS": ("backend.data.xbrl_reasoning", "COMPUTED_METRICS"),
    "absolute_change": ("backend.data.xbrl_reasoning", "absolute_change"),
    "compare_years": ("backend.data.xbrl_reasoning", "compare_years"),
    "compute_derived_metric": ("backend.data.xbrl_reasoning", "compute_derived_metric"),
    "compute_xbrl_answer": ("backend.data.xbrl_reasoning", "compute_xbrl_answer"),
    "direct_lookup": ("backend.data.xbrl_reasoning", "direct_lookup"),
    "metric_exists": ("backend.data.xbrl_reasoning", "metric_exists"),
    "percentage_change": ("backend.data.xbrl_reasoning", "percentage_change"),
    "ratio": ("backend.data.xbrl_reasoning", "ratio"),
    "download_10k": ("backend.data.filing_downloader", "download_10k"),
    "download_filing": ("backend.data.filing_downloader", "download_filing"),
    "download_filings": ("backend.data.filing_downloader", "download_filings"),
    "find_10k_filing": ("backend.data.filing_downloader", "find_10k_filing"),
    "find_filings": ("backend.data.filing_downloader", "find_filings"),
    "parse_10k_sections": ("backend.data.section_parser", "parse_10k_sections"),
    "chunk_section": ("backend.data.chunker", "chunk_section"),
    "curate_evidence": ("backend.data.retrieval", "curate_evidence"),
    "infer_section_hints": ("backend.data.retrieval", "infer_section_hints"),
    "retrieve_documents": ("backend.data.retrieval", "retrieve_documents"),
    "retrieve_passages": ("backend.data.retrieval", "retrieve_passages"),
    "html_table_to_markdown": ("backend.data.table_extractor", "html_table_to_markdown"),
    "extract_document_text": ("backend.data.document_parser", "extract_document_text"),
    "parse_generic_document": ("backend.data.document_parser", "parse_generic_document"),
    "answer_question": ("backend.data.answer_pipeline", "answer_question"),
    "PipelineResult": ("backend.data.answer_pipeline", "PipelineResult"),
    "score_official": ("backend.data.answer_evaluator", "score_official"),
    "score_internal": ("backend.data.answer_evaluator", "score_internal"),
    "compute_retrieval_recall": ("backend.data.answer_evaluator", "compute_retrieval_recall"),
    "retrieval": ("backend.data.retrieval", None),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value
