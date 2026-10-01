import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

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

    def test_one_encoded_request_per_topic_and_first_submission_date(self):
        keywords = ["Multimodal Large Language Model", "MLLM", "Multimodal LLM"]
        with patch.object(utils.urllib.request, "urlopen",
                          return_value=Mock(read=Mock(return_value=FEED))) as request:
            papers = utils.get_daily_papers_by_keyword(
                keywords, ["Title", "Link", "Date"], 20)
        request.assert_called_once()
        params = parse_qs(urlparse(request.call_args.args[0]).query)
        self.assertEqual(params["search_query"], [utils.build_arxiv_query(keywords)])
        self.assertEqual(params["max_results"], ["20"])
        self.assertEqual(params["sortBy"], ["lastUpdatedDate"])
        self.assertEqual(params["sortOrder"], ["descending"])
        self.assertEqual(len(papers), 1)  # The physics-only paper is filtered out.
        self.assertEqual(papers[0]["Date"], "2025-01-02T12:00:00Z")

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
                    runpy.run_path(str(main_path), run_name="__main__")
                self.assertEqual(request.call_count, 4)
                for name in ("README.md", ".github/ISSUE_TEMPLATE.md"):
                    content = Path(name).read_text()
                    self.assertEqual(content.count("## Multimodal Large Language Model\n"), 1)
                    self.assertNotIn("## MLLM\n", content)
                    self.assertEqual(content.count("Multimodal LLM study"), 4)
                    self.assertIn("2025-01-02", content)
                    self.assertNotIn("Physics study", content)
                self.assertIn("**Abstract**", Path("README.md").read_text())
                self.assertNotIn("**Abstract**", Path(".github/ISSUE_TEMPLATE.md").read_text())
                self.assertFalse(Path("README.md.bk").exists())
                self.assertFalse(Path(".github/ISSUE_TEMPLATE.md.bk").exists())
                params = parse_qs(urlparse(request.call_args.args[0]).query)
                self.assertIn('(ti:"MLLM" OR abs:"MLLM")', params["search_query"][0])
                self.assertIn('(ti:"Multimodal LLM" OR abs:"Multimodal LLM")',
                              params["search_query"][0])
            finally:
                os.chdir(original_directory)


if __name__ == "__main__":
    unittest.main()
