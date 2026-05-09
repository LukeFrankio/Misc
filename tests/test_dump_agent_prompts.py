from __future__ import annotations

import io
import unittest
from pathlib import Path

import dump_agent_prompts


class FakeRedirectedStream:
    def __init__(self, encoding: str = 'cp1252') -> None:
        self.encoding = encoding
        self.buffer = io.BytesIO()

    def write(self, text: str) -> int:
        encoded = text.encode(self.encoding)
        return self.buffer.write(encoded)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


class FakeTtyStream:
    def __init__(self) -> None:
        self.chunks: list[str] = []
        self.buffer = None

    def write(self, text: str) -> int:
        self.chunks.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return True


class DumpAgentPromptsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_root = Path(__file__).resolve().parents[2]

    def test_build_branch_dumps_includes_snapshot_backed_prompt(self) -> None:
        dumps = dump_agent_prompts.build_branch_dumps(self.workspace_root)

        gpt5_dump = next(branch for branch in dumps if branch.branch_id == 'gpt-5')

        self.assertEqual(gpt5_dump.source_kind, 'snapshot')
        self.assertIn('Your name is GitHub Copilot.', gpt5_dump.prompt)

    def test_build_branch_dumps_includes_source_only_branch(self) -> None:
        dumps = dump_agent_prompts.build_branch_dumps(self.workspace_root)

        alternate_dump = next(
            branch for branch in dumps if branch.branch_id == 'alternate-gpt-prompt'
        )

        self.assertEqual(alternate_dump.source_kind, 'source-template')
        self.assertIn('structuredWorkflow', alternate_dump.prompt)

    def test_build_branch_dumps_includes_hidden_alias_branch(self) -> None:
        dumps = dump_agent_prompts.build_branch_dumps(self.workspace_root)

        hidden_model_g_dump = next(
            branch for branch in dumps if branch.branch_id == 'hidden-model-g'
        )

        self.assertEqual(hidden_model_g_dump.source_kind, 'alias')
        self.assertEqual(hidden_model_g_dump.alias_of, 'claude-opus-4.6')
        self.assertIn('Gather sufficient context to act confidently', hidden_model_g_dump.prompt)

    def test_write_output_uses_utf8_bytes_when_redirected(self) -> None:
        stream = FakeRedirectedStream()

        dump_agent_prompts.write_output('hello → world', stream)

        self.assertEqual(stream.buffer.getvalue(), 'hello → world\n'.encode('utf-8'))

    def test_write_output_preserves_text_for_tty_streams(self) -> None:
        stream = FakeTtyStream()

        dump_agent_prompts.write_output('hello → world', stream)

        self.assertEqual(''.join(stream.chunks), 'hello → world\n')


if __name__ == '__main__':
    unittest.main()