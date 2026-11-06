import unittest

import support

from llm import _content_text


class LLMResponseTests(unittest.TestCase):
    def test_content_text_accepts_string_content(self):
        self.assertEqual(_content_text("  A short lesson.  "), "A short lesson.")

    def test_content_text_accepts_reasoning_content_parts(self):
        self.assertEqual(
            _content_text([{"type": "output_text", "text": "First lesson. "},
                           {"type": "output_text", "text": "Second lesson."}]),
            "First lesson. Second lesson.",
        )

    def test_content_text_rejects_non_text_content(self):
        self.assertEqual(_content_text(None), "")
        self.assertEqual(_content_text([{"type": "reasoning"}]), "")
