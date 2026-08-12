"""Regression test for the header action-row overflow bug found by a
real-`tk.Tk()` responsiveness investigation: `_build_header`'s actions
column (Notificar/Idioma/up to 2 view-switch buttons/Gadget/Bandeja/Donar/
Salir) has no shrink behavior of its own -- Tk's grid always gives a
0-weight column its full requested size first and shrinks the *other*
(weighted) column to absorb any deficit -- so at the app's own declared
floor (`root.minsize(960, 640)`, v2.4.0), which an entirely ordinary action
(Windows' Win+Left/Right half-screen Snap on a 1920px-wide monitor) lands on
directly, the row's total requested width (measured pre-fix at ~1037-1061px
across the three header instances) pushed Donar/Salir off the right edge of
the window -- completely invisible and unclickable, not just visually
tight.

This asserts the investigation's exact hard acceptance criterion: at every
width from that floor up to a large monitor, on all three header-bearing
views (list/month/week), every header button's right edge
(`winfo_x() + winfo_width()`, measured here as an absolute screen-relative
offset via `winfo_rootx()` so nested frame padding is included automatically)
must stay within the window's actual rendered width, and no two buttons may
overlap.

Builds one real `MainWindow` against a real `tk.Tk()`, shared across the
width/view sweep (same reasoning as `tests/test_calendar_day_click.py`:
mapping this app's full widget tree -- three header copies, the form, the
summary panel, 42 calendar cells, and the ~168-cell week grid -- for the
first time is the expensive part, at a few seconds; every resize afterward
is cheap). Skipped automatically if no display is available, same as every
other real-Tk test in this suite.

A second-round adversarial review found this file structurally blind to a
real, severe companion bug at the *same* checkpoints it already exercises:
`title_label` (the app's own name) and `subtitle_label` could render at
almost 0% of their required width -- at the app's own 960px floor, a
freshly built window showed `title_label` at ~1px out of a natural ~170px
(~0% visible), and at the app's literal default launch geometry (1180x760)
`subtitle_label` clipped mid-sentence at 41%, with no ellipsis or other
indication text was missing -- yet this file's only assertions were about
button geometry, so it never noticed either. `HeaderTitleAndSubtitleTests`
below closes that gap: it asserts `title_label` is *never* rendered
narrower than its own natural/required width (the fix: a real
`grid_columnconfigure(minsize=...)` floor on column 0, see
`_header_title_column_minsize`), and that `subtitle_label` is always either
its full text, a clean `…`-terminated truncation, or empty (hidden) --
never a raw, silently mid-word-clipped string. `HeaderResizeHysteresisTests`
covers the same investigation's second finding: pre-fix, whether the title
rendered fully at a given final width depended on *how* the window got
there (built fresh at that size vs. built larger and resized down), not
just the final size itself -- a numeric `minsize` floor is, by construction,
history-independent, so this is a regression guard for that determinism,
not just the plain non-clipping guarantee `HeaderTitleAndSubtitleTests`
already covers.
"""

import unittest
from typing import Optional

try:
    import tkinter as tk

    from timermeet_app import main_window
except ImportError:  # pragma: no cover - non-Windows/no-Tk dev environments
    tk = None
    main_window = None


def _no_op(*_args, **_kwargs):
    return None


def _make_callbacks(**overrides):
    fields = {
        "on_save": _no_op,
        "on_clear": _no_op,
        "on_edit": _no_op,
        "on_delete": _no_op,
        "on_open_link": _no_op,
        "on_test_sound": _no_op,
        "on_set_now": _no_op,
        "on_toggle_language": _no_op,
        "on_test_notification": _no_op,
        "on_filter_change": _no_op,
        "on_clear_past": _no_op,
        "on_exit": _no_op,
        "on_add_company": _no_op,
        "on_remove_company": _no_op,
        "on_toggle_gadget_mode": _no_op,
        "on_enter_tray_mode": _no_op,
        "on_set_active_view": _no_op,
        "on_calendar_prev_month": _no_op,
        "on_calendar_next_month": _no_op,
        "on_calendar_today": _no_op,
        "on_calendar_day_click": _no_op,
        "on_week_prev": _no_op,
        "on_week_next": _no_op,
        "on_week_today": _no_op,
        "on_week_slot_click": _no_op,
        "on_toggle_week_column_mode": _no_op,
        "on_delete_series": _no_op,
        "on_set_app_theme": _no_op, "on_gadget_resize": _no_op,
    }
    fields.update(overrides)
    return main_window.Callbacks(**fields)


# Matches the investigation's own sweep: the app's declared minsize floor
# (v2.4.0) -- which a routine Win+Left/Right half-screen Snap on any
# 1920px-wide monitor lands on directly -- through the two widths that
# pinpointed exactly where Donate/Exit stopped clipping pre-fix (980, 1040),
# up to a large single monitor.
_WIDTHS_PX = [960, 980, 1000, 1040, 1080, 1180, 1920]


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class HeaderActionRowOverflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            raise unittest.SkipTest(f"No display available for Tk: {exc}")
        # Not withdrawn: winfo_rootx()/winfo_width() need the window actually
        # mapped to report real, settled geometry (same reasoning
        # tests/test_calendar_day_click.py documents for event_generate).
        cls.root.geometry("1180x760+0+0")
        cls.view = main_window.MainWindow(cls.root, _make_callbacks())
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    @staticmethod
    def _labeled_buttons(header: "main_window._HeaderWidgets"):
        """Left-to-right pack order `_build_header` actually builds in --
        overlap checks below rely on this order matching reality."""
        buttons = [("notify", header.notify_button), ("language", header.language_button)]
        buttons += [(f"view:{key}", btn) for btn, key in header.view_switch_buttons]
        buttons += [
            ("gadget", header.gadget_button), ("tray", header.tray_button),
            ("donate", header.donate_button), ("exit", header.exit_button),
        ]
        return buttons

    def _assert_header_buttons_fit(self, header, view_name: str, window_width: int) -> None:
        prev_right = None
        prev_label = None
        for label, btn in self._labeled_buttons(header):
            x = btn.winfo_rootx() - self.root.winfo_rootx()
            right = x + btn.winfo_width()
            self.assertLessEqual(
                right, window_width,
                f"[{view_name} @ {window_width}px] {label!r} right edge {right}px "
                f"exceeds the window's actual width ({window_width}px) -- invisible/unclickable",
            )
            if prev_right is not None:
                self.assertGreaterEqual(
                    x, prev_right,
                    f"[{view_name} @ {window_width}px] {label!r} at x={x} overlaps "
                    f"{prev_label!r} (which ends at {prev_right})",
                )
            prev_right = right
            prev_label = label

    def test_header_buttons_never_overflow_or_overlap_across_widths(self):
        headers = {
            "list": self.view.full_header,
            "calendar": self.view.calendar_header,
            "week": self.view.week_header,
        }
        for view_name, header in headers.items():
            self.view.set_active_view(view_name)
            for width in _WIDTHS_PX:
                self.root.geometry(f"{width}x640+0+0")
                self.root.update()
                with self.subTest(view=view_name, width=width):
                    self._assert_header_buttons_fit(header, view_name, self.root.winfo_width())


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class HeaderTitleAndSubtitleTests(unittest.TestCase):
    """Second-round regression coverage (see module docstring): the first
    round's `HeaderActionRowOverflowTests` above only ever asserted on
    button geometry, so it was structurally blind to `title_label`/
    `subtitle_label` collapsing at these exact same checkpoints. Shares one
    `MainWindow` across the whole sweep for the same performance reason
    `HeaderActionRowOverflowTests` already documents."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            raise unittest.SkipTest(f"No display available for Tk: {exc}")
        cls.root.geometry("1180x760+0+0")
        cls.view = main_window.MainWindow(cls.root, _make_callbacks())
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def _assert_title_not_clipped(self, header, view_name: str, width: int) -> None:
        title = header.title_label
        self.assertEqual(
            title.winfo_width(), title.winfo_reqwidth(),
            f"[{view_name} @ {width}px] title_label rendered at {title.winfo_width()}px, "
            f"narrower than its own natural width ({title.winfo_reqwidth()}px) -- the app's own "
            f"name is being clipped",
        )

    def _assert_subtitle_not_mid_word_clipped(self, header, view_name: str, width: int) -> None:
        subtitle = header.subtitle_label
        text = subtitle.cget("text")
        # Acceptable outcomes per the fix's own acceptance criterion: the
        # full untruncated string, a clean "…"-terminated truncation, or
        # empty (this app's stand-in for "hidden"). A raw mid-word clip is
        # everything else -- in practice, that means the rendered width
        # falling short of what the *displayed* text itself needs, since a
        # properly truncated/emptied string always fits what's available.
        acceptable = text == "" or text.endswith("…") or subtitle.winfo_width() >= subtitle.winfo_reqwidth()
        self.assertTrue(
            acceptable,
            f"[{view_name} @ {width}px] subtitle_label shows a raw, silently clipped string "
            f"{text!r} (width={subtitle.winfo_width()}, required={subtitle.winfo_reqwidth()}) -- "
            f"expected the full text, a '…'-terminated truncation, or empty",
        )

    def test_title_never_clips_and_subtitle_never_raw_clips_across_widths(self):
        headers = {
            "list": self.view.full_header,
            "calendar": self.view.calendar_header,
            "week": self.view.week_header,
        }
        for view_name, header in headers.items():
            self.view.set_active_view(view_name)
            for width in _WIDTHS_PX:
                self.root.geometry(f"{width}x640+0+0")
                self.root.update()
                with self.subTest(view=view_name, width=width):
                    self._assert_title_not_clipped(header, view_name, self.root.winfo_width())
                    self._assert_subtitle_not_mid_word_clipped(header, view_name, self.root.winfo_width())


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class HeaderResizeHysteresisTests(unittest.TestCase):
    """Regression guard for the investigation's second finding: pre-fix, a
    window built fresh at the 960px floor showed `title_label` fully
    collapsed, but a window built at the 1180x760 default launch geometry
    and then resized *down* to 960px showed it fully intact at that same
    final size -- final geometry alone didn't determine the outcome,
    something about build-vs-resize order did (an artifact of Tk's grid
    negotiating column sizes from natural content requests with no floor of
    its own). A numeric `grid_columnconfigure(minsize=...)` floor (see
    `_header_title_column_minsize`) is a static configuration value, not
    something re-derived from content/negotiation history, so it must
    produce identical results regardless of how the window got there --
    this builds two independent `MainWindow`s (one fresh at 960px, one
    built at 1180px then resized down) and asserts they agree."""

    def _build(self, initial_geometry: str, final_width: Optional[int]):
        root = tk.Tk()
        root.minsize(960, 640)
        root.geometry(initial_geometry)
        view = main_window.MainWindow(root, _make_callbacks())
        root.update()
        if final_width is not None:
            root.geometry(f"{final_width}x640+0+0")
            root.update()
        return root, view

    def test_title_and_subtitle_identical_regardless_of_build_vs_resize_order(self):
        fresh_root, fresh_view = self._build("960x640+0+0", final_width=None)
        resized_root, resized_view = self._build("1180x760+0+0", final_width=960)
        try:
            for view_name in ("list", "calendar", "week"):
                fresh_view.set_active_view(view_name)
                resized_view.set_active_view(view_name)
                fresh_root.update()
                resized_root.update()
                fresh_header = getattr(fresh_view, f"{'full' if view_name == 'list' else view_name}_header")
                resized_header = getattr(resized_view, f"{'full' if view_name == 'list' else view_name}_header")
                with self.subTest(view=view_name):
                    self.assertEqual(
                        fresh_header.title_label.winfo_width(), fresh_header.title_label.winfo_reqwidth(),
                        f"[{view_name}] fresh-build-at-960 must not clip the title",
                    )
                    self.assertEqual(
                        resized_header.title_label.winfo_width(), resized_header.title_label.winfo_reqwidth(),
                        f"[{view_name}] build-at-1180-then-resize-to-960 must not clip the title",
                    )
                    self.assertEqual(
                        fresh_header.title_label.winfo_width(), resized_header.title_label.winfo_width(),
                        f"[{view_name}] title_label's rendered width must not depend on resize history",
                    )
        finally:
            for root in (fresh_root, resized_root):
                try:
                    root.destroy()
                except tk.TclError:  # nosec B110 - already gone, nothing to clean up
                    pass


if __name__ == "__main__":
    unittest.main()
