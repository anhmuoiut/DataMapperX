"""A Tk that records instead of drawing: the workspace's own code, run with no window, no display and no keyboard focus.

Every widget is the real tkinter / ttk class, but the interpreter behind it is a recorder, so each call a widget makes to Tcl
simply succeeds and is written down. That runs the construction of the workspace and everything it does when the user acts
(import, mapping, settings, Run, Results, Details, Checks, charts, reports), which is where a typo, a missing attribute or a
wrong signature would stop the application, without opening anything on the desktop of the person running the tests.

What it cannot show is how anything looks, or whether Tk accepts an option: those stay with the checklist run in the real
window. The tree and the variables keep what they are given, so that what the workspace puts in a table can be read back.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock

from datamapperx.palette import LIGHT
from datamapperx.settings import Settings
from datamapperx.ui import validation_workspace as workspace


class MemoryTree(ttk.Treeview):
    """A ttk.Treeview that remembers its rows, headings, columns and selection instead of asking Tcl."""

    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._rows: dict[str, dict] = {"": {"children": []}}
        self._chosen: tuple[str, ...] = ()
        self._settings: dict = {"columns": tuple(kw.get("columns") or ()), "displaycolumns": kw.get("displaycolumns", ("#all",))}
        self._heads: dict[str, dict] = {}
        self._cols: dict[str, dict] = {}
        self._count = 0

    def __getitem__(self, key):
        return self._settings[key] if key in self._settings else super().__getitem__(key)

    def configure(self, cnf=None, **kw):
        kw = {**(cnf or {}), **kw}
        for key in ("columns", "displaycolumns"):
            if key in kw:
                self._settings[key] = tuple(kw[key])
        return super().configure(**{k: v for k, v in kw.items() if k not in ("columns", "displaycolumns")})

    config = configure

    def insert(self, parent, index, iid=None, **kw):
        self._count += 1
        iid = str(iid) if iid is not None else f"I{self._count:04d}"
        self._rows[iid] = {"parent": parent, "children": [], "text": kw.get("text", ""), "values": tuple(kw.get("values", ())),
                           "tags": tuple(kw.get("tags", ())), "open": kw.get("open", False)}
        self._rows[parent]["children"].append(iid)
        return iid

    def delete(self, *items):
        for iid in items:
            record = self._rows.get(iid)
            if record is None:
                continue
            self.delete(*record["children"])  # the children first, while their parent can still be found
            siblings = self._rows[record["parent"]]
            siblings["children"] = [c for c in siblings["children"] if c != iid]
            del self._rows[iid]

    def get_children(self, item=""):
        return tuple(self._rows[item]["children"])

    def exists(self, iid):
        return iid in self._rows and iid != ""

    def item(self, iid, option=None, **kw):
        record = self._rows[iid]
        if kw:
            record.update(kw)
            return None
        return record[option] if option else dict(record)

    def set(self, iid, column=None, value=None):
        values = self._rows[iid]["values"]
        return values[list(self._settings["columns"]).index(str(column))]

    def selection(self):
        return self._chosen

    def selection_set(self, *items):
        self._chosen = tuple(items[0]) if len(items) == 1 and isinstance(items[0], (list, tuple)) else tuple(items)

    def heading(self, column, option=None, **kw):
        record = self._heads.setdefault(str(column), {"text": "", "anchor": "center"})
        if kw:
            record.update(kw)
            return None
        return record[option] if option else dict(record)

    def column(self, column, option=None, **kw):
        record = self._cols.setdefault(str(column), {"width": 200, "anchor": "w"})
        if kw:
            record.update(kw)
            return None
        return record[option] if option else dict(record)

    def rows(self, parent=""):
        """The rows under ``parent`` as dictionaries (text, values, tags, open), in order."""
        return [self._rows[iid] for iid in self._rows[parent]["children"]]


class MemoryListbox(tk.Listbox):
    """A tk.Listbox that remembers its entries and which of them are selected (the report's list of items)."""

    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._entries: list[str] = []
        self._picked: set[int] = set()

    def _index(self, index):
        return len(self._entries) if index == "end" else int(index)

    def delete(self, first, last=None):
        self._entries.clear()
        self._picked.clear()

    def insert(self, index, *elements):
        at = self._index(index)
        self._entries[at:at] = [str(e) for e in elements]

    def get(self, first, last=None):
        return self._entries[self._index(first)]

    def size(self):
        return len(self._entries)

    def selection_set(self, first, last=None):
        end = self._index(last) if last is not None else self._index(first) + 1
        self._picked |= set(range(self._index(first), min(end, len(self._entries))))

    def selection_clear(self, first, last=None):
        self._picked.clear()

    def curselection(self):
        return tuple(sorted(self._picked))


def _variable_class(cls, default):
    def init(self, master=None, value=None, name=None):
        self._value, self._traces, self._name = default if value is None else value, [], name or f"VAR{id(self)}"
        self._root, self._tk = master, getattr(master, "tk", None)

    def get(self):
        return self._value

    def set(self, value):
        self._value = value
        for callback in list(self._traces):
            callback(self._name, "", "write")

    def trace_add(self, mode, callback):
        self._traces.append(callback)
        return str(len(self._traces))

    return {"__init__": init, "get": get, "set": set, "trace_add": trace_add, "trace_remove": lambda self, mode, cbname: None}


def install(monkeypatch):
    """Put the recorder in place (undone when the test ends) and return the root that widgets are built on."""
    for cls, default in ((tk.StringVar, ""), (tk.BooleanVar, False), (tk.IntVar, 0), (tk.DoubleVar, 0.0)):
        for name, function in _variable_class(cls, default).items():
            monkeypatch.setattr(cls, name, function)
    monkeypatch.setattr(ttk, "Treeview", MemoryTree)
    monkeypatch.setattr(tk, "Listbox", MemoryListbox)
    root = tk.Tk.__new__(tk.Tk)
    root.tk, root._w, root.children, root.master, root._tclCommands, root._name = MagicMock(), ".", {}, None, [], "."
    root.tk.call.return_value = ""
    root.tk.getint.side_effect = lambda value: 900  # every widget is 900 by 900 pixels
    root.palette = LIGHT
    monkeypatch.setattr(tk, "_default_root", root, raising=False)
    monkeypatch.setattr(workspace.ValidationWorkspace, "_dialog_parent", lambda self: root)
    return root


def build_workspace(monkeypatch):
    """The real ValidationWorkspace, constructed on the recorder; its background tasks run at once, on this thread."""
    root = install(monkeypatch)
    ws = workspace.ValidationWorkspace(root, LIGHT, settings=Settings(), save_settings=lambda: None)

    def run(work, *, on_success, on_error, on_progress=None):
        try:
            result = work(lambda *args: None)
        except Exception as exc:  # delivered the way the real runner delivers it
            on_error(exc)
        else:
            on_success(result)

    ws.tasks.run = run
    return root, ws


def last_option(root, widget, option):
    """The value the widget was last configured with for ``option`` (``-state`` as "state"), or None."""
    path, found = str(widget), None
    for call in root.tk.call.call_args_list:
        args = call.args
        flat = [a for part in args for a in (part if isinstance(part, tuple) else (part,))]
        if path in flat[:1] and "configure" in flat[:3] and f"-{option}" in flat:
            found = flat[flat.index(f"-{option}") + 1]
    return found


def _words(call):
    return [a for part in call.args for a in (part if isinstance(part, tuple) else (part,))]


def is_gridded(root, widget):
    """Whether the widget was last put on its grid (True) or taken off it (False); None if it never was either."""
    path, shown = str(widget), None
    for call in root.tk.call.call_args_list:
        words = _words(call)
        if words[:1] == ["grid"] and path in words:
            shown = False if words[1:2] == ["remove"] else True if words[1:2] == ["configure"] else shown
    return shown


def canvas_texts(root, canvas):
    """The texts drawn on a canvas since it was last cleared, in the order they were drawn."""
    path, texts = str(canvas), []
    for call in root.tk.call.call_args_list:
        words = _words(call)
        if words[:1] == [path] and words[1:3] == ["delete", "all"]:
            texts = []
        elif words[:1] == [path] and words[1:3] == ["create", "text"] and "-text" in words:
            texts.append(words[words.index("-text") + 1])
    return texts
