#!/usr/bin/env python3
"""
Simple File Merger with GUI (drag-and-drop support)

Features:
- Drag & drop files into the UI (if tkinterdnd2 is installed) or use "Add Files" button.
- Reorder files with Up/Down buttons.
- Remove selected files from the list.
- Merge into a single output file. Between each file a header is inserted with:
    - Filename, extension, full path, size (bytes), last-modified timestamp, SHA-256
- Minimal dependencies: only standard library + optional `tkinterdnd2` for native drag-and-drop.

How to run:
- Optionally install drag & drop helper: pip install tkinterdnd2
- Run: python file_merger_gui.py

This program treats input files as binary to preserve exact contents and writes a UTF-8 header
between files so merging is robust for different encodings.
"""

import os
import sys
import hashlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

# Try to import tkinterdnd2 for drag & drop; fall back gracefully if not present.
USE_TKINTERDND = False
try:
    import tkinterdnd2
    USE_TKINTERDND = True
except Exception:
    USE_TKINTERDND = False


HEADER_TEMPLATE = (
    "--- FILE START ---\n"
    "Name: {name}\n"
    "Path: {path}\n"
    "Extension: {ext}\n"
    "Size: {size} bytes\n"
    "Modified: {mtime}\n"
    "SHA256: {sha256}\n"
    "--- CONTENT START ---\n"
)
FOOTER = "\n--- FILE END ---\n\n"


class FileMergerApp:
    def __init__(self, root):
        self.root = root
        root.title("File Merger")
        root.geometry("800x420")

        self.file_list = []  # list of absolute paths

        self._build_ui()

    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(frm)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill=tk.X, pady=(0, 6))

        add_btn = ttk.Button(btn_frame, text="Add Files...", command=self.add_files)
        add_btn.pack(side=tk.LEFT)

        clear_btn = ttk.Button(btn_frame, text="Clear All", command=self.clear_all)
        clear_btn.pack(side=tk.LEFT, padx=(6, 0))

        choose_btn = ttk.Button(btn_frame, text="Choose Output...", command=self.choose_output)
        choose_btn.pack(side=tk.LEFT, padx=(6, 0))

        merge_btn = ttk.Button(btn_frame, text="Merge Now", command=self.merge_now)
        merge_btn.pack(side=tk.RIGHT)

        # Listbox for files
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=sb.set)

        # Right-side controls
        right = ttk.Frame(frm, width=160)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        up_btn = ttk.Button(right, text="Move Up", command=lambda: self.move_selected(-1))
        up_btn.pack(fill=tk.X, pady=(6, 2), padx=6)

        down_btn = ttk.Button(right, text="Move Down", command=lambda: self.move_selected(1))
        down_btn.pack(fill=tk.X, pady=2, padx=6)

        remove_btn = ttk.Button(right, text="Remove Selected", command=self.remove_selected)
        remove_btn.pack(fill=tk.X, pady=2, padx=6)

        preview_btn = ttk.Button(right, text="Preview Header", command=self.preview_header)
        preview_btn.pack(fill=tk.X, pady=12, padx=6)

        self.output_var = tk.StringVar(value="")
        out_label = ttk.Label(right, textvariable=self.output_var, wraplength=140)
        out_label.pack(fill=tk.X, padx=6, pady=(6, 0))

        # Status bar
        self.status = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # Drag-and-drop support (if available)
        if USE_TKINTERDND:
            self._enable_dnd_tkinterdnd()
        else:
            note = "Drag & drop: tkinterdnd2 not installed. Use 'Add Files...' or pip install tkinterdnd2 to enable DnD."
            self.status.set(note)

    def _enable_dnd_tkinterdnd(self):
        # If using tkinterdnd2, we need to wrap root with its Tk class
        # To keep things simple, expect that the program was started with tkinterdnd2.Tk() if installed.
        try:
            # register listbox as drop target
            self.listbox.drop_target_register('DND_Files')
            self.listbox.dnd_bind('<<Drop>>', self._on_drop)
            self.status.set('Drop files into the list to add them.')
        except Exception:
            self.status.set('Drag & drop available but failed to register target.')

    def _on_drop(self, event):
        # event.data may be a list-like string; use tk.splitlist to split
        try:
            files = self.root.tk.splitlist(event.data)
        except Exception:
            # fallback: try naive split
            files = event.data.split()
        files = [f for f in files if f]
        self._add_paths(files)

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Select files to merge")
        if paths:
            self._add_paths(paths)

    def _add_paths(self, paths):
        added = 0
        for p in paths:
            p = os.path.abspath(p)
            if p not in self.file_list and os.path.isfile(p):
                self.file_list.append(p)
                self.listbox.insert(tk.END, os.path.basename(p))
                added += 1
        self.status.set(f"Added {added} file(s). Total: {len(self.file_list)}")

    def clear_all(self):
        self.file_list.clear()
        self.listbox.delete(0, tk.END)
        self.status.set("Cleared all files.")

    def remove_selected(self):
        sel = list(self.listbox.curselection())
        if not sel:
            return
        for i in reversed(sel):
            del self.file_list[i]
            self.listbox.delete(i)
        self.status.set(f"Removed {len(sel)} selected.")

    def move_selected(self, delta):
        sel = list(self.listbox.curselection())
        if not sel:
            return
        # We'll move the first selected block
        first = sel[0]
        new_index = first + delta
        if new_index < 0 or new_index >= len(self.file_list):
            return
        # move one item at a time for the selected indices
        for i in sel:
            j = i + delta
            if 0 <= j < len(self.file_list):
                self.file_list[i], self.file_list[j] = self.file_list[j], self.file_list[i]
        # rebuild listbox
        self._rebuild_listbox()
        # restore selection (shifted)
        self.listbox.selection_clear(0, tk.END)
        for i in [index + delta for index in sel]:
            if 0 <= i < self.listbox.size():
                self.listbox.selection_set(i)
        self.status.set('Moved selection.')

    def _rebuild_listbox(self):
        self.listbox.delete(0, tk.END)
        for p in self.file_list:
            self.listbox.insert(tk.END, os.path.basename(p))

    def choose_output(self):
        out = filedialog.asksaveasfilename(title="Save merged file as", defaultextension=".merged.txt",
                                           filetypes=[("All files","*.*")])
        if out:
            self.output_var.set(out)
            self.status.set(f"Output set: {out}")

    def preview_header(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("Preview header", "Select a file in the list to preview its merged header.")
            return
        idx = sel[0]
        path = self.file_list[idx]
        hdr = self._build_header(path)
        # show in a simple scrolled text window
        top = tk.Toplevel(self.root)
        top.title("Header Preview: " + os.path.basename(path))
        txt = tk.Text(top, wrap=tk.NONE)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert('1.0', hdr)
        txt.config(state=tk.DISABLED)

    def merge_now(self):
        if not self.file_list:
            messagebox.showwarning("No files", "No files added to merge.")
            return
        out = self.output_var.get()
        if not out:
            out = filedialog.asksaveasfilename(title="Save merged file as", defaultextension=".merged.txt",
                                               filetypes=[("All files","*.*")])
            if not out:
                return
            self.output_var.set(out)

        try:
            total = len(self.file_list)
            with open(out, 'wb') as fout:
                for i, p in enumerate(self.file_list, 1):
                    self.status.set(f"Merging {i}/{total}: {os.path.basename(p)}")
                    self.root.update_idletasks()

                    hdr = self._build_header(p)
                    fout.write(hdr.encode('utf-8'))

                    # stream file content to avoid loading large files fully into memory
                    with open(p, 'rb') as fin:
                        while True:
                            chunk = fin.read(8192)
                            if not chunk:
                                break
                            fout.write(chunk)

                    fout.write(FOOTER.encode('utf-8'))

            self.status.set(f"Merge complete: {out}")
            messagebox.showinfo("Success", f"Files merged successfully into:\n{out}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to merge files:\n{e}")
            self.status.set("Error during merge.")

    def _build_header(self, path):
        try:
            name = os.path.basename(path)
            ext = os.path.splitext(name)[1]
            size = os.path.getsize(path)
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
            sha256 = self._sha256(path)
            return HEADER_TEMPLATE.format(name=name, path=path, ext=ext or '<no ext>', size=size, mtime=mtime, sha256=sha256)
        except Exception as e:
            return f"--- FILE START ---\nName: {os.path.basename(path)}\nError building header: {e}\n--- CONTENT START ---\n"

    def _sha256(self, path):
        h = hashlib.sha256()
        try:
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return '<unreadable-file>'


def main():
    # If tkinterdnd2 is installed, use its Tk class for better DnD support
    if USE_TKINTERDND:
        try:
            root = tkinterdnd2.Tk()
        except Exception:
            root = tk.Tk()
    else:
        root = tk.Tk()

    app = FileMergerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
