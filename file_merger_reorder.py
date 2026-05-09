"""Helpers for moving selected file entries within a list.

This module centralizes the selection-reordering logic used by both file merger
GUIs. The goal is to move selected items as a stable group so multiple selected
files keep their relative order instead of getting scrambled by sequential
swaps.
"""

from collections.abc import Sequence


def _selection_blocks(selected_indices: Sequence[int]) -> list[tuple[int, int]]:
    """Returns contiguous index blocks from an ordered selection.

    ✨ PURE FUNCTION ✨

    Args:
        selected_indices: Sorted selection indices.

    Returns:
        A list of ``(start, end)`` tuples for contiguous blocks.
    """

    if not selected_indices:
        return []

    blocks: list[tuple[int, int]] = []
    start = selected_indices[0]
    end = start

    for index in selected_indices[1:]:
        if index == end + 1:
            end = index
            continue
        blocks.append((start, end))
        start = index
        end = index

    blocks.append((start, end))
    return blocks


def move_selected_items(
    items: Sequence[str],
    selected_indices: Sequence[int],
    delta: int,
) -> tuple[list[str], tuple[int, ...]]:
    """Moves selected items by one position while preserving relative order.

    ✨ PURE FUNCTION ✨

    Args:
        items: Current ordered items.
        selected_indices: Selected indices within ``items``.
        delta: Direction to move: ``-1`` for up or ``1`` for down.

    Returns:
        Tuple of ``(new_items, new_selection)``.

    Raises:
        ValueError: If ``delta`` is not ``-1`` or ``1``.
    """

    if delta not in (-1, 1):
        raise ValueError("delta must be -1 or 1")

    result = list(items)
    item_count = len(result)
    selection = tuple(sorted({index for index in selected_indices if 0 <= index < item_count}))

    if not selection:
        return result, ()

    if delta < 0:
        if selection[0] == 0:
            return result, selection

        for start, end in _selection_blocks(selection):
            preceding_item = result[start - 1]
            block = result[start : end + 1]
            result[start - 1 : end + 1] = block + [preceding_item]

        return result, tuple(index - 1 for index in selection)

    if selection[-1] == item_count - 1:
        return result, selection

    for start, end in reversed(_selection_blocks(selection)):
        following_item = result[end + 1]
        block = result[start : end + 1]
        result[start : end + 2] = [following_item] + block

    return result, tuple(index + 1 for index in selection)