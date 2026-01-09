"""Persistent state management for the AnkiGarden add-on.

Stores inventory and garden layout in a JSON file inside the add-on folder.
Includes basic schema versioning to allow future migrations.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import random

from .constants import (
    AESTHETIC_MODES,
    COLORFUL_PLANT_COLORS,
    CURRENT_SCHEMA_VERSION,
    GARDEN_HEIGHT,
    GARDEN_WIDTH,
    INVENTORY_KEYS,
    SHOP_PRICES,
    STATE_FILENAME,
)

UTC = timezone.utc


def utc_now() -> datetime:
    """Return the current UTC time."""

    return datetime.now(UTC)


def to_iso(dt: datetime) -> str:
    """Convert a datetime to an ISO 8601 string."""

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def from_iso(s: str) -> Optional[datetime]:
    """Parse an ISO 8601 string to datetime.

    Returns None on failure.
    """

    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def default_inventory() -> Dict[str, int]:
    """Return a default inventory dict."""

    return {k: 0 for k in INVENTORY_KEYS}


def default_garden() -> Dict[str, Any]:
    """Return a default garden structure."""

    return {
        "width": GARDEN_WIDTH,
        "height": GARDEN_HEIGHT,
        # Flat list of tiles, row-major. Each entry is either None or a tile dict.
        "tiles": [None for _ in range(GARDEN_WIDTH * GARDEN_HEIGHT)],
    }


def initial_state() -> Dict[str, Any]:
    """Return a fresh initial state dict."""

    inv = default_inventory()
    # Give starting items
    inv["water"] = 3
    inv["plants"] = 1
    inv["trees"] = 0
    inv["sunlight"] = 0
    inv["seeds"] = 0
    inv["coins"] = 0
    
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "inventory": inv,
        "garden": default_garden(),
        "aesthetic_mode": "default",
        "unlocked_themes": ["default"],  # Only default theme is unlocked initially
        "paths": [],  # List of path edges: [(row, col, direction), ...] where direction is "n", "s", "e", "w"
    }


@dataclass
class TileStatus:
    """Represents the computed status for a tile."""

    is_empty: bool = True
    is_blooming: bool = False
    is_wilted: bool = False
    is_dead: bool = False
    # For plants only: 0 = not wilted, 1 = mildly wilted, 2 = heavily wilted.
    wilt_level: int = 0


@dataclass
class AddonState:
    """Encapsulates all AnkiGarden persistent state operations."""

    base_dir: str
    data: Dict[str, Any] = field(default_factory=initial_state)

    @property
    def path(self) -> str:
        """Return the path to the JSON state file."""

        return os.path.join(self.base_dir, STATE_FILENAME)

    # ------------------------------------------------------------------
    # Loading / saving / migration
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load state from disk, creating a default file if necessary."""

        if not os.path.exists(self.path):
            self.data = initial_state()
            self._save()
            return

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except Exception:
            # If the file is corrupt, fall back to a fresh state.
            self.data = initial_state()
            self._save()
            return

        if not isinstance(loaded, dict):
            self.data = initial_state()
            self._save()
            return

        self.data = self._migrate(loaded)
        self._ensure_defaults()
        self._save()  # Save back in canonical format.

    def _ensure_defaults(self) -> None:
        """Ensure required keys are present in the state."""

        inv = self.data.setdefault("inventory", {})
        for k in INVENTORY_KEYS:
            inv.setdefault(k, 0)
        
        # Ensure aesthetic mode is set
        self.data.setdefault("aesthetic_mode", "default")
        if self.data["aesthetic_mode"] not in AESTHETIC_MODES:
            self.data["aesthetic_mode"] = "default"
        
        # Ensure unlocked themes are set (migrate old saves)
        if "unlocked_themes" not in self.data:
            # Old saves: only default was available, so unlock it
            self.data["unlocked_themes"] = ["default"]
        # Ensure default is always unlocked
        unlocked = self.data.get("unlocked_themes", [])
        if "default" not in unlocked:
            unlocked.append("default")
            self.data["unlocked_themes"] = unlocked
        
        # Ensure paths list exists
        if "paths" not in self.data:
            self.data["paths"] = []

        garden = self.data.setdefault("garden", {})
        old_w = int(garden.get("width", GARDEN_WIDTH))
        old_h = int(garden.get("height", GARDEN_HEIGHT))
        garden["width"] = GARDEN_WIDTH
        garden["height"] = GARDEN_HEIGHT

        tiles = garden.get("tiles")
        expected_len = GARDEN_WIDTH * GARDEN_HEIGHT
        if not isinstance(tiles, list):
            tiles = []

        # If size changed (e.g., upgrading from 5x4 to 5x10), preserve existing
        # tiles in the overlapping top-left region instead of wiping.
        old_expected_len = max(old_w, 0) * max(old_h, 0)
        if len(tiles) != expected_len:
            new_tiles: List[Optional[Dict[str, Any]]] = [None for _ in range(expected_len)]
            if old_expected_len == len(tiles) and old_w > 0 and old_h > 0:
                for r in range(min(old_h, GARDEN_HEIGHT)):
                    for c in range(min(old_w, GARDEN_WIDTH)):
                        old_idx = r * old_w + c
                        new_idx = r * GARDEN_WIDTH + c
                        if 0 <= old_idx < len(tiles) and 0 <= new_idx < len(new_tiles):
                            new_tiles[new_idx] = tiles[old_idx]
            else:
                # Fallback: shallow copy as much as possible in row-major order.
                for i in range(min(len(tiles), len(new_tiles))):
                    new_tiles[i] = tiles[i]
            tiles = new_tiles
            garden["tiles"] = tiles

        # Ensure each tile dict carries row/col for persistence/debugging.
        for idx, tile in enumerate(tiles):
            if isinstance(tile, dict):
                row, col = divmod(idx, GARDEN_WIDTH)
                tile.setdefault("row", row)
                tile.setdefault("col", col)

    def _migrate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate a loaded state dict to the current schema version.

        For now, only schema_version 1 is supported, but this method is
        structured to allow future migration steps.
        """

        version = int(data.get("schema_version", 0))
        if version < 1:
            # Treat anything older/unknown as fresh state for MVP.
            return initial_state()

        # If we add future versions, incrementally migrate here.
        data["schema_version"] = CURRENT_SCHEMA_VERSION
        return data

    def _safe_write(self, text: str) -> None:
        """Safely write text to the state file using a temporary file."""

        target = self.path
        tmp = target + ".tmp"
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)

    def _save(self) -> None:
        """Persist current state to disk."""

        text = json.dumps(self.data, indent=2, sort_keys=True)
        self._safe_write(text)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------
    def get_inventory(self) -> Dict[str, int]:
        """Return a copy of the inventory dictionary."""

        inv = self.data.get("inventory") or {}
        # Return a shallow copy to avoid accidental external mutation.
        return {k: int(inv.get(k, 0)) for k in INVENTORY_KEYS}

    def get_garden_dims(self) -> Tuple[int, int]:
        """Return (width, height) of the garden."""

        garden = self.data.get("garden") or {}
        return int(garden.get("width", GARDEN_WIDTH)), int(
            garden.get("height", GARDEN_HEIGHT)
        )

    def get_tiles(self) -> List[Optional[Dict[str, Any]]]:
        """Return the list of tiles (do not modify directly)."""

        garden = self.data.get("garden") or {}
        tiles = garden.get("tiles")
        if not isinstance(tiles, list):
            tiles = [None for _ in range(GARDEN_WIDTH * GARDEN_HEIGHT)]
            garden["tiles"] = tiles
        return tiles
    
    def get_aesthetic_mode(self) -> str:
        """Return the current aesthetic mode."""
        return self.data.get("aesthetic_mode", "default")
    
    def set_aesthetic_mode(self, mode: str) -> None:
        """Set the aesthetic mode (only if unlocked)."""
        if mode in AESTHETIC_MODES and self.is_theme_unlocked(mode):
            self.data["aesthetic_mode"] = mode
            self._save()
    
    def is_theme_unlocked(self, mode: str) -> bool:
        """Check if a theme is unlocked."""
        unlocked = self.data.get("unlocked_themes", ["default"])
        return mode in unlocked
    
    def get_unlocked_themes(self) -> List[str]:
        """Return list of unlocked themes."""
        unlocked = self.data.get("unlocked_themes", ["default"])
        # Ensure default is always unlocked
        if "default" not in unlocked:
            unlocked.append("default")
        return unlocked
    
    def unlock_theme(self, mode: str) -> tuple[bool, str]:
        """Unlock a theme by spending coins.
        
        Returns (success: bool, message: str)
        """
        from .constants import THEME_UNLOCK_PRICE
        
        if mode not in AESTHETIC_MODES:
            return (False, f"Invalid theme: {mode}")
        
        if mode == "default":
            return (False, "Default theme is already unlocked.")
        
        if self.is_theme_unlocked(mode):
            return (False, f"{mode.title()} theme is already unlocked.")
        
        inv = self.data.setdefault("inventory", default_inventory())
        current_coins = int(inv.get("coins", 0))
        
        if current_coins < THEME_UNLOCK_PRICE:
            return (False, f"Not enough coins. Need {THEME_UNLOCK_PRICE} coins to unlock {mode.title()} theme.")
        
        # Spend coins and unlock theme
        inv["coins"] = current_coins - THEME_UNLOCK_PRICE
        unlocked = self.data.get("unlocked_themes", ["default"])
        unlocked.append(mode)
        self.data["unlocked_themes"] = unlocked
        self._save()
        return (True, f"Unlocked {mode.title()} theme for {THEME_UNLOCK_PRICE} coins!")

    # ------------------------------------------------------------------
    # Inventory operations
    # ------------------------------------------------------------------
    def award_token(self, key: str, amount: int = 1) -> None:
        """Add tokens to inventory for a particular key."""

        if key not in INVENTORY_KEYS:
            return
        inv = self.data.setdefault("inventory", default_inventory())
        inv[key] = int(inv.get(key, 0)) + int(amount)
        self._save()

    def spend_token(self, key: str, amount: int = 1) -> bool:
        """Attempt to spend `amount` of a token.

        Returns True on success, False if insufficient balance or invalid key.
        """

        if key not in INVENTORY_KEYS:
            return False
        inv = self.data.setdefault("inventory", default_inventory())
        current = int(inv.get(key, 0))
        if current < amount:
            return False
        inv[key] = current - amount
        self._save()
        return True

    def purchase_with_coins(self, item: str) -> tuple[bool, str]:
        """Purchase an item using coins.

        Args:
            item: The item to purchase ("water", "plants", "trees", or "sunlight")

        Returns:
            A tuple of (success: bool, message: str)
        """
        if item not in SHOP_PRICES:
            return (False, f"Cannot purchase {item}.")
        
        price = SHOP_PRICES[item]
        inv = self.data.setdefault("inventory", default_inventory())
        current_coins = int(inv.get("coins", 0))
        
        if current_coins < price:
            return (False, f"Not enough coins. Need {price} coins to purchase {item}.")
        
        # Spend coins and award the item
        inv["coins"] = current_coins - price
        inv[item] = int(inv.get(item, 0)) + 1
        self._save()
        return (True, f"Purchased 1 {item} for {price} coins.")

    # ------------------------------------------------------------------
    # Garden operations
    # ------------------------------------------------------------------
    def row_col_to_index(self, row: int, col: int) -> Optional[int]:
        """Convert (row, col) to a tile index, returning None if out of bounds."""

        if row < 0 or col < 0:
            return None
        if row >= GARDEN_HEIGHT or col >= GARDEN_WIDTH:
            return None
        return row * GARDEN_WIDTH + col

    def index_to_row_col(self, idx: int) -> Tuple[int, int]:
        """Convert a tile index to (row, col)."""

        return divmod(int(idx), GARDEN_WIDTH)

    def _first_empty_index(self) -> Optional[int]:
        """Return the index of the first empty tile, or None if full."""

        tiles = self.get_tiles()
        for idx, tile in enumerate(tiles):
            if tile is None:
                return idx
        return None

    def _create_tile(self, kind: str, row: int, col: int) -> Dict[str, Any]:
        """Create a new tile dict for the given kind ('plant', 'tree', or 'seed')."""

        now = utc_now()
        iso_now = to_iso(now)
        tile = {
            "id": str(uuid.uuid4()),
            "kind": kind,
            "planted_at": iso_now,
            "last_watered_at": iso_now,
            "bloom_until": None,
            "row": int(row),
            "col": int(col),
        }
        # For seeds, track evolution stage
        if kind == "seed":
            tile["evolution_stage"] = "seed"
        return tile

    def place_at_index(self, kind: str, idx: int) -> Optional[Dict[str, Any]]:
        """Place an item at a specific tile index (if empty) and spend inventory.

        For trees (2x2), checks that all 4 tiles are empty.
        Returns the created tile dict on success, or None on failure.
        """

        if kind not in ("plant", "tree", "seed"):
            return None
        tiles = self.get_tiles()
        if idx < 0 or idx >= len(tiles):
            return None
        
        row, col = self.index_to_row_col(idx)
        
        # For trees (2x2), check all 4 tiles are empty and within bounds
        if kind == "tree":
            if row < 0 or col < 0 or row >= GARDEN_HEIGHT - 1 or col >= GARDEN_WIDTH - 1:
                return None
            for dr in range(2):
                for dc in range(2):
                    check_idx = self.row_col_to_index(row + dr, col + dc)
                    if check_idx is None or tiles[check_idx] is not None:
                        return None
        else:
            # Plant: check single tile
            if tiles[idx] is not None:
                return None

        # Determine inventory key
        if kind == "plant":
            inv_key = "plants"
        elif kind == "tree":
            inv_key = "trees"
        elif kind == "seed":
            inv_key = "seeds"
        else:
            return None
        
        inv = self.data.setdefault("inventory", default_inventory())
        if int(inv.get(inv_key, 0)) <= 0:
            return None

        tile = self._create_tile(kind, row=row, col=col)
        tiles[idx] = tile
        inv[inv_key] = int(inv.get(inv_key, 0)) - 1
        self._save()
        return tile

    def place_at(self, kind: str, row: int, col: int) -> Optional[Dict[str, Any]]:
        """Place an item at (row, col). Returns tile dict on success."""

        idx = self.row_col_to_index(row, col)
        if idx is None:
            return None
        return self.place_at_index(kind, idx)

    def move_tile(self, from_idx: int, to_idx: int) -> bool:
        """Move a tile from one index to another (to must be empty).

        For trees (2x2), checks that all 4 destination tiles are empty.
        Persists immediately on success.
        """

        tiles = self.get_tiles()
        if (
            from_idx < 0
            or to_idx < 0
            or from_idx >= len(tiles)
            or to_idx >= len(tiles)
            or from_idx == to_idx
        ):
            return False
        if tiles[from_idx] is None:
            return False
        
        tile = tiles[from_idx]
        kind = tile.get("kind") if isinstance(tile, dict) else None
        
        to_row, to_col = self.index_to_row_col(to_idx)
        
        # For trees and cherry blossoms (2x2), check all 4 destination tiles are empty and within bounds
        if kind in ("tree", "cherry_blossom"):
            if to_row < 0 or to_col < 0 or to_row >= GARDEN_HEIGHT - 1 or to_col >= GARDEN_WIDTH - 1:
                return False
            
            # For cherry blossoms, we need to clear all reference tiles first
            if kind == "cherry_blossom":
                main_id = tile.get("id")
                for t_idx, t in enumerate(tiles):
                    if t is not None and t.get("id") == main_id and t.get("is_reference"):
                        tiles[t_idx] = None
            
            for dr in range(2):
                for dc in range(2):
                    check_idx = self.row_col_to_index(to_row + dr, to_col + dc)
                    if check_idx is None:
                        return False
                    # Allow if it's the source tile (we're moving from there)
                    if check_idx != from_idx and tiles[check_idx] is not None:
                        return False
            
            # For cherry blossoms, recreate reference tiles at new location
            if kind == "cherry_blossom":
                main_id = tile.get("id")
                color = tile.get("color")
                evolution_stage = tile.get("evolution_stage")
                planted_at = tile.get("planted_at")
                last_watered_at = tile.get("last_watered_at")
                bloom_until = tile.get("bloom_until")
                
                for dr in range(2):
                    for dc in range(2):
                        check_idx = self.row_col_to_index(to_row + dr, to_col + dc)
                        if check_idx != to_idx:
                            tiles[check_idx] = {
                                "id": main_id,
                                "kind": "cherry_blossom",
                                "evolution_stage": evolution_stage,
                                "color": color,
                                "planted_at": planted_at,
                                "last_watered_at": last_watered_at,
                                "bloom_until": bloom_until,
                                "row": to_row + dr,
                                "col": to_col + dc,
                                "is_reference": True,
                            }
        else:
            # Plant, seed, colorful_plant: check single destination tile
            if tiles[to_idx] is not None:
                return False

        tiles[to_idx] = tile
        tiles[from_idx] = None

        if isinstance(tile, dict):
            tile["row"] = int(to_row)
            tile["col"] = int(to_col)

        self._save()
        return True

    def place_plant(self) -> bool:
        """Place a plant in the first empty tile if inventory allows.

        Returns True on success, False if no inventory or no space.
        """

        idx = self._first_empty_index()
        if idx is None:
            return False
        return self.place_at_index("plant", idx) is not None

    def place_tree(self) -> bool:
        """Place a tree in the first empty tile if inventory allows.

        Returns True on success, False if no inventory or no space.
        """

        idx = self._first_empty_index()
        if idx is None:
            return False
        return self.place_at_index("tree", idx) is not None

    def water_all(self) -> bool:
        """Water all non-empty, non-dead tiles, costing 1 water.

        Returns True if at least one tile was watered and the cost paid.
        Dead items are skipped and cannot be revived.
        """

        tiles = self.get_tiles()
        now = utc_now()
        has_living = False
        for tile in tiles:
            if tile is not None:
                status = self.tile_status(tile, now)
                if not status.is_dead:
                    has_living = True
                    break
        
        if not has_living:
            return False

        if not self.spend_token("water", 1):
            return False

        iso_now = to_iso(now)
        for tile in tiles:
            if tile is not None:
                status = self.tile_status(tile, now)
                # Only water living items
                if not status.is_dead:
                    tile["last_watered_at"] = iso_now
        self._save()
        return True

    def apply_sunlight(self) -> bool:
        """Apply sunlight to all non-empty, non-dead tiles, costing 1 sunlight.

        Returns True if at least one tile was affected and the cost paid.
        Dead items are skipped and cannot be revived.
        """

        tiles = self.get_tiles()
        now = utc_now()
        has_living = False
        for tile in tiles:
            if tile is not None:
                status = self.tile_status(tile, now)
                if not status.is_dead:
                    has_living = True
                    break
        
        if not has_living:
            return False

        if not self.spend_token("sunlight", 1):
            return False

        until = utc_now() + timedelta(days=1)
        iso_until = to_iso(until)
        for tile in tiles:
            if tile is not None:
                status = self.tile_status(tile, now)
                # Only apply sunlight to living items
                if not status.is_dead:
                    tile["bloom_until"] = iso_until
        self._save()
        return True

    def clear_dead(self) -> bool:
        """Remove all dead items from the garden.

        Returns True if any tiles were cleared.
        """

        tiles = self.get_tiles()
        now = utc_now()
        changed = False
        for idx, tile in enumerate(tiles):
            if tile is None:
                continue
            status = self.tile_status(tile, now)
            if status.is_dead:
                tiles[idx] = None
                changed = True
                # Also clear reference tiles for trees/cherry blossoms
                if tile.get("kind") in ("tree", "cherry_blossom"):
                    main_id = tile.get("id")
                    for t_idx, t in enumerate(tiles):
                        if t is not None and t.get("id") == main_id and t.get("is_reference"):
                            tiles[t_idx] = None
        if changed:
            self._save()
        return changed
    
    # ------------------------------------------------------------------
    # Path operations
    # ------------------------------------------------------------------
    def get_paths(self) -> List[tuple[int, int, str]]:
        """Get all paths as a list of (row, col, direction) tuples.
        
        Direction is one of: "n" (north), "s" (south), "e" (east), "w" (west)
        """
        return self.data.get("paths", [])
    
    def place_path(self, row: int, col: int, direction: str) -> tuple[bool, str]:
        """Place a path on an edge.
        
        Args:
            row: Row of the tile
            col: Column of the tile
            direction: "n", "s", "e", or "w" (north, south, east, west)
        
        Returns:
            (success: bool, message: str)
        """
        # Validate direction
        if direction not in ("n", "s", "e", "w"):
            return (False, f"Invalid direction: {direction}")
        
        # Validate tile position
        if row < 0 or row >= GARDEN_HEIGHT or col < 0 or col >= GARDEN_WIDTH:
            return (False, "Invalid tile position")
        
        # Check if path already exists
        paths = self.get_paths()
        path_key = (row, col, direction)
        if path_key in paths:
            return (False, "Path already exists on this edge")
        
        # Check inventory
        if not self.spend_token("path", 1):
            return (False, "No paths in inventory")
        
        # Add path
        paths.append(path_key)
        self.data["paths"] = paths
        self._save()
        return (True, "Path placed successfully")
    
    def remove_path(self, row: int, col: int, direction: str) -> bool:
        """Remove a path from an edge.
        
        Returns True if path was removed, False if it didn't exist.
        """
        paths = self.get_paths()
        path_key = (row, col, direction)
        if path_key in paths:
            paths.remove(path_key)
            self.data["paths"] = paths
            # Return path to inventory
            self.award_token("path", 1)
            self._save()
            return True
        return False
    
    # ------------------------------------------------------------------
    # Object removal operations
    # ------------------------------------------------------------------
    def remove_object_at_index(self, idx: int) -> tuple[bool, str]:
        """Remove an object at the given tile index and return it to inventory.
        
        Returns (success: bool, message: str)
        """
        tiles = self.get_tiles()
        if idx < 0 or idx >= len(tiles):
            return (False, "Invalid tile index")
        
        tile = tiles[idx]
        if tile is None:
            return (False, "No object at this location")
        
        # Skip reference tiles (part of 2x2 objects)
        if tile.get("is_reference"):
            return (False, "Cannot remove reference tile")
        
        kind = tile.get("kind", "plant")
        
        # Handle different object types
        if kind == "plant":
            tiles[idx] = None
            self.award_token("plants", 1)
            self._save()
            return (True, "Plant removed and returned to inventory")
        
        elif kind == "tree":
            # Remove all 4 tiles of the tree
            main_id = tile.get("id")
            tiles[idx] = None
            # Remove reference tiles
            for t_idx, t in enumerate(tiles):
                if t is not None and t.get("id") == main_id and t.get("is_reference"):
                    tiles[t_idx] = None
            self.award_token("trees", 1)
            self._save()
            return (True, "Tree removed and returned to inventory")
        
        elif kind == "seed":
            tiles[idx] = None
            self.award_token("seeds", 1)
            self._save()
            return (True, "Seed removed and returned to inventory")
        
        elif kind == "colorful_plant":
            tiles[idx] = None
            self.award_token("seeds", 1)  # Return as seed
            self._save()
            return (True, "Colorful plant removed, seed returned to inventory")
        
        elif kind == "cherry_blossom":
            # Remove all 4 tiles of the cherry blossom
            main_id = tile.get("id")
            tiles[idx] = None
            # Remove reference tiles
            for t_idx, t in enumerate(tiles):
                if t is not None and t.get("id") == main_id and t.get("is_reference"):
                    tiles[t_idx] = None
            self.award_token("seeds", 1)  # Return as seed
            self._save()
            return (True, "Cherry blossom removed, seed returned to inventory")
        
        else:
            return (False, f"Cannot remove object of type: {kind}")

    def _find_tree_at_tile(self, row: int, col: int) -> Optional[int]:
        """Find the top-left tile index of a tree or cherry blossom that occupies the given (row, col).

        Returns the tile index of the tree's/cherry blossom's top-left tile, or None if not found.
        """
        tiles = self.get_tiles()
        # Check if this tile itself is a tree or cherry blossom
        idx = self.row_col_to_index(row, col)
        if idx is not None and idx < len(tiles):
            tile = tiles[idx]
            if tile is not None and tile.get("kind") in ("tree", "cherry_blossom") and not tile.get("is_reference"):
                return idx
        
        # Check if this tile is part of a tree or cherry blossom (check tiles to the left/above)
        for dr in range(2):
            for dc in range(2):
                check_row = row - dr
                check_col = col - dc
                check_idx = self.row_col_to_index(check_row, check_col)
                if check_idx is not None and check_idx < len(tiles):
                    tile = tiles[check_idx]
                    if tile is not None and tile.get("kind") in ("tree", "cherry_blossom") and not tile.get("is_reference"):
                        # Verify this tree/cherry blossom occupies the target tile
                        tile_row, tile_col = self.index_to_row_col(check_idx)
                        if (tile_row <= row < tile_row + 2 and 
                            tile_col <= col < tile_col + 2):
                            return check_idx
        return None

    def water_tile(self, row: int, col: int) -> tuple[bool, str]:
        """Water a specific tile.

        For plants, seeds, colorful_plants: costs 1 water.
        For trees, cherry_blossoms: costs 4 water (any of its 4 tiles can be clicked).
        Returns (success: bool, message: str).
        """
        idx = self.row_col_to_index(row, col)
        if idx is None:
            return (False, "Invalid tile position.")
        
        tiles = self.get_tiles()
        if idx >= len(tiles):
            return (False, "Invalid tile position.")
        
        tile = tiles[idx]
        if tile is None:
            return (False, "No plant, seed, or tree at this tile.")
        
        # Skip reference tiles, find the main tile
        if tile.get("is_reference"):
            # Find the main tile by ID
            main_id = tile.get("id")
            for t_idx, t in enumerate(tiles):
                if t is not None and t.get("id") == main_id and not t.get("is_reference"):
                    tile = t
                    idx = t_idx
                    break
        
        now = utc_now()
        status = self.tile_status(tile, now)
        
        # Dead items cannot be watered
        if status.is_dead:
            return (False, "This item is dead and cannot be revived.")
        
        kind = tile.get("kind")
        water_cost = 4 if kind in ("tree", "cherry_blossom") else 1
        
        # For trees and cherry blossoms, find the main tile
        if kind in ("tree", "cherry_blossom"):
            tree_idx = self._find_tree_at_tile(row, col)
            if tree_idx is None:
                return (False, f"Could not find {kind} at this position.")
            tile = tiles[tree_idx]
        
        # Check if we have enough water
        inv = self.data.setdefault("inventory", default_inventory())
        current_water = int(inv.get("water", 0))
        if current_water < water_cost:
            return (False, f"Not enough water. Need {water_cost} water to water this {kind}.")
        
        # Spend water and update timestamp
        inv["water"] = current_water - water_cost
        iso_now = to_iso(now)
        tile["last_watered_at"] = iso_now
        
        self._save()
        return (True, f"Watered {kind} (used {water_cost} water).")

    def fast_forward_time(self, days: int = 1) -> bool:
        """Advance time by the specified number of days for testing.

        Subtracts the specified days from all timestamps (making items older).
        Returns True if any tiles were modified.
        """

        tiles = self.get_tiles()
        changed = False
        delta = timedelta(days=days)

        for tile in tiles:
            if tile is None:
                continue

            # Make last_watered_at older (subtract days)
            last_watered_str = tile.get("last_watered_at")
            if last_watered_str:
                last_watered = from_iso(last_watered_str)
                if last_watered:
                    new_watered = last_watered - delta
                    tile["last_watered_at"] = to_iso(new_watered)
                    changed = True

            # Make planted_at older
            planted_str = tile.get("planted_at")
            if planted_str:
                planted = from_iso(planted_str)
                if planted:
                    new_planted = planted - delta
                    tile["planted_at"] = to_iso(new_planted)
                    changed = True

            # Make bloom_until older (if it exists)
            bloom_str = tile.get("bloom_until")
            if bloom_str:
                bloom_until = from_iso(bloom_str)
                if bloom_until:
                    new_bloom = bloom_until - delta
                    tile["bloom_until"] = to_iso(new_bloom)
                    changed = True

        if changed:
            self._save()
        return changed

    # ------------------------------------------------------------------
    # Tile lifecycle logic
    # ------------------------------------------------------------------
    def _evolve_tile_if_needed(self, tile: Dict[str, Any], idx: int) -> bool:
        """Check if a tile should evolve and perform evolution if needed.
        
        Returns True if evolution occurred, False otherwise.
        """
        now = utc_now()
        kind = tile.get("kind")
        evolution_stage = tile.get("evolution_stage", "seed" if kind == "seed" else None)
        planted_at = from_iso(tile.get("planted_at") or "")
        last_watered_at = from_iso(tile.get("last_watered_at") or "")
        
        if planted_at is None or last_watered_at is None:
            return False
        
        # Check if tile is dead - don't evolve dead tiles
        delta_water = now - last_watered_at
        if delta_water > timedelta(days=2):
            return False
        
        # Check time since planted
        delta_planted = now - planted_at
        
        # Seed -> Colorful Plant (1 week)
        if kind == "seed" and evolution_stage == "seed" and delta_planted >= timedelta(days=7):
            # Assign random color
            color = random.choice(COLORFUL_PLANT_COLORS)
            tile["kind"] = "colorful_plant"
            tile["evolution_stage"] = "colorful_plant"
            tile["color"] = color
            # Reset planted_at to track colorful plant age
            tile["planted_at"] = to_iso(now)
            self._save()
            return True
        
        # Colorful Plant -> Cherry Blossom (1 week)
        if kind == "colorful_plant" and evolution_stage == "colorful_plant" and delta_planted >= timedelta(days=7):
            color = tile.get("color")
            if color is None:
                return False
            
            # Cherry blossoms are 2x2 like trees
            row, col = self.index_to_row_col(idx)
            if row < 0 or col < 0 or row >= GARDEN_HEIGHT - 1 or col >= GARDEN_WIDTH - 1:
                return False
            
            tiles = self.get_tiles()
            # Check all 4 tiles are available (current tile + 3 neighbors)
            occupied = []
            for dr in range(2):
                for dc in range(2):
                    check_idx = self.row_col_to_index(row + dr, col + dc)
                    if check_idx is None:
                        return False
                    if check_idx != idx and tiles[check_idx] is not None:
                        occupied.append(check_idx)
            
            if occupied:
                return False
            
            # Transform to cherry blossom (2x2)
            tile["kind"] = "cherry_blossom"
            tile["evolution_stage"] = "cherry_blossom"
            # Keep the color
            # Reset planted_at to track cherry blossom age
            tile["planted_at"] = to_iso(now)
            
            # Mark all 4 tiles as part of the cherry blossom
            for dr in range(2):
                for dc in range(2):
                    check_idx = self.row_col_to_index(row + dr, col + dc)
                    if check_idx != idx:
                        # Create a reference tile pointing to the main tile
                        tiles[check_idx] = {
                            "id": tile["id"],  # Same ID
                            "kind": "cherry_blossom",
                            "evolution_stage": "cherry_blossom",
                            "color": color,
                            "planted_at": tile["planted_at"],
                            "last_watered_at": tile["last_watered_at"],
                            "bloom_until": tile.get("bloom_until"),
                            "row": row + dr,
                            "col": col + dc,
                            "is_reference": True,  # Mark as reference tile
                        }
            
            self._save()
            return True
        
        return False
    
    def tile_status(
        self, tile: Optional[Dict[str, Any]], now: Optional[datetime] = None
    ) -> TileStatus:
        """Compute lifecycle status flags for a tile."""

        status = TileStatus()
        if tile is None:
            return status

        status.is_empty = False
        if now is None:
            now = utc_now()

        # Bloom status
        bloom_until = from_iso(tile.get("bloom_until") or "")
        if bloom_until and bloom_until > now:
            status.is_blooming = True

        # Watering / death
        last_watered = from_iso(tile.get("last_watered_at") or "")
        if last_watered is None:
            # No watering info: treat as dead for safety.
            status.is_dead = True
            return status

        delta = now - last_watered
        kind = tile.get("kind")

        # Dead / wilt thresholds
        if kind == "plant":
            # Plants:
            # - 0–1 days: healthy
            # - 1–2 days: wilt level 1 (current wilt colour)
            # - 2–3 days: wilt level 2 (darker, more brown)
            # - >3 days: dead
            if delta > timedelta(days=3):
                status.is_dead = True
            elif delta >= timedelta(days=2):
                status.is_wilted = True
                status.wilt_level = 2
            elif delta >= timedelta(days=1):
                status.is_wilted = True
                status.wilt_level = 1
        elif kind == "tree":
            # Trees: keep existing thresholds
            if delta > timedelta(days=2):
                status.is_dead = True
            elif delta >= timedelta(days=1):
                status.is_wilted = True
        elif kind in ("seed", "colorful_plant", "cherry_blossom"):
            # Seeds, colorful plants, and cherry blossoms:
            # - 0–1 days: healthy
            # - 1–2 days: wilted
            # - >2 days: dead
            if delta > timedelta(days=2):
                status.is_dead = True
            elif delta >= timedelta(days=1):
                status.is_wilted = True
                status.wilt_level = 1

        return status


