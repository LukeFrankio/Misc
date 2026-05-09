import unittest

from file_merger_reorder import move_selected_items


class MoveSelectedItemsTests(unittest.TestCase):
    def test_moves_contiguous_block_down_without_scrambling(self) -> None:
        items, selection = move_selected_items(["a", "b", "c", "d", "e"], [1, 2], 1)

        self.assertEqual(items, ["a", "d", "b", "c", "e"])
        self.assertEqual(selection, (2, 3))

    def test_moves_non_contiguous_selection_up_preserving_relative_order(self) -> None:
        items, selection = move_selected_items(["a", "b", "c", "d", "e"], [1, 3], -1)

        self.assertEqual(items, ["b", "a", "d", "c", "e"])
        self.assertEqual(selection, (0, 2))

    def test_keeps_selection_in_place_at_boundary(self) -> None:
        items, selection = move_selected_items(["a", "b", "c"], [0], -1)

        self.assertEqual(items, ["a", "b", "c"])
        self.assertEqual(selection, (0,))


if __name__ == "__main__":
    unittest.main()
