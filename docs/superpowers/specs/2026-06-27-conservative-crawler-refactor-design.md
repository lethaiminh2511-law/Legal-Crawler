# Conservative Crawler Refactor Design

## Goal

Reduce duplicated crawler infrastructure while preserving current operational behavior:
each crawler remains runnable directly with `python crawlers/<name>.py`, JSON output shape stays compatible with the WhatsApp sender, and site-specific scraping logic remains inside each crawler file.

## Scope

This refactor extracts shared support code that is repeated across crawler modules:

- article record model and JSON conversion
- text cleanup and search normalization
- Vietnam timezone date parsing and formatting
- keyword hit detection and relevance filtering
- HTTP fetch/session helpers
- common JSON file writing
- runner status handling in `main.py`

The refactor does not move crawlers into an installable package, does not change crawler output filenames, and does not redesign site-specific parsing.

## Architecture

Create a lightweight `crawlers/common/` package. Crawler modules import focused helpers from this package while keeping their existing public crawl functions and `main()` entry points.

Shared modules:

- `crawlers/common/models.py`: `ParsedArticle` dataclass and `article_to_json_dict`.
- `crawlers/common/text.py`: `clean_text`, `normalize_for_search`.
- `crawlers/common/dates.py`: `VN_TZ`, flexible datetime parsing, date formatting, day-window helpers.
- `crawlers/common/keywords.py`: default legal/topic keywords, `keyword_hits`, `is_relevant_text`.
- `crawlers/common/http.py`: `fetch_html` and session header setup helpers.
- `crawlers/common/io.py`: `write_json`.

Crawler-specific models with extra fields may remain local where needed. Shared helpers should be adopted incrementally, starting with `bokhcn.py` because it is active in the IDE and recently touched for 403 handling.

## Data Flow

Each crawler still:

1. Builds one or more listing URLs or API requests.
2. Extracts candidate article records or links.
3. Fetches detail pages where needed.
4. Produces dictionaries with existing keys such as `title`, `url`, `source`, `published_at`, and `summary_raw`.
5. Writes a JSON output file from its CLI.

Shared utilities support those steps but do not own crawler orchestration.

## Error Handling

HTTP helpers preserve the existing behavior of raising for failed responses and fixing `iso-8859-1` fallback encoding. Retry support is included for crawlers that already need it, such as `bokhcn.py`.

Crawler loops continue to catch per-article failures and log warnings so one failed article does not stop the whole crawler.

`main.py` should report success or failure accurately. It should only print the failure message when at least one crawler fails.

## Testing

Add focused unit tests for the shared utilities and runner behavior:

- text cleanup handles `None`, non-breaking spaces, HTML fragments, and repeated whitespace
- date parsing supports current formats used by crawler modules
- keyword filtering respects required legal/topic switches
- JSON serialization preserves expected article fields
- runner returns false only when a crawler subprocess fails and prints correct status

Avoid live network tests. Existing crawler detail parsing can be tested later with fixture HTML if needed.

## Migration Plan

Implement shared modules first with tests. Then migrate `bokhcn.py` to prove the pattern while preserving its CLI and output. Finally fix `main.py` status reporting and verify imports/compilation across all crawler files.

Future follow-up work can migrate the remaining crawlers in small batches.
