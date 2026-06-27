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

            with patch.object(
                main,
                "Path",
                side_effect=lambda value: crawler_dir
                if value == "crawlers"
                else Path(value),
            ):
                with patch.object(main.subprocess, "run") as run:
                    output = io.StringIO()
                    with redirect_stdout(output):
                        result = main.run_crawlers()

            self.assertTrue(result)
            self.assertEqual(run.call_count, 1)
            run.assert_called_once_with(
                [main.sys.executable, "-m", "crawlers.a"],
                check=True,
            )
            self.assertIn("All crawlers completed successfully", output.getvalue())
            self.assertNotIn("Some crawlers failed", output.getvalue())

    def test_run_crawlers_skips_package_init_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler_dir = Path(tmp) / "crawlers"
            crawler_dir.mkdir()
            (crawler_dir / "__init__.py").write_text("", encoding="utf-8")
            (crawler_dir / "a.py").write_text("print('ok')", encoding="utf-8")

            with patch.object(
                main,
                "Path",
                side_effect=lambda value: crawler_dir
                if value == "crawlers"
                else Path(value),
            ):
                with patch.object(main.subprocess, "run") as run:
                    result = main.run_crawlers()

            self.assertTrue(result)
            run.assert_called_once_with(
                [main.sys.executable, "-m", "crawlers.a"],
                check=True,
            )

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
