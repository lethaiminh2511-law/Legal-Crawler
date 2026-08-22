# Creating a New Crawler

This guide describes the current crawler contract in this repository. Use it
when adding a new source under `crawlers/` so it works with the top-level
runner, writes the same JSON shape, and follows the same filtering behavior as
the existing crawlers.

## File and Entry Point

Create one module per source:

```text
crawlers/<source_name>.py
```

The filename is the crawler identity. `main.py` discovers every `*.py` file in
`crawlers/` except `__init__.py` and runs it as a module:

```bash
python -m crawlers.<source_name>
```

Because of that, every crawler must be importable as part of the `crawlers`
package and must include a direct CLI entry point:

```python
if __name__ == "__main__":
    main()
```

Use a source-specific crawl function named after the source, for example
`crawl_mof`, `crawl_vibonline`, or `crawl_<source_name>`. Tests can import this
function directly without running the CLI.

## Required CLI Arguments

New crawlers should expose the same core arguments:

| Argument | Default | Purpose |
| --- | --- | --- |
| `--days` | `1` | Crawl only items in the recent day window. Use `--days 0` to disable date filtering. |
| `--max-articles` | `50` | Stop after this many matching items. |
| `--output` | `<source_name>_articles.json` | JSON output path in the repository root by default. |
| `--pretty` | `False` | Also print formatted JSON to stdout. |

The top-level runner checks whether the crawler source text contains `--days`.
If it does, the runner passes:

- `--days 2` for the morning WhatsApp window
- `--days 1` for the other window

That means a new crawler should support `--days` unless the source truly cannot
be filtered by time. In the CLI path, convert `--days 0` to `None` before
calling the crawl function:

```python
days=None if args.days == 0 else args.days
```

## Optional CLI Arguments

Add site-specific arguments only when the target source needs them. Reuse the
existing names where possible:

| Argument pattern | Use when |
| --- | --- |
| `--prefixes` | The crawler visits multiple category/listing URL prefixes. Parse as comma-separated strings. |
| `--category-ids` | The source API uses category IDs. Parse as comma-separated IDs. |
| `--category-urls` or `--seed-urls` | The source starts from configurable listing URLs. Parse as comma-separated URLs. |
| `--date-from` and `--date-to` | The source API accepts explicit date ranges. These should override or complement `--days`. |
| `--items-per-page`, `--page-size` | The source has a configurable API/listing page size. |
| `--max-pages`, `--max-pages-per-prefix`, `--max-pages-per-category`, `--max-pages-per-source` | The crawler needs a pagination cap. |
| `--no-detail` | Detail pages are normally fetched, but callers may want listing-only mode. |
| `--verify-ssl` | SSL verification is disabled by default for a source with known certificate-chain problems. |

Prefer `--no-detail` for new crawlers. A few existing modules use source-specific
variants such as `--no-details` or `--fetch-details`; keep those for backward
compatibility, but do not copy the inconsistency into new modules.

Do not add CLI flags that let normal runs disable relevance filtering. Tests
assert that crawler CLI paths do not expose switches such as `--no-filter`,
`--filter-relevant`, or `--require-topic-keyword`.

## Output Contract

Each crawler writes a UTF-8 JSON array. Every article dictionary should include
these fields:

```json
{
  "title": "Article title",
  "url": "https://example.test/article",
  "source": "Source display name",
  "published_at": "2026-06-27 09:30",
  "summary_raw": "Raw or cleaned summary text"
}
```

`published_at` may be `null` when the source does not expose a parseable date.
Use the normalized `%Y-%m-%d %H:%M` format when possible.

Source-specific fields are allowed when useful. Existing examples include
`category`, `category_url`, `document_type`, `status`, `effective_date`,
`issuing_agency`, and API IDs. Keep the core fields stable because downstream
code expects them.

Use `ensure_ascii=False` and `indent=2` when writing JSON. Prefer the shared
helper for new crawlers:

```python
from crawlers.common.io import write_json

write_json(articles, args.output)
```

## Shared Architecture

Most crawlers follow this flow:

1. Configure logging in `main()`.
2. Create a `requests.Session`, usually with browser-like headers.
3. Fetch listing pages or API pages.
4. Parse candidate records into article objects.
5. Stop pagination when there are no more candidates, the date window is older
   than requested, or `max_articles` has been reached.
6. Deduplicate by URL before fetching details or appending output.
7. Fetch detail pages when details improve dates, summaries, or metadata.
8. Filter by date and relevance.
9. Serialize matching articles to dictionaries.
10. Write JSON and optionally print pretty JSON.

Keep site-specific scraping in the crawler module. Use `crawlers/common/` for
small shared concerns:

| Module | Use |
| --- | --- |
| `crawlers.common.http` | `create_session`, `fetch_html` with timeout, retries, and encoding fallback. |
| `crawlers.common.text` | `clean_text`, `normalize_for_search`. |
| `crawlers.common.dates` | Vietnam timezone, flexible datetime parsing, date formatting, day-window helpers. |
| `crawlers.common.keywords` | Legal/topic keyword lists and relevance checks. |
| `crawlers.common.models` | Basic `ParsedArticle` and JSON conversion for simple crawlers. |
| `crawlers.common.io` | UTF-8 pretty JSON writing. |

If the source needs extra fields, define a local dataclass instead of forcing
those fields into the common model.

## Filtering Rules

Default crawler behavior should be conservative and match the current tests:

- `filter_relevant=True`
- `require_legal_keyword=True`
- `require_topic_keyword=True`

A record is relevant only when combined searchable text contains at least one
legal keyword and at least one topic keyword. Build that searchable text from
the title, summary, document type, category/status metadata, and any useful
detail-page content.

Date filtering should accept unknown dates unless the source-specific behavior
has a stronger reason to drop them. This avoids losing records from sources that
omit dates in listings but provide useful detail content.

## Error Handling

Crawler loops should tolerate individual bad records:

- Let listing/API fetch failures stop the current page or category with a
  warning.
- Catch per-article detail failures, log a warning, and continue.
- Avoid live network work at import time. Network calls belong in the crawl
  function or below `main()`.
- Sleep briefly between detail requests when a crawler already uses polite
  delays or the source is sensitive.

The top-level runner treats a crawler as failed only when its module process
exits non-zero. Do not swallow fatal setup errors if the crawler cannot run at
all.

## Starter Skeleton

```python
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from crawlers.common.dates import format_datetime, is_within_days
from crawlers.common.http import create_session, fetch_html
from crawlers.common.io import write_json
from crawlers.common.keywords import is_relevant_text
from crawlers.common.text import clean_text


SOURCE_NAME = "Example Source"
DEFAULT_PREFIXES = ["https://example.test/news"]


@dataclass
class ParsedArticle:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    summary_raw: str
    category_url: str


def parse_prefixes(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def extract_listing_articles(html: str, category_url: str) -> list[ParsedArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[ParsedArticle] = []

    for node in soup.select("article"):
        title = clean_text(node.get_text(" "))
        link = node.select_one("a[href]")
        if not title or not link:
            continue

        time_node = node.select_one("time")
        raw_date = ""
        if time_node:
            raw_date = time_node.get("datetime") or time_node.get_text(" ")

        articles.append(
            ParsedArticle(
                title=title,
                url=link["href"],
                source=SOURCE_NAME,
                published_at=format_datetime(raw_date),
                summary_raw=title,
                category_url=category_url,
            )
        )

    return articles


def is_relevant_article(
    article: ParsedArticle,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
) -> bool:
    searchable = " ".join(
        [
            article.title,
            article.summary_raw,
            article.category_url,
        ]
    )
    return is_relevant_text(
        searchable,
        require_legal_keyword=require_legal_keyword,
        require_topic_keyword=require_topic_keyword,
    )


def article_to_json_dict(article: ParsedArticle) -> dict[str, Optional[str]]:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
        "category_url": article.category_url,
    }


def crawl_example_source(
    prefixes: list[str] | None = None,
    days: Optional[int] = 1,
    max_articles: int = 50,
    max_pages_per_prefix: int = 5,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
) -> list[dict[str, Optional[str]]]:
    session = create_session(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
            )
        }
    )
    results: list[dict[str, Optional[str]]] = []
    seen_urls: set[str] = set()

    for prefix in prefixes or DEFAULT_PREFIXES:
        for page_no in range(1, max_pages_per_prefix + 1):
            if len(results) >= max_articles:
                break

            listing_url = f"{prefix}?page={page_no}"
            try:
                html = fetch_html(session, listing_url)
            except Exception as exc:
                logging.warning("Failed listing page %s: %s", listing_url, exc)
                break

            page_articles = extract_listing_articles(html, prefix)
            if not page_articles:
                break

            for article in page_articles:
                if len(results) >= max_articles:
                    break
                if article.url in seen_urls:
                    continue
                seen_urls.add(article.url)

                if not is_within_days(article.published_at, days):
                    continue

                if filter_relevant and not is_relevant_article(
                    article,
                    require_legal_keyword=require_legal_keyword,
                    require_topic_keyword=require_topic_keyword,
                ):
                    continue

                results.append(article_to_json_dict(article))

    logging.info("Finished. Parsed %d relevant articles.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Example Source and export legal/IP-tech updates as JSON."
    )
    parser.add_argument(
        "--prefixes",
        type=str,
        default=",".join(DEFAULT_PREFIXES),
        help="Comma-separated listing URL prefixes.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Only include items from the last N days. Use --days 0 to disable.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Maximum number of articles to return. Default: 50.",
    )
    parser.add_argument(
        "--max-pages-per-prefix",
        type=int,
        default=5,
        help="Maximum listing pages per prefix. Default: 5.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="example_source_articles.json",
        help="JSON output file.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print formatted JSON to stdout.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    articles = crawl_example_source(
        prefixes=parse_prefixes(args.prefixes),
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        max_pages_per_prefix=args.max_pages_per_prefix,
        filter_relevant=True,
        require_legal_keyword=True,
        require_topic_keyword=True,
    )

    write_json(articles, args.output)

    if args.pretty:
        print(json.dumps(articles, ensure_ascii=False, indent=2))

    print(f"Saved {len(articles)} articles to {args.output}")


if __name__ == "__main__":
    main()
```

Treat the skeleton as a shape, not as copy-paste-complete code. Real sources
usually need URL joining, API payloads, date extraction, detail parsing, or
custom stopping logic.

## Testing Checklist

Before considering a new crawler complete:

- Add focused tests for parsing helpers and crawl orchestration with mocked
  HTTP/session responses.
- Avoid live network tests.
- Test deduplication, pagination stop conditions, date filtering, relevance
  filtering, and JSON fields.
- Test source-specific selectors or API payloads that are likely to break.
- Run the crawler directly with a small cap, for example:

```bash
uv run python -m crawlers.<source_name> --days 1 --max-articles 5 --pretty
```

- Run the relevant test suite:

```bash
uv run pytest
```

## New Crawler Checklist

- `crawlers/<source_name>.py` exists and imports cleanly.
- The module has `crawl_<source_name>()`, `main()`, and the `__main__` guard.
- The CLI includes `--days`, `--max-articles`, `--output`, and `--pretty`.
- `--days 0` maps to no date filter.
- The default output file is `<source_name>_articles.json`.
- Normal CLI execution keeps both legal and topic keyword filters enabled.
- Results include the core JSON fields.
- URLs are deduped.
- Per-record failures are logged without stopping the whole crawler.
- No network work runs at import time.
- Tests cover the source-specific parser/API behavior without live network.
