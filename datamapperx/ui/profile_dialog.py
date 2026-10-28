"""Create, duplicate, edit and delete scan profiles."""

from __future__ import annotations

import re
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from ..config import APP_TITLE, EXCEL_FILE_EXTENSIONS, TEXT_FILE_EXTENSIONS
from ..profiles import BUILT_IN_PROFILE_NAMES, save_profiles, validate_profile
from .dialogs import Dialog
from .widgets import UndoableEntry

REGEX_HELP = (
    "To extract data from text logs, use Python regular expressions.\n\n"
    "RECOMMENDED GROUPS\n"
    "• Name_Regex: capture the component as (?P<component>...)\n"
    "• Measure_Regex: capture the value as (?P<measured>...)\n"
    "  Optional: (?P<type>...) for the unit and (?P<tail>...) for the rest of the line (limits)\n"
    "• Min/Max regex: capture (?P<min>...) and (?P<max>...)\n\n"
    "TIP\n"
    "Select a built-in profile and press Duplicate to start from a working example, "
    "then use the live tester below to check your changes against a pasted line."
)

_TEXT_FIELDS = ("block_regex", "measure_regex", "lim2_regex", "lim3_regex")
_EXCEL_FIELDS = (
    ("sn_sheet", ""), ("data_sheet", ""), ("row_start", "2"), ("component_col", "A"),
    ("measure_col", "B"), ("min_col", "C"), ("max_col", "D"), ("unit_col", "E"),
)


class ProfileManager(Dialog):
    def __init__(self, parent: tk.Misc, profiles: dict[str, dict], on_changed: Callable[[str | None], None]):
        """``profiles`` is edited in place. ``on_changed(name)`` runs after a save (name) or delete (None)."""
        super().__init__(parent, "Manage profiles", modal=False, min_size=(760, 640))
        self.profiles = profiles
        self.on_changed = on_changed

        v = self.vars = {
            name: tk.StringVar()
            for name in (
                "name", "type", "extensions", "sn_regex", *_TEXT_FIELDS, *(f for f, _ in _EXCEL_FIELDS),
                "test_input",
            )
        }
        self.test_result = tk.StringVar(value="Result: ")
        self.original_name = ""
        self._entries: list[ttk.Entry] = []
        self._combos: list[ttk.Combobox] = []

        main = ttk.Frame(self, padding=14)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        # ---- left: list of profiles
        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Profiles", font=("Segoe UI Semibold", 11)).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.listbox = tk.Listbox(
            left, width=26, exportselection=False, activestyle="none", relief="flat", borderwidth=0,
            bg=self.palette.surface, fg=self.palette.fg, selectbackground=self.palette.accent,
            selectforeground="#ffffff" if self.palette.mode == "light" else "#000000",
            highlightthickness=1, highlightbackground=self.palette.muted, font=("Segoe UI", 10),
        )
        self.listbox.grid(row=1, column=0, sticky="ns")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        actions = ttk.Frame(left)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for col in range(3):
            actions.columnconfigure(col, weight=1)
        ttk.Button(actions, text="New", command=self._new).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(actions, text="Duplicate", command=self._duplicate).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(actions, text="Delete", command=self._delete).grid(row=0, column=2, sticky="ew", padx=(4, 0))

        # ---- right: editor
        right = ttk.LabelFrame(main, text="Edit profile", padding=12)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)

        self.notice = ttk.Label(right, text="", style="Muted.TLabel", wraplength=480, justify="left")
        self.notice.grid(row=0, column=0, columnspan=2, sticky="w")

        self.name_entry = self._entry(right, 1, "Profile name:", v["name"])
        ttk.Label(right, text="Input type:").grid(row=2, column=0, sticky="w", pady=5)
        self.type_combo = ttk.Combobox(right, textvariable=v["type"], values=["text", "excel"], state="readonly")
        self.type_combo.grid(row=2, column=1, sticky="ew", pady=5)
        self._combos.append(self.type_combo)
        self._entry(right, 3, "File extensions:", v["extensions"])
        self._entry(right, 4, "SN_Regex / Cell:", v["sn_regex"])
        ttk.Label(
            right, text="For Excel you can enter a cell such as B2, or leave blank to search the filename and cells.",
            style="Hint.TLabel", wraplength=480,
        ).grid(row=5, column=1, sticky="w", pady=(0, 4))

        self.text_frame = ttk.Frame(right)
        self.excel_frame = ttk.Frame(right)
        self._build_text_frame()
        self._build_excel_frame()

        footer = ttk.Frame(right)
        footer.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.save_button = ttk.Button(footer, text="Save profile", style="Accent.TButton", command=self._save)
        self.save_button.pack(side="right")

        v["type"].trace_add("write", lambda *_: self._show_fields())
        for name in ("test_input", *_TEXT_FIELDS):
            v[name].trace_add("write", lambda *_: self._evaluate_test())

        self._refresh_list()
        if self.profiles:
            self.listbox.selection_set(0)
            self._on_select()
        self.present(width=820, height=720)

    # ------------------------------------------------------------------ layout helpers
    def _entry(self, parent, row: int, label: str, var: tk.StringVar) -> UndoableEntry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 10))
        entry = UndoableEntry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        self._entries.append(entry)
        return entry

    def _build_text_frame(self) -> None:
        f = self.text_frame
        f.columnconfigure(1, weight=1)
        ttk.Button(f, text="Regex guide", command=lambda: messagebox.showinfo("Regex guide", REGEX_HELP, parent=self)).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(4, 6)
        )
        for row, (key, label) in enumerate(
            (("block_regex", "Name_Regex:"), ("measure_regex", "Measure_Regex:"),
             ("lim2_regex", "Min_Max_Regex1:"), ("lim3_regex", "Min_Max_Regex2:")),
            start=1,
        ):
            self._entry(f, row, label, self.vars[key])

        tester = ttk.LabelFrame(f, text="Live regex tester", padding=8)
        tester.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        tester.columnconfigure(0, weight=1)
        ttk.Label(tester, text="Paste a data row from a log:").grid(row=0, column=0, sticky="w")
        ttk.Entry(tester, textvariable=self.vars["test_input"]).grid(row=1, column=0, sticky="ew", pady=4)
        ttk.Label(tester, textvariable=self.test_result, wraplength=520, justify="left", font=("Segoe UI Semibold", 9)).grid(
            row=2, column=0, sticky="w"
        )

    def _build_excel_frame(self) -> None:
        f = self.excel_frame
        f.columnconfigure(1, weight=1)
        labels = {
            "sn_sheet": "SN_Sheet:", "data_sheet": "Data_Sheet:", "row_start": "Row_Start:",
            "component_col": "Component_Col:", "measure_col": "Measure_Col:", "min_col": "Min_Col:",
            "max_col": "Max_Col:", "unit_col": "Unit_Col (blank if none):",
        }
        for row, (key, _default) in enumerate(_EXCEL_FIELDS):
            self._entry(f, row, labels[key], self.vars[key])

    def _show_fields(self) -> None:
        if self.vars["type"].get() == "excel":
            self.text_frame.grid_remove()
            self.excel_frame.grid(row=6, column=0, columnspan=2, sticky="ew")
        else:
            self.excel_frame.grid_remove()
            self.text_frame.grid(row=6, column=0, columnspan=2, sticky="ew")

    # ------------------------------------------------------------------ state
    def _refresh_list(self, select: str | None = None) -> None:
        self.listbox.delete(0, tk.END)
        for name in self.profiles:
            self.listbox.insert(tk.END, name)
        if select and select in self.profiles:
            index = list(self.profiles).index(select)
            self.listbox.selection_set(index)
            self.listbox.see(index)

    def _set_readonly(self, readonly: bool) -> None:
        for entry in self._entries:
            entry.configure(state="readonly" if readonly else "normal")
        for combo in self._combos:
            combo.configure(state="disabled" if readonly else "readonly")
        self.save_button.configure(state="disabled" if readonly else "normal")

    def _load(self, name: str, data: dict) -> None:
        v = self.vars
        v["name"].set(name)
        v["type"].set(data.get("type", "text"))
        defaults = TEXT_FILE_EXTENSIONS if data.get("type", "text") == "text" else EXCEL_FILE_EXTENSIONS
        raw_ext = data.get("file_extensions") or ",".join(defaults)
        v["extensions"].set(raw_ext if isinstance(raw_ext, str) else ",".join(raw_ext))
        v["sn_regex"].set(data.get("sn_regex", ""))
        for key in _TEXT_FIELDS:
            v[key].set(data.get(key, ""))
        for key, default in _EXCEL_FIELDS:
            v[key].set(str(data.get(key, default)))
        v["test_input"].set("")
        self.test_result.set("Result: ")
        self._show_fields()

    def _on_select(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        name = self.listbox.get(selection[0])
        self.original_name = name
        self._load(name, self.profiles[name])
        built_in = name in BUILT_IN_PROFILE_NAMES
        self._set_readonly(built_in)
        self.notice.configure(
            text="Built-in profile (read-only). Press Duplicate to make an editable copy." if built_in else ""
        )

    def _new(self) -> None:
        self.listbox.selection_clear(0, tk.END)
        self.original_name = ""
        self._load("New profile", {"type": "text", "file_extensions": ",".join(TEXT_FILE_EXTENSIONS)})
        self._set_readonly(False)
        self.notice.configure(text="")
        self.name_entry.focus_set()
        self.name_entry.select_range(0, tk.END)

    def _duplicate(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showinfo(APP_TITLE, "Select a profile to duplicate first.", parent=self)
            return
        source = self.listbox.get(selection[0])
        self.listbox.selection_clear(0, tk.END)
        self.original_name = ""
        base, n = f"{source} (copy)", 2
        new_name = base
        while new_name in self.profiles:
            new_name, n = f"{base} {n}", n + 1
        self._load(new_name, self.profiles[source])
        self._set_readonly(False)
        self.notice.configure(text="Editing a copy. Press Save profile to keep it.")
        self.name_entry.focus_set()

    def _delete(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        name = self.listbox.get(selection[0])
        if name in BUILT_IN_PROFILE_NAMES:
            messagebox.showerror(APP_TITLE, "Built-in profiles cannot be deleted.", parent=self)
            return
        if not messagebox.askyesno("Delete profile", f"Delete '{name}'?", parent=self):
            return
        del self.profiles[name]
        save_profiles(self.profiles)
        self._refresh_list()
        self.original_name = ""
        self.on_changed(None)
        if self.profiles:
            self.listbox.selection_set(0)
            self._on_select()

    def _collect(self) -> dict:
        v = self.vars
        data: dict = {"type": v["type"].get(), "sn_regex": v["sn_regex"].get()}
        extensions = v["extensions"].get().strip()
        if data["type"] == "text":
            data["file_extensions"] = extensions or ",".join(TEXT_FILE_EXTENSIONS)
            for key in _TEXT_FIELDS:
                data[key] = v[key].get()
        else:
            data["file_extensions"] = extensions or ",".join(EXCEL_FILE_EXTENSIONS)
            for key, _default in _EXCEL_FIELDS:
                data[key] = v[key].get()
        return data

    def _save(self) -> None:
        name = self.vars["name"].get().strip()
        if not name:
            messagebox.showwarning(APP_TITLE, "Profile name cannot be empty.", parent=self)
            return
        if name in BUILT_IN_PROFILE_NAMES:
            messagebox.showwarning(APP_TITLE, "Cannot override built-in profiles. Choose another name.", parent=self)
            return

        data = self._collect()
        try:
            validate_profile(data)
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return

        replacing_other = name in self.profiles and name != self.original_name
        if replacing_other and not messagebox.askyesno(
            APP_TITLE, f"A profile named '{name}' already exists. Replace it?", parent=self
        ):
            return
        if self.original_name and self.original_name != name and self.original_name not in BUILT_IN_PROFILE_NAMES:
            self.profiles.pop(self.original_name, None)

        self.profiles[name] = data
        save_profiles(self.profiles)
        self.original_name = name
        self._refresh_list(select=name)
        self.notice.configure(text="")
        self.on_changed(name)
        messagebox.showinfo("Saved", f"Profile '{name}' saved.", parent=self)

    # ------------------------------------------------------------------ live tester
    def _evaluate_test(self) -> None:
        data = self.vars["test_input"].get().strip()
        if not data:
            self.test_result.set("Result: No data")
            return
        v = self.vars
        try:
            block_pattern, measure_pattern = v["block_regex"].get().strip(), v["measure_regex"].get().strip()
            if block_pattern:
                match = re.search(block_pattern, data, re.IGNORECASE)
                if match:
                    if "component" in match.groupdict():
                        self.test_result.set(f"Result: MATCHED BLOCK - Component: {match.group('component')}")
                    elif match.groups():
                        self.test_result.set(f"Result: MATCHED BLOCK - Component: {match.group(1)}")
                    else:
                        self.test_result.set("Result: Matched the block but found no component group")
                    return

            if measure_pattern:
                match = re.search(measure_pattern, data, re.IGNORECASE)
                if match:
                    self.test_result.set("Result: MATCHED MEASURE - " + self._describe_measure(match, data))
                    return

            self.test_result.set("Result: Format not recognized with the current regexes")
        except re.error as exc:
            self.test_result.set(f"Result: Regex error - {exc}")

    def _describe_measure(self, match: re.Match, data: str) -> str:
        groups = match.groupdict()
        parts = []
        if "measured" in groups:
            parts.append(f"Measured: {match.group('measured')}")
        elif match.groups():
            parts.append(f"Measured: {match.group(1)}")

        tail = match.group("tail") if "tail" in groups else data
        limits_found = False
        for pattern in (self.vars["lim2_regex"].get().strip(), self.vars["lim3_regex"].get().strip()):
            if not pattern:
                continue
            limit = re.search(pattern, tail or "")
            if limit:
                limits_found = True
                found = limit.groupdict()
                parts.append(f"Min: {limit.group('min')}" if "min" in found else "Min: ?")
                parts.append(f"Max: {limit.group('max')}" if "max" in found else "Max: ?")
                break

        if not parts:
            parts.append("Matched, but no measured group found")
        if not limits_found:
            parts.append("Limits: not found")
        return ", ".join(parts)
