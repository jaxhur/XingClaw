from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai.providers._common import to_openai_messages
from ai.types import Context, TextContent, UserMessage


class AiProviderCommonTests(unittest.TestCase):
    def test_openai_messages_include_system_prompt_first(self) -> None:
        context = Context(
            system_prompt="You are XingClaw's quickstart assistant.",
            messages=[UserMessage(content=[TextContent(text="hello")])],
        )

        messages = to_openai_messages(context)

        self.assertEqual(
            messages[0],
            {"role": "system", "content": "You are XingClaw's quickstart assistant."},
        )
        self.assertEqual(messages[1]["role"], "user")


if __name__ == "__main__":
    unittest.main()
