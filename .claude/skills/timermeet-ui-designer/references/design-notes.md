# TimerMeet UI design notes

## Color palette (defined at the top of `timermeet_app/main_window.py`)

| Constant | Value | Use |
|---|---|---|
| `WINDOW_BG` | `#15171c` | Root window background |
| `PANEL_BG` | `#1c1f26` | Header/form/summary panel backgrounds |
| `FIELD_BG` | `#252a33` | Entry/OptionMenu/Textbox backgrounds |
| `BORDER` | `#333844` | Field border/highlight |
| `TEXT` | `#f2f3f5` | Primary text |
| `MUTED` | `#9aa1ac` | Secondary text (hints, labels) |
| `SUBTLE` | `#767d88` | Tertiary text (recurrence line) |
| `ACCENT` / `ACCENT_HOVER` | `#3b82f6` / `#2563eb` | Primary action buttons (Save, Open Teams) |
| `GHOST_BG` / `GHOST_HOVER` | `#2a2e37` / `#343a45` | Secondary/utility buttons |
| `DANGER` / `DANGER_HOVER` | `#b91c1c` / `#991b1b` | Destructive actions (Delete, Exit) |
| `CHIP_BG` | `#2a2e37` | Version/storage chips, stat cards |
| `GOLD_BG` / `GOLD_HOVER` | `#f2c14e` / `#e0ad33` | Donate button only |

Meeting cards use a separate `_CARD_PALETTE` dict (same hues, tuned for the card background) -- don't hardcode new colors elsewhere; add a constant here if a new one is genuinely needed.

## Spacing conventions

- Panel padding: `padx=14-16, pady=14-16` for outer panels; `padx=10, pady=(0,10)` between stacked form fields.
- Buttons: `padx=12, pady=6` (via `_button()`); card action buttons are slightly smaller.
- Use `tk.Frame(parent, bg=<matching parent bg>, width=N).pack(side="left")` as a spacer instead of ad-hoc padx bumps when you want a deliberate visual gap (see the Exit button separator in the header).

## Widget-count budget

- Header: ~10 widgets total (title, subtitle, 2 chips, 4 buttons + 1 spacer).
- Form panel: ~30 widgets (fixed, doesn't scale with data).
- Summary panel chrome: ~20 widgets (fixed).
- **Meeting card: ~10 widgets, multiplied by the number of visible meetings.** This is the one place where widget count scales with data and where a "just one more label" change has a real, measured cost (a full CustomTkinter-based card set with ~40 meetings added 20+ seconds to startup before the plain-tkinter rewrite; even plain-tk widgets have non-zero geometry-management cost at scale). Think twice before adding a widget here; prefer combining text into an existing label.

## Track record: simplifying fixed real bugs here, not just aesthetics

- Dropping CustomTkinter for plain tkinter fixed a 20+ second startup freeze (v2.0.1).
- Merging the countdown + recurrence line into one label per card reduced widget count and visual clutter at the same time (v2.1.0).
- Removing a single synchronous `update_idletasks()` call fixed the real remaining freeze (v2.1.0) -- the fix was deletion, not addition.

When in doubt, the direction that has actually worked in this project is *fewer moving parts*, not more visual polish layered on top.
