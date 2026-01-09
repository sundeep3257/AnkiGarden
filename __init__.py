"""AnkiGarden - a garden mini-game driven by your Anki review streak.

Entry point for the add-on. Wires up:
- Persistent state (JSON in add-on folder)
- Review streak tracking
- Garden dialog and Tools menu entry
"""

from __future__ import annotations

import os

from aqt import mw
from aqt.gui_hooks import reviewer_did_answer_card
from aqt.qt import QAction
from aqt.utils import qconnect

from .state import AddonState
from .tracker import StreakTracker
from .ui import GardenDialog

# ----------------------------------------------------------------------
# Global singletons
# ----------------------------------------------------------------------

# Base directory of this add-on (used for state file).
_BASE_DIR = os.path.dirname(__file__)

# Persistent state.
addon_state = AddonState(base_dir=_BASE_DIR)
addon_state.load()

# Per-session streak tracker.
streak_tracker = StreakTracker(state=addon_state)


def _on_reviewer_did_answer_card(reviewer, card, ease: int) -> None:
    """Hook callback for when the user answers a card in the reviewer."""

    # Keep logic very light to avoid blocking the reviewer.
    try:
        streak_tracker.handle_answer(ease)
    except Exception:
        # Fail silently; add-on should not crash reviews.
        return


def _open_garden_dialog() -> None:
    """Open the garden dialog."""

    # Reuse a single dialog per call; keep it simple for MVP.
    dlg = GardenDialog(state=addon_state, parent=mw)
    dlg.exec()


def _setup_menu() -> None:
    """Add the 'AnkiGarden' entry to the Tools menu."""

    action = QAction("AnkiGarden", mw)
    qconnect(action.triggered, _open_garden_dialog)
    mw.form.menuTools.addAction(action)


def init_ankigarden() -> None:
    """Initialize the AnkiGarden add-on.

    Called on import.
    """

    _setup_menu()
    reviewer_did_answer_card.append(_on_reviewer_did_answer_card)


# Initialize on import.
init_ankigarden()


