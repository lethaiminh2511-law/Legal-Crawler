# HCMC News Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `crawlers/hcmcity.py` to crawl the Ho Chi Minh City news listing.

**Architecture:** Follow `crawlers/ipvn.py` as a self-contained crawler module with URL building, listing/detail parsing, date and keyword filtering, dedupe, and CLI JSON output. The listing URL increments the `_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_iwwYBC4Hj8wV_cur` parameter from page 1 upward.

**Tech Stack:** Python 3.12, `requests`, BeautifulSoup, `unittest`.

## Global Constraints

- Keep output shape compatible with existing crawlers: `title`, `url`, `source`, `published_at`, `summary_raw`, `category_url`.
- Use the HCMC listing URL provided by the user as the default prefix.
- Do not modify unrelated existing untracked crawler files.

---

### Task 1: HCMC Crawler

**Files:**
- Create: `crawlers/hcmcity.py`
- Create: `tests/test_hcmcity.py`

**Interfaces:**
- Produces: `build_listing_url(prefix: str, page_no: int, items_per_page: int = 10) -> str`
- Produces: `extract_listing_articles(html: str, category_url: str) -> list[ParsedArticle]`
- Produces: `crawl_hcmcity(...) -> list[dict]`

- [ ] **Step 1: Write failing tests**

Create tests for page URL construction, listing card extraction, and crawl dedupe with injected session responses.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_hcmcity.py -q`

Expected: fails because `crawlers.hcmcity` does not exist.

- [ ] **Step 3: Implement crawler**

Create `crawlers/hcmcity.py` using the `ipvn.py` crawler shape and HCMC-specific selectors.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_hcmcity.py -q
python -m py_compile crawlers/hcmcity.py tests/test_hcmcity.py
uv run python crawlers/hcmcity.py --days 0 --max-articles 3 --max-pages-per-prefix 1 --no-filter --no-detail --pretty --output /tmp/hcmcity_articles.json
```
