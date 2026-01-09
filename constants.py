"""Constants for the AnkiGarden add-on."""

from __future__ import annotations

# Garden dimensions (columns x rows)
GARDEN_WIDTH: int = 15
GARDEN_HEIGHT: int = 7

# Streak thresholds for rewards
STREAK_THRESHOLDS = {
    5: "water",
    10: "plants",
    30: "trees",
    50: "sunlight",
}

# Inventory keys for consistency
INVENTORY_KEYS = ("water", "plants", "trees", "sunlight", "coins", "seeds", "path")

# Shop prices (in coins)
SHOP_PRICES = {
    "water": 20,
    "plants": 50,
    "trees": 100,
    "sunlight": 200,
    "seeds": 1000,
    "path": 20,
}

# Colorful plant colors (for seed evolution)
COLORFUL_PLANT_COLORS = [
    "red",
    "orange",
    "yellow",
    "dark_blue",
    "light_blue",
    "purple",
    "pink",
    "teal",
]

# Aesthetic modes
AESTHETIC_MODES = [
    "default",
    "night",
    "summer",
    "winter",
    "spring",
    "autumn",
]

# Theme unlock prices (in coins)
THEME_UNLOCK_PRICE = 2000

# Persistence / schema
STATE_FILENAME = "ankigarden_state.json"
CURRENT_SCHEMA_VERSION = 1


