import os
import io
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import utils


FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Multimodal LLM study</title>
    <summary>A study of MLLM systems.</summary>
    <author><name>Researcher</name></author>
    <link href="https://arxiv.org/abs/2501.00001v2" rel="alternate"/>
    <category term="cs.CV"/>
    <published>2025-01-02T12:00:00Z</published>
    <updated>2026-09-29T12:00:00Z</updated>
  </entry>
  <entry>
    <title>Physics study</title>
    <summary>A physics paper.</summary>
    <author><name>Researcher</name></author>
    <link href="https://arxiv.org/abs/2501.00002v1" rel="alternate"/>
    <category term="physics.optics"/>
    <published>2025-01-03T12:00:00Z</published>
    <updated>2025-01-03T12:00:00Z</updated>
  </entry>
</feed>'''


class TopicSearchTests(unittest.TestCase):
    def test_variants_match_either_title_or_abstract(self):
        query = utils.build_arxiv_query([
            "Multimodal Large Language Model", "MLLM", "Multimodal LLM",
        ])
        self.assertEqual(query,
            '(ti:"Multimodal Large Language Model" OR abs:"Multimodal Large Language Model")'
            ' OR (ti:"MLLM" OR abs:"MLLM")'
            ' OR (ti:"Multimodal LLM" OR abs:"Multimodal LLM")')

    def test_single_keyword_and_normalized_duplicates(self):
        self.assertEqual(utils.build_arxiv_query("MLLM"),
                         '(ti:"MLLM" OR abs:"MLLM")')
        self.assertEqual(utils.build_arxiv_query([" MLLM ", "mllm"]),
                         utils.build_arxiv_query("MLLM"))
        self.assertEqual(utils.build_arxiv_query("MLLM", "AND"),
                         '(ti:"MLLM" AND abs:"MLLM")')

    def test_invalid_keywords_are_rejected(self):
        for keywords in ([], "", ["MLLM", " "], ['a"b']):
            with self.subTest(keywords=keywords), self.assertRaises(ValueError):
                utils.build_arxiv_query(keywords)

    def test_one_encoded_request_per_topic_and_both_dates(self):
        keywords = ["Multimodal Large Language Model", "MLLM", "Multimodal LLM"]
        with patch.object(utils.urllib.request, "urlopen",
                          return_value=Mock(read=Mock(return_value=FEED))) as request:
            papers = utils.get_daily_papers_by_keyword(
                keywords, ["Title", "Link", "Submitted", "Updated"], 20)
        request.assert_called_once()
        self.assertTrue(request.call_args.args[0].full_url.startswith("https://"))
        self.assertEqual(request.call_args.kwargs["timeout"], 60)
        params = parse_qs(urlparse(request.call_args.args[0].full_url).query)
        self.assertEqual(params["search_query"], [utils.build_arxiv_query(keywords)])
        self.assertEqual(params["max_results"], ["20"])
        self.assertEqual(params["sortBy"], ["lastUpdatedDate"])
        self.assertEqual(params["sortOrder"], ["descending"])
        self.assertEqual(len(papers), 1)  # The physics-only paper is filtered out.
        self.assertEqual(papers[0]["Submitted"], "2025-01-02T12:00:00Z")
        self.assertEqual(papers[0]["Updated"], "2026-09-29T12:00:00Z")

    def test_main_generates_one_section_per_topic(self):
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        original_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path("README.md").write_text("Last update: 2026-01-01\n")
                Path(".github").mkdir()
                Path(".github/ISSUE_TEMPLATE.md").write_text("Old issue\n")
                with patch.object(utils.urllib.request, "urlopen",
                                  return_value=Mock(read=Mock(return_value=FEED))) as request, \
                        patch.object(utils.time, "sleep"):
                    config = runpy.run_path(str(main_path), run_name="__main__")
                topic_count = len(config["topics"])
                self.assertEqual(request.call_count, topic_count)
                for name in ("README.md", ".github/ISSUE_TEMPLATE.md"):
                    content = Path(name).read_text()
                    self.assertEqual(content.count("## Multimodal Large Language Model\n"), 1)
                    self.assertNotIn("## MLLM\n", content)
                    self.assertEqual(content.count("Multimodal LLM study"), topic_count)
                    self.assertIn("| 2025-01-02 | 2026-09-29 |", content)
                    self.assertIn("| **Title** | **First Submitted** | **Last Updated** | **Comment** |", content)
                    self.assertNotIn("**Date**", content)
                    self.assertNotIn("**Abstract**", content)
                    self.assertNotIn("A study of MLLM systems.", content)
                    self.assertNotIn("Physics study", content)
                self.assertFalse(Path("README.md.bk").exists())
                self.assertFalse(Path(".github/ISSUE_TEMPLATE.md.bk").exists())
                params = parse_qs(urlparse(request.call_args.args[0].full_url).query)
                self.assertIn('(ti:"MLLM" OR abs:"MLLM")', params["search_query"][0])
                self.assertIn('(ti:"Multimodal LLM" OR abs:"Multimodal LLM")',
                              params["search_query"][0])
            finally:
                os.chdir(original_directory)

    def test_rate_limit_respects_retry_after_then_succeeds(self):
        error = HTTPError("https://export.arxiv.org", 429, "Too Many Requests",
                          {"Retry-After": "300"}, io.BytesIO())
        with patch.object(utils, "get_daily_papers_by_keyword", side_effect=[error, [{"Title": "paper"}]]), \
                patch.object(utils.time, "sleep") as sleep:
            self.assertEqual(utils.get_daily_papers_by_keyword_with_retries("MLLM", [], 25),
                             [{"Title": "paper"}])
        sleep.assert_called_once_with(300)

    def test_retry_after_http_date_and_invalid_values(self):
        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        delay = utils.retry_after_seconds(format_datetime(future, usegmt=True))
        self.assertGreater(delay, 598)
        self.assertLessEqual(delay, 600)
        for value in (None, "invalid", "-10"):
            self.assertEqual(utils.retry_after_seconds(value), 0)

    def test_transient_errors_and_empty_result_back_off(self):
        errors = [URLError("connection reset"), TimeoutError("timeout"),
                  HTTPError("https://export.arxiv.org", 503, "Unavailable", {}, io.BytesIO()), []]
        with patch.object(utils, "get_daily_papers_by_keyword", side_effect=errors) as query, \
                patch.object(utils.time, "sleep") as sleep:
            self.assertIsNone(utils.get_daily_papers_by_keyword_with_retries("MLLM", [], 25))
        self.assertEqual(query.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60, 120])

    def test_persistent_rate_limit_stops_without_final_sleep(self):
        error = HTTPError("https://export.arxiv.org", 429, "Too Many Requests", {}, io.BytesIO())
        with patch.object(utils, "get_daily_papers_by_keyword", side_effect=error) as query, \
                patch.object(utils.time, "sleep") as sleep:
            self.assertIsNone(utils.get_daily_papers_by_keyword_with_retries("MLLM", [], 25, retries=3))
        self.assertEqual(query.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60])

    def test_non_retryable_http_error_fails_immediately(self):
        error = HTTPError("https://export.arxiv.org", 400, "Bad Request", {}, io.BytesIO())
        with patch.object(utils, "get_daily_papers_by_keyword", side_effect=error) as query, \
                patch.object(utils.time, "sleep") as sleep, self.assertRaises(HTTPError):
            utils.get_daily_papers_by_keyword_with_retries("MLLM", [], 25)
        query.assert_called_once()
        sleep.assert_not_called()

    def test_main_restores_files_after_exhaustion_or_unexpected_error(self):
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        original_directory = Path.cwd()
        for failure in (None, ValueError("Invalid response")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                try:
                    os.chdir(directory)
                    originals = {"README.md": "Last update: 2026-01-01\n",
                                 ".github/ISSUE_TEMPLATE.md": "Old issue\n"}
                    Path(".github").mkdir()
                    for name, content in originals.items():
                        Path(name).write_text(content)
                    paper = {"Title": "paper", "Link": "https://arxiv.org",
                             "Submitted": "2025-01-02", "Updated": "2026-09-29", "Comment": ""}
                    with patch.object(utils, "get_daily_papers_by_keyword_with_retries",
                                      side_effect=[[paper], failure]), \
                            patch.object(utils.time, "sleep"), self.assertRaises((RuntimeError, ValueError)):
                        runpy.run_path(str(main_path), run_name="__main__")
                    for name, content in originals.items():
                        self.assertEqual(Path(name).read_text(), content)
                        self.assertFalse(Path(name + ".bk").exists())
                finally:
                    os.chdir(original_directory)


if __name__ == "__main__":
    unittest.main()
