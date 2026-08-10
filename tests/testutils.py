"""Shared test helpers for this suite's real-`tk.Tk()` tests.

The one helper here exists to correct a real methodological blind spot
found in this project's own leak-detection history (see
`.claude/skills/timermeet-python-builder/references/module-map.md`'s
"Recurring footgun" note): `root._tclCommands` -- the metric
`tests/test_scrollable_panel.py` already (correctly) uses -- only reflects
Tcl commands registered directly against the ROOT widget's own bookkeeping
list. That is exactly right for a `bind_all()`/`unbind_all()` leak (CPython's
`Misc.bind_all` always routes through `self._root()._bind(...)`), but it is
BLIND to a leak from a plain, non-"all" `.bind()` call on any other widget --
confirmed empirically: 500 leaked plain-`.bind()` Tcl commands on a `tk.Frame`
moved `root._tclCommands`'s count by exactly 0, while the real
interpreter-wide command count (`info commands`) moved by exactly 500.

`count_tcl_commands()` below queries that real, authoritative count via Tcl's
own `info commands` instead of any single widget's bookkeeping list -- use
this (not `root._tclCommands`) for any NEW leak-regression test on a plain
`.bind()`. Existing `root._tclCommands`-based assertions for `bind_all()`
cases (`tests/test_scrollable_panel.py`) are not wrong and do not need to
change -- `bind_all()` is the one case where `root._tclCommands` already is
the right metric -- but a plain `.bind()` case must use this helper instead.
"""

import tkinter as tk


def count_tcl_commands(root: tk.Tk) -> int:
    """The real, interpreter-wide Tcl command count, via `info commands` --
    unlike `len(root._tclCommands or [])`, this catches a leak from a plain
    `.bind()` call on ANY widget, not just ones registered against `root`'s
    own bookkeeping list (see this module's docstring)."""
    return len(root.tk.splitlist(root.tk.call("info", "commands")))
