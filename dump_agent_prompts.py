from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol, cast


SourceKind = Literal['snapshot', 'source-template', 'alias']


class OutputBuffer(Protocol):
    """Minimal byte-oriented output buffer protocol.

    ✨ PURE INTERFACE ✨
    """

    def write(self, data: bytes) -> int: ...
    def flush(self) -> None: ...


class OutputStream(Protocol):
    """Minimal text stream protocol used by ``write_output``.

    ✨ PURE INTERFACE ✨
    """

    buffer: OutputBuffer | None

    def write(self, text: str) -> int: ...
    def flush(self) -> None: ...
    def isatty(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class BranchDump:
    """Represents one dumped prompt branch.

    ✨ PURE DATA ✨

    Attributes:
        branch_id: Stable identifier for the prompt branch.
        repo_name: Repository that contributes the branch.
        source_kind: Whether the dump comes from a rendered snapshot, a raw
            source template excerpt, or an alias to another dumped branch.
        source_path: File that produced this dump.
        prompt: Raw dumped prompt body or raw JSX template excerpt.
        reminder: Optional reminder prompt/body associated with the branch.
        alias_of: Optional target branch when this branch reuses another dump.
        note: Extra context about why the branch exists or how it was derived.
    """

    branch_id: str
    repo_name: str
    source_kind: SourceKind
    source_path: Path
    prompt: str
    reminder: str | None = None
    alias_of: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SourceBranchSpec:
    """Describes a branch that must be dumped from raw source.

    ✨ PURE DATA ✨

    Attributes:
        branch_id: Stable identifier to expose in the report.
        repo_name: Repository containing the source file.
        relative_path: File path relative to the workspace root.
        prompt_class_name: Prompt class to extract.
        reminder_class_name: Optional reminder class to extract.
        note: Context for the report.
    """

    branch_id: str
    repo_name: str
    relative_path: str
    prompt_class_name: str
    reminder_class_name: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class AliasBranchSpec:
    """Describes a branch that aliases another dumped branch.

    ✨ PURE DATA ✨
    """

    branch_id: str
    repo_name: str
    relative_path: str
    alias_of: str
    note: str | None = None


WORKSPACE_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
SNAPSHOT_REPO: Final[str] = 'vscode-copilot-chat'
TEST_FAMILIES_PATH: Final[Path] = (
    WORKSPACE_ROOT
    / SNAPSHOT_REPO
    / 'src/extension/prompts/node/agent/test/agentPrompt.spec.tsx'
)
TEST_FAMILIES_BLOCK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'const testFamilies\s*=\s*\[(?P<body>.*?)\];',
    re.DOTALL,
)
STRING_LITERAL_PATTERN: Final[re.Pattern[str]] = re.compile(r"'([^']+)'")
CLASS_START_PATTERN_TEMPLATE: Final[str] = r'class\s+{class_name}\b'

SOURCE_BRANCH_SPECS: Final[tuple[SourceBranchSpec, ...]] = (
    SourceBranchSpec(
        branch_id='alternate-gpt-prompt',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/defaultAgentInstructions.tsx',
        prompt_class_name='AlternateGPTPrompt',
        note='Experiment-gated GPT system prompt override.',
    ),
    SourceBranchSpec(
        branch_id='claude-sonnet-4',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/anthropicPrompts.tsx',
        prompt_class_name='DefaultAnthropicAgentPrompt',
        reminder_class_name='AnthropicReminderInstructions',
        note='Legacy Sonnet 4 Anthropic branch with explicit reminder template.',
    ),
    SourceBranchSpec(
        branch_id='gpt-5.2',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/openai/gpt52Prompt.tsx',
        prompt_class_name='HiddenModelBPrompt',
        reminder_class_name='HiddenModelBReminderInstructions',
        note='Public GPT-5.2 family backed by the gpt52 prompt file.',
    ),
    SourceBranchSpec(
        branch_id='gpt-5.3-codex',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/openai/gpt53CodexPrompt.tsx',
        prompt_class_name='Gpt53CodexPrompt',
        reminder_class_name='Gpt53CodexReminderInstructions',
        note='5.3 Codex branch is source-backed because no snapshot fixture exists.',
    ),
    SourceBranchSpec(
        branch_id='gpt-5.4',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/openai/gpt54Prompt.tsx',
        prompt_class_name='Gpt54Prompt',
        reminder_class_name='Gpt54ReminderInstructions',
        note='Main GPT-5.4 branch.',
    ),
    SourceBranchSpec(
        branch_id='gpt-5.4-concise-exp',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/openai/gpt54ConcisePrompt.tsx',
        prompt_class_name='Gpt54ConcisePromptExp',
        reminder_class_name='Gpt54ConcisePromptExpReminderInstructions',
        note='Experiment-only concise GPT-5.4 branch.',
    ),
    SourceBranchSpec(
        branch_id='gpt-5.4-large-exp',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/openai/gpt54LargePrompt.tsx',
        prompt_class_name='Gpt54LargePromptExp',
        reminder_class_name='Gpt54LargePromptExpReminderInstructions',
        note='Experiment-only large GPT-5.4 branch.',
    ),
    SourceBranchSpec(
        branch_id='hidden-model-b-minimal',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/openai/hiddenModelBPrompt.tsx',
        prompt_class_name='HiddenModelBPrompt',
        note='Hashed internal OpenAI branch with a minimal prompt body.',
    ),
    SourceBranchSpec(
        branch_id='hidden-model-f-gemini',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/geminiPrompts.tsx',
        prompt_class_name='HiddenModelFGeminiAgentPrompt',
        note='Hashed Gemini branch discovered from source only.',
    ),
    SourceBranchSpec(
        branch_id='default-zai-agent',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/zaiPrompts.tsx',
        prompt_class_name='DefaultZaiAgentPrompt',
        note='Z.AI source-only branch.',
    ),
    SourceBranchSpec(
        branch_id='default-minimax-agent',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/minimaxPrompts.tsx',
        prompt_class_name='DefaultMinimaxAgentPrompt',
        note='MiniMax source-only branch.',
    ),
    SourceBranchSpec(
        branch_id='family-h-default',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/familyHPrompts.tsx',
        prompt_class_name='DefaultFamilyHAgentPrompt',
        note='Hidden family-H prompt source.',
    ),
    SourceBranchSpec(
        branch_id='vsc-model-a',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/vscModelPrompts.tsx',
        prompt_class_name='VSCModelPromptA',
        reminder_class_name='VSCModelReminderInstructionsA',
        note='Hashed internal VSC prompt branch A.',
    ),
    SourceBranchSpec(
        branch_id='vsc-model-b',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/vscModelPrompts.tsx',
        prompt_class_name='VSCModelPromptB',
        reminder_class_name='VSCModelReminderInstructions',
        note='Hashed internal VSC prompt branch B.',
    ),
    SourceBranchSpec(
        branch_id='vsc-model-c',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/vscModelPrompts.tsx',
        prompt_class_name='VSCModelPromptC',
        reminder_class_name='VSCModelReminderInstructionsC',
        note='Hashed internal VSC prompt branch C.',
    ),
    SourceBranchSpec(
        branch_id='vsc-model-d',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/vscModelPrompts.tsx',
        prompt_class_name='VSCModelPromptD',
        reminder_class_name='VSCModelReminderInstructionsA',
        note='Hashed internal VSC prompt branch D.',
    ),
)

ALIAS_BRANCH_SPECS: Final[tuple[AliasBranchSpec, ...]] = (
    AliasBranchSpec(
        branch_id='gpt-5.2-codex',
        repo_name='vscode-copilot-chat',
        relative_path='src/extension/prompts/node/agent/openai/gpt51CodexPrompt.tsx',
        alias_of='gpt-5.1-codex',
        note='The gpt-5.2-codex family resolves to the same prompt class as gpt-5.1-codex.',
    ),
    AliasBranchSpec(
        branch_id='hidden-model-g',
        repo_name='vscode',
        relative_path='extensions/copilot/src/extension/prompts/node/agent/anthropicPrompts.tsx',
        alias_of='claude-opus-4.6',
        note='Repo-specific hidden Anthropic resolver in vscode; aliases Claude46OpusPrompt.',
    ),
)


def read_text(path: Path) -> str:
    """Reads UTF-8 text from ``path``.

    ✨ PURE FUNCTION ✨ from the caller's point of view because the file content
    becomes an immutable ``str`` value and no external state is modified.

    Args:
        path: File to read.

    Returns:
        Full decoded text.
    """

    return path.read_text(encoding='utf-8')


def parse_test_families(spec_text: str) -> tuple[str, ...]:
    """Extracts the snapshot-backed family list from the Vitest source.

    ✨ PURE FUNCTION ✨

    Args:
        spec_text: Raw ``agentPrompt.spec.tsx`` source.

    Returns:
        Ordered tuple of family identifiers.

    Raises:
        ValueError: If the ``testFamilies`` block cannot be found.
    """

    match = TEST_FAMILIES_BLOCK_PATTERN.search(spec_text)
    if match is None:
        raise ValueError('Could not locate testFamilies block in agentPrompt.spec.tsx')

    families = tuple(STRING_LITERAL_PATTERN.findall(match.group('body')))
    if not families:
        raise ValueError('testFamilies block was found but no family identifiers were parsed')
    return families


def snapshot_path_for_family(workspace_root: Path, family: str) -> Path:
    """Computes the simple-case snapshot path for ``family``.

    ✨ PURE FUNCTION ✨
    """

    return (
        workspace_root
        / SNAPSHOT_REPO
        / 'src/extension/prompts/node/agent/test/__snapshots__'
        / f'agentPrompts-{family}'
        / 'simple_case.spec.snap'
    )


def relative_to_workspace(workspace_root: Path, path: Path) -> Path:
    """Returns ``path`` relative to ``workspace_root`` when possible.

    ✨ PURE FUNCTION ✨
    """

    try:
        return path.relative_to(workspace_root)
    except ValueError:
        return path


def build_snapshot_branch_dumps(workspace_root: Path) -> list[BranchDump]:
    """Builds rendered prompt dumps from existing snapshot fixtures.

    ⚠️ IMPURE FUNCTION ⚠️ because it reads repository files.

    Args:
        workspace_root: Workspace root containing the repositories.

    Returns:
        Snapshot-backed prompt dumps in the same order as the Vitest list.
    """

    spec_text = read_text(workspace_root / SNAPSHOT_REPO / 'src/extension/prompts/node/agent/test/agentPrompt.spec.tsx')
    families = parse_test_families(spec_text)

    return [
        BranchDump(
            branch_id=family,
            repo_name=SNAPSHOT_REPO,
            source_kind='snapshot',
            source_path=relative_to_workspace(workspace_root, snapshot_path_for_family(workspace_root, family)),
            prompt=read_text(snapshot_path_for_family(workspace_root, family)).strip(),
            note='Rendered simple_case snapshot from the prompt test corpus.',
        )
        for family in families
    ]


def find_class_block(source_text: str, class_name: str) -> str:
    """Extracts the full TypeScript class block for ``class_name``.

    ✨ PURE FUNCTION ✨

    Args:
        source_text: TypeScript/TSX file contents.
        class_name: Class identifier to locate.

    Returns:
        Full class block including braces.

    Raises:
        ValueError: If the class or its closing brace cannot be found.
    """

    class_pattern = re.compile(CLASS_START_PATTERN_TEMPLATE.format(class_name=re.escape(class_name)))
    match = class_pattern.search(source_text)
    if match is None:
        raise ValueError(f'Could not find class {class_name}')

    brace_index = source_text.find('{', match.end())
    if brace_index == -1:
        raise ValueError(f'Could not find opening brace for class {class_name}')

    depth = 0
    for index in range(brace_index, len(source_text)):
        character = source_text[index]
        if character == '{':
            depth += 1
        elif character == '}':
            depth -= 1
            if depth == 0:
                return source_text[match.start() : index + 1]

    raise ValueError(f'Could not find closing brace for class {class_name}')


def extract_instruction_message(class_block: str) -> str:
    """Extracts the raw JSX returned by ``InstructionMessage`` when present.

    ✨ PURE FUNCTION ✨

    Args:
        class_block: Full class source block.

    Returns:
        Raw JSX excerpt when ``InstructionMessage`` exists, otherwise the full
        class block stripped of surrounding whitespace.
    """

    start_token = '<InstructionMessage>'
    end_token = '</InstructionMessage>'
    start_index = class_block.find(start_token)
    if start_index == -1:
        return class_block.strip()

    end_index = class_block.find(end_token, start_index)
    if end_index == -1:
        return class_block[start_index:].strip()

    return class_block[start_index : end_index + len(end_token)].strip()


def extract_prompt_template(path: Path, class_name: str) -> str:
    """Loads ``path`` and extracts the raw template for ``class_name``.

    ⚠️ IMPURE FUNCTION ⚠️ because it reads repository source files.
    """

    return extract_instruction_message(find_class_block(read_text(path), class_name))


def build_source_branch_dumps(workspace_root: Path) -> list[BranchDump]:
    """Builds best-effort source-template dumps for unsnapshotted branches.

    ⚠️ IMPURE FUNCTION ⚠️ because it reads repository source files.
    """

    dumps: list[BranchDump] = []
    for spec in SOURCE_BRANCH_SPECS:
        source_path = workspace_root / spec.repo_name / spec.relative_path
        reminder = (
            extract_prompt_template(source_path, spec.reminder_class_name)
            if spec.reminder_class_name is not None
            else None
        )
        dumps.append(
            BranchDump(
                branch_id=spec.branch_id,
                repo_name=spec.repo_name,
                source_kind='source-template',
                source_path=relative_to_workspace(workspace_root, source_path),
                prompt=extract_prompt_template(source_path, spec.prompt_class_name),
                reminder=reminder,
                note=spec.note,
            )
        )
    return dumps


def build_alias_branch_dumps(
    workspace_root: Path,
    existing_dumps: dict[str, BranchDump],
) -> list[BranchDump]:
    """Builds alias branches that intentionally reuse another branch dump.

    ✨ PURE FUNCTION ✨ with respect to prompt shaping; it only rewraps existing
    immutable branch values and does not mutate anything.

    Args:
        workspace_root: Workspace root used to relativize source paths.
        existing_dumps: Previously built branches keyed by ``branch_id``.

    Returns:
        Alias branch dumps.

    Raises:
        KeyError: If an alias points at a branch that has not been built yet.
    """

    aliases: list[BranchDump] = []
    for spec in ALIAS_BRANCH_SPECS:
        target_branch = existing_dumps[spec.alias_of]
        aliases.append(
            BranchDump(
                branch_id=spec.branch_id,
                repo_name=spec.repo_name,
                source_kind='alias',
                source_path=relative_to_workspace(
                    workspace_root,
                    workspace_root / spec.repo_name / spec.relative_path,
                ),
                prompt=target_branch.prompt,
                reminder=target_branch.reminder,
                alias_of=spec.alias_of,
                note=spec.note,
            )
        )
    return aliases


def build_branch_dumps(workspace_root: Path | None = None) -> list[BranchDump]:
    """Builds the complete branch dump inventory.

    ⚠️ IMPURE FUNCTION ⚠️ because it reads repository files.

    Args:
        workspace_root: Optional explicit workspace root. Defaults to the
            parent of the ``Misc`` folder containing this script.

    Returns:
        Sorted list of all known branch dumps.
    """

    resolved_root = workspace_root or WORKSPACE_ROOT
    snapshot_dumps = build_snapshot_branch_dumps(resolved_root)
    source_dumps = build_source_branch_dumps(resolved_root)

    indexed_dumps = {branch.branch_id: branch for branch in (*snapshot_dumps, *source_dumps)}
    alias_dumps = build_alias_branch_dumps(resolved_root, indexed_dumps)

    all_dumps = [*snapshot_dumps, *source_dumps, *alias_dumps]
    return sorted(all_dumps, key=lambda branch: (branch.branch_id, branch.source_kind, branch.repo_name))


def render_branch_dump(branch: BranchDump) -> str:
    """Renders one branch dump as a plain-text report section.

    ✨ PURE FUNCTION ✨
    """

    header_lines = [
        f'=== BRANCH {branch.branch_id} ===',
        f'repo: {branch.repo_name}',
        f'source-kind: {branch.source_kind}',
        f'source-path: {branch.source_path.as_posix()}',
    ]

    if branch.alias_of is not None:
        header_lines.append(f'alias-of: {branch.alias_of}')
    if branch.note is not None:
        header_lines.append(f'note: {branch.note}')

    match branch.source_kind:
        case 'snapshot':
            prompt_label = 'rendered-prompt'
        case 'source-template':
            prompt_label = 'source-template'
        case 'alias':
            prompt_label = 'aliased-prompt'
        case _:
            prompt_label = 'prompt'

    body_lines = [*header_lines, f'--- {prompt_label} ---', branch.prompt.strip()]
    if branch.reminder:
        body_lines.extend(['--- reminder-template ---', branch.reminder.strip()])
    return '\n'.join(body_lines).rstrip()


def render_branch_report(branch_dumps: list[BranchDump]) -> str:
    """Renders all branch dumps into one concatenated report.

    ✨ PURE FUNCTION ✨
    """

    return '\n\n'.join(render_branch_dump(branch) for branch in branch_dumps)


def write_output(text: str, stream: object) -> None:
    """Writes ``text`` to ``stream`` while handling redirected Unicode safely.

    ⚠️ IMPURE FUNCTION ⚠️ because it writes to an external stream.

    When stdout is redirected on Windows, Python may still wrap the file in a
    legacy locale encoding like ``cp1252``. The report contains characters such
    as ``→``, so writing via the text wrapper can explode with
    ``UnicodeEncodeError``. For redirected streams that expose a byte buffer, we
    bypass the text wrapper and emit UTF-8 bytes directly. TTY-like streams keep
    the normal text path so interactive output still behaves naturally.

    Args:
        text: Full report text to emit.
        stream: Destination text stream.
    """

    is_tty = False
    isatty_method = getattr(stream, 'isatty', None)
    if callable(isatty_method):
        try:
            is_tty = bool(isatty_method())
        except (OSError, ValueError):
            is_tty = False

    buffer = getattr(stream, 'buffer', None)
    if (
        not is_tty
        and buffer is not None
        and hasattr(buffer, 'write')
        and hasattr(buffer, 'flush')
    ):
        output_buffer = cast(OutputBuffer, buffer)
        output_buffer.write(text.encode('utf-8'))
        if not text.endswith('\n'):
            output_buffer.write(b'\n')
        output_buffer.flush()
        return

    if not all(hasattr(stream, attribute) for attribute in ('write', 'flush', 'isatty')):
        raise TypeError('stream must provide write(), flush(), and isatty() methods')

    output_stream = cast(OutputStream, stream)
    output_stream.write(text)
    if not text.endswith('\n'):
        output_stream.write('\n')
    output_stream.flush()


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parses CLI arguments.

    ✨ PURE FUNCTION ✨
    """

    parser = argparse.ArgumentParser(
        description='Dump raw VS Code Copilot agent prompts for all known branches.',
    )
    parser.add_argument(
        '--workspace-root',
        type=Path,
        default=WORKSPACE_ROOT,
        help='Workspace root that contains vscode-copilot-chat, vscode, and Misc.',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    ⚠️ IMPURE FUNCTION ⚠️ because it performs file I/O and writes to stdout.

    Args:
        argv: Optional argument vector excluding the executable name.

    Returns:
        Process exit status.
    """

    args = parse_args(argv or sys.argv[1:])
    branch_dumps = build_branch_dumps(args.workspace_root.resolve())
    write_output(render_branch_report(branch_dumps), sys.stdout)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())