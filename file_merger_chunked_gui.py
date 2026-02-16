#!/usr/bin/env python3
"""
Chunked File Merger with GUI (drag-and-drop support)

Merges files into multiple output chunks, each staying below a configurable
word limit (default 10,000). Word counting is strict: len(text.split()) on
the entire chunk including headers and footers.

Rules:
- A file is NEVER split across two output chunks.
- If adding a file would push the current chunk over the word limit,
  the current chunk is finalized and the file goes into the next chunk.
- If a single file (with its header + footer) exceeds the limit on its own,
  it gets its own dedicated chunk (unavoidable).
- Output files are named: <base>_001.txt, <base>_002.txt, etc.

Features:
- Drag & drop files (if tkinterdnd2 is installed) or use "Add Files" button.
- Reorder files with Up/Down buttons.
- Remove selected files from the list.
- Configurable word limit via spinbox in the GUI.
- Between each file a header is inserted with:
    - Filename, extension, full path, size (bytes), last-modified timestamp, SHA-256

How to run:
    pip install tkinterdnd2   (optional, for drag & drop)
    python file_merger_chunked_gui.py

This program reads input files as UTF-8 text for word counting purposes.
"""

import os
import hashlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from typing import Optional
import traceback

# Try to import tkinterdnd2 for drag & drop; fall back gracefully if not present.
USE_TKINTERDND: bool = False
try:
    import tkinterdnd2
    USE_TKINTERDND = True
except ImportError:
    USE_TKINTERDND = False


DEFAULT_WORD_LIMIT: int = 10_000

HEADER_TEMPLATE: str = (
    "--- FILE START ---\n"
    "Name: {name}\n"
    "Path: {path}\n"
    "Extension: {ext}\n"
    "Size: {size} bytes\n"
    "Modified: {mtime}\n"
    "SHA256: {sha256}\n"
    "--- CONTENT START ---\n"
)
FOOTER: str = "\n--- FILE END ---\n\n"


def count_words(text: str) -> int:
    """
    Counts words using the strictest possible definition:
    split on whitespace, count resulting tokens. Every whitespace-delimited
    token is one word — no exceptions.

    Args:
        text: input string to count words in.

    Returns:
        Number of whitespace-delimited tokens.
    """
    return len(text.split())


def build_header(path: str) -> str:
    """
    Builds the metadata header for a file entry.

    Args:
        path: absolute path to the source file.

    Returns:
        Formatted header string with file metadata.
    """
    try:
        name: str = os.path.basename(path)
        ext: str = os.path.splitext(name)[1]
        size: int = os.path.getsize(path)
        mtime: str = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
        sha: str = sha256_file(path)
        return HEADER_TEMPLATE.format(
            name=name,
            path=path,
            ext=ext or "<no ext>",
            size=size,
            mtime=mtime,
            sha256=sha,
        )
    except OSError as e:
        # File-system related failures (missing file, permission denied, ...)
        # are handled here; we still return a usable header so the merge can
        # continue instead of crashing.
        return (
            f"--- FILE START ---\n"
            f"Name: {os.path.basename(path)}\n"
            f"Error building header: {e}\n"
            f"--- CONTENT START ---\n"
        )


def sha256_file(path: str) -> str:
    """
    Computes SHA-256 hex digest of a file.

    Args:
        path: path to the file.

    Returns:
        Hex digest string, or '<unreadable-file>' on failure.
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "<unreadable-file>"


def read_file_text(path: str) -> str:
    """
    Reads a file as UTF-8 text, falling back to latin-1 on decode errors.

    Args:
        path: path to the file.

    Returns:
        File contents as string.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="latin-1") as f:
            return f.read()


def build_file_entry(path: str) -> str:
    """
    Builds the complete text entry for a single file: header + content + footer.

    Args:
        path: absolute path to the source file.

    Returns:
        Complete entry string ready to be written into a chunk.
    """
    header: str = build_header(path)
    content: str = read_file_text(path)
    return header + content + FOOTER


def merge_chunked(
    file_list: list[str],
    output_base: str,
    word_limit: int = DEFAULT_WORD_LIMIT,
    progress_callback: Optional[callable] = None,
) -> list[str]:
    """
    Merges files into word-limited chunks.

    Each chunk stays at or below word_limit words (header + content + footer
    all included in the count). Files are never split across chunks.

    Args:
        file_list: ordered list of absolute file paths to merge.
        output_base: base path for output files (e.g. "output" produces
                     output_001.txt, output_002.txt, ...).
        word_limit: maximum words per output chunk.
        progress_callback: optional function(current_index, total, filename)
                          called after processing each file.

    Returns:
        List of output file paths that were created.
    """
    # Strip extension from base so we can append _001.txt etc.
    base_root, _ = os.path.splitext(output_base)

    chunks: list[list[str]] = []  # each element is a list of entry strings
    chunk_word_counts: list[int] = []  # running word count per chunk

    total: int = len(file_list)

    for i, path in enumerate(file_list):
        if progress_callback:
            progress_callback(i + 1, total, os.path.basename(path))

        entry: str = build_file_entry(path)
        entry_words: int = count_words(entry)

        # Try to fit into the current chunk
        if chunks and (chunk_word_counts[-1] + entry_words) <= word_limit:
            chunks[-1].append(entry)
            chunk_word_counts[-1] += entry_words
        else:
            # Start a new chunk with this file
            chunks.append([entry])
            chunk_word_counts.append(entry_words)

    # Write chunks to disk
    output_paths: list[str] = []
    for idx, entries in enumerate(chunks, start=1):
        chunk_path: str = f"{base_root}_{idx:03d}.txt"
        with open(chunk_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(entry)
        output_paths.append(chunk_path)

    return output_paths


class ChunkedFileMergerApp:
    """GUI application for chunked file merging with word-limit control."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Chunked File Merger")
        root.geometry("820x480")

        self.file_list: list[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        frm = ttk.Frame(self.root, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        # Left panel: buttons + listbox
        left = ttk.Frame(frm)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Button(btn_frame, text="Add Files...", command=self.add_files).pack(
            side=tk.LEFT
        )
        ttk.Button(btn_frame, text="Clear All", command=self.clear_all).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(btn_frame, text="Choose Output...", command=self.choose_output).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(btn_frame, text="Merge Now", command=self.merge_now).pack(
            side=tk.RIGHT
        )

        # Listbox for files
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=sb.set)

        # Right panel: controls
        right = ttk.Frame(frm, width=180)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Button(right, text="Move Up", command=lambda: self.move_selected(-1)).pack(
            fill=tk.X, pady=(6, 2), padx=6
        )
        ttk.Button(
            right, text="Move Down", command=lambda: self.move_selected(1)
        ).pack(fill=tk.X, pady=2, padx=6)
        ttk.Button(right, text="Remove Selected", command=self.remove_selected).pack(
            fill=tk.X, pady=2, padx=6
        )
        ttk.Button(right, text="Preview Header", command=self.preview_header).pack(
            fill=tk.X, pady=12, padx=6
        )

        # Word limit control
        limit_frame = ttk.LabelFrame(right, text="Word Limit", padding=6)
        limit_frame.pack(fill=tk.X, padx=6, pady=(6, 0))

        self.word_limit_var = tk.IntVar(value=DEFAULT_WORD_LIMIT)
        self.limit_spin = ttk.Spinbox(
            limit_frame,
            from_=100,
            to=1_000_000,
            increment=500,
            textvariable=self.word_limit_var,
            width=10,
        )
        self.limit_spin.pack(fill=tk.X)

        ttk.Label(limit_frame, text="words per chunk", font=("", 8)).pack(anchor=tk.W)

        # Output path display
        self.output_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.output_var, wraplength=160).pack(
            fill=tk.X, padx=6, pady=(6, 0)
        )

        # Status bar
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status, relief=tk.SUNKEN, anchor=tk.W).pack(
            fill=tk.X, side=tk.BOTTOM
        )

        # Drag-and-drop
        if USE_TKINTERDND:
            self._enable_dnd()
        else:
            self.status.set(
                "Drag & drop: tkinterdnd2 not installed. Use 'Add Files...' "
                "or pip install tkinterdnd2 to enable DnD."
            )

    def _enable_dnd(self) -> None:
        try:
            self.listbox.drop_target_register("DND_Files")
            self.listbox.dnd_bind("<<Drop>>", self._on_drop)
            self.status.set("Drop files into the list to add them.")
        except (tk.TclError, AttributeError):
            self.status.set("Drag & drop available but failed to register target.")

    def _on_drop(self, event) -> None:
        try:
            files = self.root.tk.splitlist(event.data)
        except tk.TclError:
            files = event.data.split()
        self._add_paths([f for f in files if f])

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Select files to merge")
        if paths:
            self._add_paths(paths)

    def _add_paths(self, paths: list[str]) -> None:
        added: int = 0
        for p in paths:
            p = os.path.abspath(p)
            if p not in self.file_list and os.path.isfile(p):
                self.file_list.append(p)
                self.listbox.insert(tk.END, os.path.basename(p))
                added += 1
        self.status.set(f"Added {added} file(s). Total: {len(self.file_list)}")

    def clear_all(self) -> None:
        self.file_list.clear()
        self.listbox.delete(0, tk.END)
        self.status.set("Cleared all files.")

    def remove_selected(self) -> None:
        sel = list(self.listbox.curselection())
        if not sel:
            return
        for i in reversed(sel):
            del self.file_list[i]
            self.listbox.delete(i)
        self.status.set(f"Removed {len(sel)} selected.")

    def move_selected(self, delta: int) -> None:
        sel = list(self.listbox.curselection())
        if not sel:
            return
        first: int = sel[0]
        new_index: int = first + delta
        if new_index < 0 or new_index >= len(self.file_list):
            return
        for i in sel:
            j = i + delta
            if 0 <= j < len(self.file_list):
                self.file_list[i], self.file_list[j] = (
                    self.file_list[j],
                    self.file_list[i],
                )
        self._rebuild_listbox()
        self.listbox.selection_clear(0, tk.END)
        for i in [idx + delta for idx in sel]:
            if 0 <= i < self.listbox.size():
                self.listbox.selection_set(i)
        self.status.set("Moved selection.")

    def _rebuild_listbox(self) -> None:
        self.listbox.delete(0, tk.END)
        for p in self.file_list:
            self.listbox.insert(tk.END, os.path.basename(p))

    def choose_output(self) -> None:
        out = filedialog.asksaveasfilename(
            title="Save merged chunks as (base name)",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if out:
            self.output_var.set(out)
            self.status.set(f"Output base: {out}")

    def preview_header(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo(
                "Preview header",
                "Select a file in the list to preview its merged header.",
            )
            return
        idx: int = sel[0]
        path: str = self.file_list[idx]
        hdr: str = build_header(path)
        words: int = count_words(hdr)

        top = tk.Toplevel(self.root)
        top.title(f"Header Preview: {os.path.basename(path)} ({words} words)")
        txt = tk.Text(top, wrap=tk.NONE)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert("1.0", hdr)
        txt.config(state=tk.DISABLED)

    def merge_now(self) -> None:
        if not self.file_list:
            messagebox.showwarning("No files", "No files added to merge.")
            return

        out: str = self.output_var.get()
        if not out:
            out = filedialog.asksaveasfilename(
                title="Save merged chunks as (base name)",
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            )
            if not out:
                return
            self.output_var.set(out)

        word_limit: int = self.word_limit_var.get()
        if word_limit < 100:
            messagebox.showwarning(
                "Invalid limit", "Word limit must be at least 100."
            )
            return

        def on_progress(current: int, total: int, name: str) -> None:
            self.status.set(f"Processing {current}/{total}: {name}")
            self.root.update_idletasks()

        try:
            output_paths: list[str] = merge_chunked(
                file_list=self.file_list,
                output_base=out,
                word_limit=word_limit,
                progress_callback=on_progress,
            )

            # Build summary
            summary_lines: list[str] = [
                f"Created {len(output_paths)} chunk(s):\n"
            ]
            for p in output_paths:
                size: int = os.path.getsize(p)
                with open(p, "r", encoding="utf-8") as f:
                    words: int = count_words(f.read())
                summary_lines.append(
                    f"  {os.path.basename(p)}: {words} words, {size} bytes"
                )

            summary: str = "\n".join(summary_lines)
            self.status.set(f"Merge complete: {len(output_paths)} chunk(s) created")
            messagebox.showinfo("Success", summary)

        except (OSError, UnicodeDecodeError) as e:
            messagebox.showerror("Error", f"Failed to merge files:\n{e}")
            self.status.set("Error during merge.")
        except (RuntimeError, ValueError, TypeError) as e:
            # Handle expected runtime / data issues without catching all exceptions.
            # Log traceback to stderr and show a concise message to the user.
            traceback.print_exc()
            messagebox.showerror(
                "Error",
                f"An error occurred while merging:\n{e}\n\nSee console for details.",
            )
            self.status.set("Error during merge.")


def main() -> None:
    if USE_TKINTERDND:
        try:
            root = tkinterdnd2.Tk()
        except (AttributeError, RuntimeError, tk.TclError):
            root = tk.Tk()
    else:
        root = tk.Tk()

    ChunkedFileMergerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
