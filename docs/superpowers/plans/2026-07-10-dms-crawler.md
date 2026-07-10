# DMS Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `crawlers/dms.py` to crawl DMS news and policy listings.

**Architecture:** Follow `crawlers/ipvn.py` as a self-contained crawler module. Fetch DMS category listing pages, parse article cards and rows, optionally enrich each article from its detail page, filter by date and configured keywords, and expose both `crawl_dms()` and a CLI.

**Tech Stack:** Python 3.12, `requests`, `beautifulsoup4`, stdlib `argparse`, `json`, `datetime`, `zoneinfo`.

## Global Constraints

- Create only `crawlers/dms.py` unless verification reveals a necessary local adjustment.
- Default prefixes are `https://dms.gov.vn/tin-t%E1%BB%A9c-s%E1%BB%B1-ki%E1%BB%87n` and `https://dms.gov.vn/chinh-sach`.
- Preserve the output shape used by `ipvn.py`: `title`, `url`, `source`, `published_at`, `summary_raw`, `category_url`.
- Default SSL verification is disabled because DMS currently has a certificate-chain issue in this environment.

---

### Task 1: Implement DMS Crawler

**Files:**
- Create: `crawlers/dms.py`

**Interfaces:**
- Consumes: `LEGAL_KEYWORDS`, `TOPIC_KEYWORDS` from `crawlers.common.keywords`.
- Produces: `crawl_dms(prefixes: Optional[list[str]] = None, days: Optional[int] = 1, max_articles: int = 50, items_per_page: int = 15, max_pages_per_prefix: int = 5, filter_relevant: bool = True, require_legal_keyword: bool = True, require_topic_keyword: bool = True, fetch_details: bool = True, verify_ssl: bool = False) -> list[dict]`.

- [ ] Create `crawlers/dms.py` from the `ipvn.py` structure.
- [ ] Add DMS-specific constants, headers, `ParsedArticle`, URL canonicalization, date parsing, and listing URL construction.
- [ ] Parse listing articles from `.list-tin-part-1` and `.list-tin-part-2`, using selectors for `.post-typical`, `.title-item`, `.list-bottom`, and `.title-list-tin-2`.
- [ ] Parse detail pages with `.entry-title`, `.entry-meta .more-info`, and `.entry-summary`.
- [ ] Add relevance/date filtering, duplicate handling, polite delays, JSON conversion, CLI args, and JSON output.

### Task 2: Verify

**Files:**
- Inspect: `crawlers/dms.py`

**Interfaces:**
- Consumes: `crawl_dms()` from Task 1.
- Produces: a syntax-clean module and a live smoke result.

- [ ] Run `python -m py_compile crawlers/dms.py`.
- [ ] Run `uv run python crawlers/dms.py --days 0 --max-articles 3 --max-pages-per-prefix 1 --no-filter --pretty --output /tmp/dms_articles.json`.
- [ ] Confirm the output contains DMS article dictionaries with non-empty `title`, `url`, `source`, and `category_url`.
