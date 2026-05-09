import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import directory_mapper_gui as directory_mapper


class DirectoryMapperLoopGuardTests(unittest.TestCase):
    def test_scan_directory_skips_revisited_directory_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            child = root / "child"
            child.mkdir()
            (child / "payload.txt").write_text("payload", encoding="utf-8")

            options = directory_mapper.ScanOptions(
                follow_symlinks=True,
                include_hidden=True,
                ignore_globs=(),
            )

            with patch("directory_mapper_gui._directory_identity", return_value=(1, 1), create=True):
                scan = directory_mapper.scan_directory(root, options, largest_files=5)

            self.assertEqual(scan.total_dir_count, 0)
            self.assertEqual(scan.total_file_count, 0)
            self.assertEqual(scan.total_size_bytes, 0)


if __name__ == "__main__":
    unittest.main()
