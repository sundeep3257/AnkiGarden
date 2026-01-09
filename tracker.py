"""Review streak tracking logic for AnkiGarden.

Hooks into Anki's reviewer answer events and awards tokens at iterative
streak thresholds. Keeps a per-session streak counter only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from aqt import mw
from aqt.utils import tooltip

from .state import AddonState


@dataclass
class StreakTracker:
    """Tracks the current review streak for this Anki session."""

    state: AddonState
    current_streak: int = 0
    # Track which multiples have been awarded in this streak run to avoid duplicates.
    # Key: (threshold, multiple), e.g., (5, 1) means we awarded at streak 5.
    awarded_multiples: Set[tuple[int, int]] = field(default_factory=set)

    def reset(self) -> None:
        """Reset streak and per-run awarded multiples."""

        self.current_streak = 0
        self.awarded_multiples.clear()

    def handle_answer(self, ease: int) -> None:
        """Handle a reviewer answer.

        `ease` is the Anki ease integer (1=Again, 2=Hard, 3=Good, 4=Easy).
        Any ease > 1 is treated as a correct answer.
        """

        if ease <= 1:
            # Wrong answer: streak breaks.
            self.reset()
            return

        # Correct answer: award 1 coin (no pop-up)
        self.state.award_token("coins", 1)

        # Correct answer.
        self.current_streak += 1
        self._maybe_award_for_streak()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _maybe_award_for_streak(self) -> None:
        """Award inventory tokens at iterative thresholds.

        Rewards are given at:
        - 15 correct in a row: +1 Water
        - 30 correct in a row: +1 Plant
        - 50 correct in a row: +1 Tree
        """

        streak = self.current_streak
        awards: List[str] = []

        # Track what we're awarding at this exact streak to avoid duplicates
        award_water = False
        award_plant = False
        award_tree = False

        # 15 correct: water
        if streak == 15:
            key = (15, 1)
            if key not in self.awarded_multiples:
                self.awarded_multiples.add(key)
                award_water = True

        # 30 correct: plant
        if streak == 30:
            key = (30, 1)
            if key not in self.awarded_multiples:
                self.awarded_multiples.add(key)
                award_plant = True

        # 50 correct: tree
        if streak == 50:
            key = (50, 1)
            if key not in self.awarded_multiples:
                self.awarded_multiples.add(key)
                award_tree = True

        # Apply awards
        if award_water:
            self.state.award_token("water", 1)
            awards.append("Water")
        if award_plant:
            self.state.award_token("plants", 1)
            awards.append("Plant")
        if award_tree:
            self.state.award_token("trees", 1)
            awards.append("Tree")

        # Show tooltip if we awarded anything
        if awards:
            # Combine multiple awards into one message
            msg = "+" + " +".join(f"1 {a}" for a in awards)
            tooltip(msg, parent=mw, period=2000)

    def _pretty_inventory_name(self, key: str) -> str:
        """Human-friendly label for an inventory key."""

        mapping: Dict[str, str] = {
            "water": "Water",
            "plants": "Plant",
            "trees": "Tree",
            "sunlight": "Sunlight",
        }
        return mapping.get(key, key.title())


