from __future__ import annotations

import unittest

from storyteller.storage.repositories.project import preview


class PreviewTest(unittest.TestCase):
    def test_markdown_preview_preserves_structure(self) -> None:
        source = "### 本集人物\n\n**沈清妙**：调查门禁日志。\n\n---\n\n## 第一场"

        result = preview(source)

        self.assertEqual(source, result)
        self.assertIn("### 本集人物\n\n**沈清妙**", result)

    def test_long_preview_stops_at_a_line_boundary(self) -> None:
        source = "### 标题\n\n" + "第一段内容。" * 45 + "\n\n## 下一节\n\n不会进入预览"

        result = preview(source, length=120)

        self.assertTrue(result.endswith("\n\n…"))
        self.assertNotIn("下一节", result)


if __name__ == "__main__":
    unittest.main()
