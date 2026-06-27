# Conservative Crawler Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract shared crawler utilities, migrate `bokhcn.py` to them, and fix runner status reporting without changing current crawler invocation style.

**Architecture:** Add a small `crawlers/common/` package with focused helpers for models, text, dates, keywords, HTTP, and JSON output. Keep crawler-specific scraping in each crawler module and migrate only `bokhcn.py` in this pass to reduce risk.

**Tech Stack:** Python 3.12, standard library `unittest`, `requests`, BeautifulSoup in existing crawler code.

---

## File Structure

- Create `crawlers/__init__.py` so tests can import crawler modules reliably.
- Create `crawlers/common/__init__.py` to mark the common helper package.
- Create `crawlers/common/models.py` for the shared `ParsedArticle` dataclass and JSON conversion.
- Create `crawlers/common/text.py` for text cleanup and search normalization.
- Create `crawlers/common/dates.py` for Vietnam timezone date parsing, formatting, and date-window helpers.
- Create `crawlers/common/keywords.py` for keyword matching and relevance checks.
- Create `crawlers/common/http.py` for HTML fetching with encoding normalization and optional retries.
- Create `crawlers/common/io.py` for JSON output.
- Modify `crawlers/bokhcn.py` to import common helpers while preserving its CLI, public crawl function, output filename, and filtering behavior.
- Modify `main.py` to only print failure status when crawlers fail.
- Create `tests/test_common_utils.py` for shared helper behavior.
- Create `tests/test_main_runner.py` for runner status behavior.

### Task 1: Shared Utility Tests

**Files:**
- Create: `tests/test_common_utils.py`

- [ ] **Step 1: Write failing tests for shared helpers**

```python
import json
import tempfile
import unittest
from pathlib import Path

from crawlers.common.dates import VN_TZ, format_datetime, is_within_days, try_parse_datetime
from crawlers.common.io import write_json
from crawlers.common.keywords import is_relevant_text, keyword_hits
from crawlers.common.models import ParsedArticle, article_to_json_dict
from crawlers.common.text import clean_text, normalize_for_search


class CommonUtilsTest(unittest.TestCase):
    def test_clean_text_normalizes_common_noise(self):
        self.assertEqual(clean_text(None), "")
        self.assertEqual(clean_text(" A\\xa0  B\\nC "), "A B C")
        self.assertEqual(clean_text("<p>Hello</p> <b>world</b>"), "Hello world")

    def test_normalize_for_search_lowercases_clean_text(self):
        self.assertEqual(normalize_for_search("  DỰ   THẢO "), "dự thảo")

    def test_try_parse_datetime_accepts_current_formats(self):
        cases = [
            "27/06/2026 08:30",
            "27-06-2026 08:30:12",
            "2026-06-27T08:30:12",
            "2026-06-27T08:30:12Z",
            "2026-06-27",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                parsed = try_parse_datetime(raw)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed.tzinfo, VN_TZ)

    def test_format_datetime_returns_project_format(self):
        self.assertEqual(format_datetime("27/06/2026 08:30"), "2026-06-27 08:30")
        self.assertIsNone(format_datetime(""))

    def test_is_within_days_keeps_unknown_dates(self):
        self.assertTrue(is_within_days(None, 7))

    def test_keyword_relevance_can_require_legal_and_topic_hits(self):
        text = "Dự thảo nghị định về dữ liệu cá nhân"
        self.assertEqual(keyword_hits(text, ["nghị định", "thông tư"]), ["nghị định"])
        self.assertTrue(
            is_relevant_text(
                text,
                legal_keywords=["nghị định"],
                topic_keywords=["dữ liệu cá nhân"],
            )
        )
        self.assertFalse(
            is_relevant_text(
                "Tin hoạt động chung",
                legal_keywords=["nghị định"],
                topic_keywords=["dữ liệu cá nhân"],
            )
        )

    def test_article_to_json_dict_preserves_existing_shape(self):
        article = ParsedArticle(
            title="Title",
            url="https://example.test/a",
            source="Source",
            published_at="2026-06-27 08:30",
            summary_raw="Summary",
        )
        self.assertEqual(
            article_to_json_dict(article),
            {
                "title": "Title",
                "url": "https://example.test/a",
                "source": "Source",
                "published_at": "2026-06-27 08:30",
                "summary_raw": "Summary",
            },
        )

    def test_write_json_outputs_utf8_pretty_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "articles.json"
            write_json([{"title": "Dự thảo"}], output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))[0]["title"], "Dự thảo")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_common_utils -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'crawlers.common'`.

### Task 2: Shared Utility Implementation

**Files:**
- Create: `crawlers/__init__.py`
- Create: `crawlers/common/__init__.py`
- Create: `crawlers/common/models.py`
- Create: `crawlers/common/text.py`
- Create: `crawlers/common/dates.py`
- Create: `crawlers/common/keywords.py`
- Create: `crawlers/common/http.py`
- Create: `crawlers/common/io.py`
- Test: `tests/test_common_utils.py`

- [ ] **Step 1: Implement shared utility modules**

Create focused modules matching the tests. Date parsing must support `%d/%m/%Y`, `%d-%m-%Y`, ISO datetime strings, optional seconds, optional timezone, and trailing `Z`.

- [ ] **Step 2: Run utility tests**

Run: `python -m unittest tests.test_common_utils -v`

Expected: PASS.

### Task 3: Runner Tests

**Files:**
- Create: `tests/test_main_runner.py`
- Modify: `main.py`

- [ ] **Step 1: Write failing runner tests**

```python
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import main


class MainRunnerTest(unittest.TestCase):
    def test_run_crawlers_reports_all_success_without_failure_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler_dir = Path(tmp) / "crawlers"
            crawler_dir.mkdir()
            (crawler_dir / "a.py").write_text("print('ok')", encoding="utf-8")

            with patch.object(main, "Path", side_effect=lambda value: crawler_dir if value == "crawlers" else Path(value)):
                with patch.object(main.subprocess, "run") as run:
                    output = io.StringIO()
                    with redirect_stdout(output):
                        result = main.run_crawlers()

            self.assertTrue(result)
            self.assertEqual(run.call_count, 1)
            self.assertIn("All crawlers completed successfully", output.getvalue())
            self.assertNotIn("Some crawlers failed", output.getvalue())

    def test_run_main_only_prints_failure_message_when_crawlers_fail(self):
        with patch.object(main, "run_crawlers", return_value=True):
            with patch.object(main, "run_whatsapp_sender") as sender:
                output = io.StringIO()
                with redirect_stdout(output):
                    main.main()

        self.assertNotIn("Some crawlers failed", output.getvalue())
        sender.assert_called_once()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run runner tests to verify the current bug**

Run: `python -m unittest tests.test_main_runner -v`

Expected: FAIL because `main.py` has no `main()` function and currently prints the failure message unconditionally in the script block.

### Task 4: Runner Fix

**Files:**
- Modify: `main.py`
- Test: `tests/test_main_runner.py`

- [ ] **Step 1: Add `main()` and fix status reporting**

Move the `if __name__ == "__main__"` body into `main()`. Print `Some crawlers failed` only when `run_crawlers()` returns false. Keep WhatsApp sender execution after crawler execution.

- [ ] **Step 2: Run runner tests**

Run: `python -m unittest tests.test_main_runner -v`

Expected: PASS.

### Task 5: Migrate `bokhcn.py`

**Files:**
- Modify: `crawlers/bokhcn.py`
- Test: `tests/test_common_utils.py`

- [ ] **Step 1: Replace duplicated helpers in `bokhcn.py`**

Import common helpers for:

- `ParsedArticle`
- `article_to_json_dict`
- `clean_text`
- `normalize_for_search`
- `fetch_html`
- `try_parse_datetime`
- `keyword_hits`
- `is_relevant_text`
- `write_json`
- `VN_TZ`

Keep `normalize_target_date`, article URL detection, HTML extraction, and `crawl_bo_khoa_hoc_cong_nghe` local.

- [ ] **Step 2: Preserve relevance behavior**

Update `is_relevant_article()` to call `is_relevant_text()` with local `LEGAL_KEYWORDS` and `TOPIC_KEYWORDS` so site-specific keyword lists are unchanged.

- [ ] **Step 3: Preserve CLI output behavior**

Replace the direct `json.dump` call in `main()` with `write_json(articles, args.output)`. Keep `--pretty` output unchanged.

- [ ] **Step 4: Compile migrated crawler**

Run: `python -m py_compile crawlers/bokhcn.py`

Expected: PASS with no output.

### Task 6: Verification

**Files:**
- All Python files

- [ ] **Step 1: Run full unit tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 2: Compile project Python files**

Run: `python -m compileall main.py whatsapp_sender.py crawlers`

Expected: PASS.

- [ ] **Step 3: Check git diff**

Run: `git diff --stat`

Expected: changes are limited to docs, common helpers, tests, `main.py`, and `crawlers/bokhcn.py`.

## Self-Review

Spec coverage: shared helpers, `bokhcn.py` migration, runner status fix, and non-network verification are covered.

Placeholder scan: no placeholder work remains.

Type consistency: tests and plan use the same names as the proposed modules and functions.
