from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sugestatorium_flask.store import (
    initialize_storage,
    parse_csv_rows,
    read_prompt_file,
)


class StoreTests(unittest.TestCase):
    def test_parse_csv_rows(self) -> None:
        raw = (
            b'"pk","sk","currentImplementationCode","currentImplementationDescription","groupedIssuesId","gsi1pk","gsi1sk","impactOnUsers","recommendedFixCode","recommendedFixDescription","reportId","ruleId","status","tenantId","whyThisFails"\n'
            b'"a","b","<div></div>","desc","g","p","s","impact","<main></main>","fix","r","rule-id","COMPLETED","tenant","why"\n'
        )
        rows = parse_csv_rows(raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ruleId"], "rule-id")

    def test_read_prompt_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text(
                "---\nid: sample\nname: Sample Prompt\nmodel: gpt-4.1\ntemperature: 0.2\ncreatedAt: 2026-04-12\nnotes: Demo\n---\n\nPrompt body\n",
                encoding="utf-8",
            )
            prompt = read_prompt_file(prompt_path)
            self.assertEqual(prompt["id"], "sample")
            self.assertEqual(prompt["content"], "Prompt body")

    def test_initialize_storage_creates_sqlite_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "prompts").mkdir()
            initialize_storage(root)
            self.assertTrue((root / "storage" / "imports").exists())
            self.assertTrue((root / "storage" / "sugestatorium.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
