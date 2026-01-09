"""Qt6 UI for the AnkiGarden garden dialog."""

from __future__ import annotations

from aqt import mw
from aqt.qt import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    Qt,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import tooltip

from .constants import AESTHETIC_MODES, SHOP_PRICES, THEME_UNLOCK_PRICE
from .garden_scene import GardenView
from .state import AddonState


class GardenDialog(QDialog):
    """Main dialog showing the AnkiGarden garden and inventory."""

    def __init__(self, state: AddonState, parent=None) -> None:
        super().__init__(parent or mw)
        self.state = state

        self.setWindowTitle("AnkiGarden")
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Create all widgets and layouts."""

        main_layout = QVBoxLayout(self)

        # Inventory group (with theme selector)
        inv_group = QGroupBox("Inventory")
        inv_layout = QHBoxLayout(inv_group)
        self.water_label = QLabel()
        self.plants_label = QLabel()
        self.trees_label = QLabel()
        self.sunlight_label = QLabel()
        self.coins_label = QLabel()
        self.seeds_label = QLabel()
        self.path_label = QLabel()

        # Make inventory visually richer (emojis + spacing)
        # Styling will be set in _refresh_inventory to include spacing

        # Add Read Instructions button on the left side
        self.read_instructions_btn = QPushButton("Read Instructions")
        self.read_instructions_btn.clicked.connect(self.on_read_instructions)
        self.read_instructions_btn.setStyleSheet("QPushButton { background-color: #4A90E2; color: white; font-weight: bold; }")
        inv_layout.addWidget(self.read_instructions_btn)
        inv_layout.addWidget(QLabel(" | "))  # Separator
        
        inv_layout.addStretch(1)
        inv_layout.addWidget(self.water_label)
        inv_layout.addWidget(self.plants_label)
        inv_layout.addWidget(self.trees_label)
        inv_layout.addWidget(self.sunlight_label)
        inv_layout.addWidget(self.coins_label)
        inv_layout.addWidget(self.seeds_label)
        inv_layout.addWidget(self.path_label)
        
        # Add theme selector to inventory section
        inv_layout.addWidget(QLabel(" | "))  # Separator
        theme_label = QLabel("Theme:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Default",
            "Night Garden",
            "Summer Garden",
            "Winter Garden",
            "Spring Garden",
            "Autumn Garden",
        ])
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        inv_layout.addWidget(theme_label)
        inv_layout.addWidget(self.mode_combo)
        inv_layout.addStretch(1)
        main_layout.addWidget(inv_group)

        # Shop group (with theme unlocks) - create buttons first
        self.buy_water_btn = QPushButton(f"Buy Water ({SHOP_PRICES['water']} coins)")
        self.buy_plant_btn = QPushButton(f"Buy Plant ({SHOP_PRICES['plants']} coins)")
        self.buy_tree_btn = QPushButton(f"Buy Tree ({SHOP_PRICES['trees']} coins)")
        self.buy_sunlight_btn = QPushButton(f"Buy Sunlight ({SHOP_PRICES['sunlight']} coins)")
        self.buy_seed_btn = QPushButton(f"Buy Seed ({SHOP_PRICES['seeds']} coins)")
        
        self.buy_water_btn.clicked.connect(lambda: self.on_purchase("water"))
        self.buy_plant_btn.clicked.connect(lambda: self.on_purchase("plants"))
        self.buy_tree_btn.clicked.connect(lambda: self.on_purchase("trees"))
        self.buy_sunlight_btn.clicked.connect(lambda: self.on_purchase("sunlight"))
        self.buy_seed_btn.clicked.connect(lambda: self.on_purchase("seeds"))
        self.buy_path_btn = QPushButton(f"Buy Path ({SHOP_PRICES['path']} coins)")
        self.buy_path_btn.clicked.connect(lambda: self.on_purchase("path"))
        
        # Shop group (with theme unlocks)
        shop_group = QGroupBox("Shop")
        shop_layout = QVBoxLayout(shop_group)
        
        # Items shop
        items_shop_layout = QHBoxLayout()
        items_shop_layout.addStretch(1)
        items_shop_layout.addWidget(self.buy_water_btn)
        items_shop_layout.addWidget(self.buy_plant_btn)
        items_shop_layout.addWidget(self.buy_tree_btn)
        items_shop_layout.addWidget(self.buy_sunlight_btn)
        items_shop_layout.addWidget(self.buy_seed_btn)
        items_shop_layout.addWidget(self.buy_path_btn)
        items_shop_layout.addStretch(1)
        shop_layout.addLayout(items_shop_layout)
        
        # Theme unlocks shop
        themes_shop_layout = QHBoxLayout()
        themes_shop_layout.addStretch(1)
        themes_shop_layout.addWidget(QLabel("Unlock Themes:"))
        self.unlock_night_btn = QPushButton(f"Unlock Night ({THEME_UNLOCK_PRICE} coins)")
        self.unlock_summer_btn = QPushButton(f"Unlock Summer ({THEME_UNLOCK_PRICE} coins)")
        self.unlock_winter_btn = QPushButton(f"Unlock Winter ({THEME_UNLOCK_PRICE} coins)")
        self.unlock_spring_btn = QPushButton(f"Unlock Spring ({THEME_UNLOCK_PRICE} coins)")
        self.unlock_autumn_btn = QPushButton(f"Unlock Autumn ({THEME_UNLOCK_PRICE} coins)")
        
        self.unlock_night_btn.clicked.connect(lambda: self.on_unlock_theme("night"))
        self.unlock_summer_btn.clicked.connect(lambda: self.on_unlock_theme("summer"))
        self.unlock_winter_btn.clicked.connect(lambda: self.on_unlock_theme("winter"))
        self.unlock_spring_btn.clicked.connect(lambda: self.on_unlock_theme("spring"))
        self.unlock_autumn_btn.clicked.connect(lambda: self.on_unlock_theme("autumn"))
        
        themes_shop_layout.addWidget(self.unlock_night_btn)
        themes_shop_layout.addWidget(self.unlock_summer_btn)
        themes_shop_layout.addWidget(self.unlock_winter_btn)
        themes_shop_layout.addWidget(self.unlock_spring_btn)
        themes_shop_layout.addWidget(self.unlock_autumn_btn)
        themes_shop_layout.addStretch(1)
        shop_layout.addLayout(themes_shop_layout)
        
        main_layout.addWidget(shop_group)

        # Main content area: Actions on left, Garden on right
        content_layout = QHBoxLayout()
        
        # Actions group (on the left)
        btn_group = QGroupBox("Actions")
        btn_layout = QVBoxLayout(btn_group)  # Vertical layout for buttons

        self.place_plant_btn = QPushButton("Place Plant")
        self.place_tree_btn = QPushButton("Place Tree")
        self.place_seed_btn = QPushButton("Place Seed")
        self.place_path_btn = QPushButton("Place Path")
        self.water_garden_btn = QPushButton("Water Garden")
        self.sunlight_btn = QPushButton("Apply Sunlight")
        self.remove_object_btn = QPushButton("Remove Object")
        self.clear_dead_btn = QPushButton("Clear Dead")
        self.fast_forward_btn = QPushButton("Fast Forward 1 Day")

        self.place_plant_btn.clicked.connect(self.on_place_plant)
        self.place_tree_btn.clicked.connect(self.on_place_tree)
        self.place_seed_btn.clicked.connect(self.on_place_seed)
        self.place_path_btn.clicked.connect(self.on_place_path)
        self.water_garden_btn.clicked.connect(self.on_water_garden)
        self.sunlight_btn.clicked.connect(self.on_apply_sunlight)
        self.remove_object_btn.clicked.connect(self.on_remove_object)
        self.clear_dead_btn.clicked.connect(self.on_clear_dead)
        self.fast_forward_btn.clicked.connect(self.on_fast_forward)

        # Make action buttons colorful
        self.place_plant_btn.setStyleSheet("QPushButton { background-color: #006400; color: white; font-weight: bold; }")
        self.place_tree_btn.setStyleSheet("QPushButton { background-color: #8B4513; color: white; font-weight: bold; }")
        self.place_seed_btn.setStyleSheet("QPushButton { background-color: #DAA520; font-weight: bold; }")
        self.place_path_btn.setStyleSheet("QPushButton { background-color: #A9A9A9; font-weight: bold; }")
        self.water_garden_btn.setStyleSheet("QPushButton { background-color: #4169E1; color: white; font-weight: bold; }")
        self.sunlight_btn.setStyleSheet("QPushButton { background-color: #CC5500; color: white; font-weight: bold; }")
        self.remove_object_btn.setStyleSheet("QPushButton { background-color: #FF6347; color: white; font-weight: bold; }")
        self.clear_dead_btn.setStyleSheet("QPushButton { background-color: #696969; color: white; font-weight: bold; }")
        self.fast_forward_btn.setStyleSheet("QPushButton { background-color: #9370DB; color: white; font-weight: bold; }")

        btn_layout.addWidget(self.place_plant_btn)
        btn_layout.addWidget(self.place_tree_btn)
        btn_layout.addWidget(self.place_seed_btn)
        btn_layout.addWidget(self.place_path_btn)
        btn_layout.addWidget(self.water_garden_btn)
        btn_layout.addWidget(self.sunlight_btn)
        btn_layout.addWidget(self.remove_object_btn)
        btn_layout.addWidget(self.clear_dead_btn)
        btn_layout.addWidget(self.fast_forward_btn)
        
        # Hide fast forward button initially
        self.fast_forward_btn.hide()
        self._fast_forward_enabled = False
        
        # Add emoji indicator for active modes
        self.mode_indicator_label = QLabel()
        self.mode_indicator_label.setStyleSheet("font-size: 24pt;")
        self.mode_indicator_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(self.mode_indicator_label)
        btn_layout.addStretch(1)
        
        self._watering_mode_active = False
        self._path_placement_mode_active = False
        self._remove_mode_active = False
        content_layout.addWidget(btn_group)

        # Garden (graphics view) - on the right
        grid_group = QGroupBox("Garden")
        grid_layout = QVBoxLayout(grid_group)
        self.garden_view = GardenView(self.state, grid_group)
        self.garden_view.stateChanged.connect(self.refresh)
        # Pass dialog reference to garden view for special tile click handling
        self.garden_view.set_dialog_reference(self)
        grid_layout.addWidget(self.garden_view)
        content_layout.addWidget(grid_group, stretch=1)  # Garden takes remaining space
        
        main_layout.addLayout(content_layout)

        # Close button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        main_layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def on_place_plant(self) -> None:
        if not self.garden_view.begin_place("plant"):
            tooltip(
                "Cannot place plant (no plants in inventory).",
                parent=self,
            )
        self.refresh()

    def on_place_tree(self) -> None:
        if not self.garden_view.begin_place("tree"):
            tooltip(
                "Cannot place tree (no trees in inventory).",
                parent=self,
            )
        self.refresh()

    def on_place_seed(self) -> None:
        if not self.garden_view.begin_place("seed"):
            tooltip(
                "Cannot place seed (no seeds in inventory).",
                parent=self,
            )
        self.refresh()

    def on_place_path(self) -> None:
        """Toggle path placement mode."""
        # Check if we have paths before toggling
        inv = self.state.get_inventory()
        if inv.get("path", 0) <= 0 and not self._path_placement_mode_active:
            tooltip(
                "Cannot place path (no paths in inventory).",
                parent=self,
            )
            return
        
        self._path_placement_mode_active = not self._path_placement_mode_active
        self.garden_view.garden_scene.set_path_placement_mode(self._path_placement_mode_active)
        
        if self._path_placement_mode_active:
            self.place_path_btn.setText("Exit Path Placing")
            tooltip("🪨 PATH PLACEMENT MODE: Click near edges between tiles to place paths.", parent=self)
        else:
            self.place_path_btn.setText("Place Path")
            tooltip("Path placement mode cancelled.", parent=self)
        self.refresh()

    def on_remove_object(self) -> None:
        """Toggle remove object mode."""
        self._remove_mode_active = not self._remove_mode_active
        self.garden_view.set_remove_mode(self._remove_mode_active)
        
        if self._remove_mode_active:
            self.remove_object_btn.setText("Exit Removing")
            tooltip("🗑️ REMOVE MODE: Click on objects to remove them and return to inventory.", parent=self)
        else:
            self.remove_object_btn.setText("Remove Object")
            tooltip("Remove mode cancelled.", parent=self)
        self.refresh()

    def on_water_garden(self) -> None:
        """Toggle watering mode - click tiles to water them individually."""
        self._watering_mode_active = not self._watering_mode_active
        self.garden_view.set_watering_mode(self._watering_mode_active)
        
        if self._watering_mode_active:
            self.water_garden_btn.setText("Exit Watering")
            tooltip("💧 WATERING MODE: Click on tiles to water them. Plants cost 1 water, trees cost 4 water.", parent=self)
        else:
            self.water_garden_btn.setText("Water Garden")
            tooltip("Watering mode cancelled.", parent=self)
        self.refresh()

    def on_apply_sunlight(self) -> None:
        did = self.state.apply_sunlight()
        if not did:
            tooltip(
                "Cannot apply sunlight (no sunlight tokens or no items in garden).",
                parent=self,
            )
        else:
            tooltip("Sunlight applied: everything is blooming!", parent=self)
        self.refresh()
        if did:
            self.garden_view.glow()

    def on_clear_dead(self) -> None:
        if not self.state.clear_dead():
            tooltip("No dead items to clear.", parent=self)
        else:
            tooltip("Cleared dead items from the garden.", parent=self)
        self.refresh()

    def on_fast_forward(self) -> None:
        """Fast forward time by 1 day for testing."""
        if not self.state.fast_forward_time(1):
            tooltip("No items to age.", parent=self)
        else:
            tooltip("Time advanced by 1 day.", parent=self)
        self.refresh()
    
    def toggle_fast_forward_button(self) -> None:
        """Toggle the visibility of the fast forward button."""
        self._fast_forward_enabled = not self._fast_forward_enabled
        if self._fast_forward_enabled:
            self.fast_forward_btn.show()
        else:
            self.fast_forward_btn.hide()

    def on_read_instructions(self) -> None:
        """Open a dialog with instructions on how to use AnkiGarden."""
        instructions_dialog = QDialog(self)
        instructions_dialog.setWindowTitle("AnkiGarden Instructions")
        instructions_dialog.setMinimumSize(600, 700)
        
        layout = QVBoxLayout(instructions_dialog)
        
        # Create text edit for instructions
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("font-size: 11pt; padding: 10px;")
        
        instructions = """
<h1>AnkiGarden - User Guide</h1>

<h2>Getting Started</h2>
<p>Welcome to AnkiGarden! This add-on lets you create and maintain a beautiful garden while you study with Anki. Your garden grows as you review cards correctly.</p>

<p><b>Starting Inventory:</b> You begin with 1 plant and 3 waters. Use these wisely to start your garden!</p>

<h2>How to Earn Rewards</h2>
<p>As you review cards in Anki, you'll earn rewards based on your streak of correct answers:</p>
<ul>
<li><b>15 cards correct in a row:</b> +1 Water</li>
<li><b>30 cards correct in a row:</b> +1 Plant</li>
<li><b>50 cards correct in a row:</b> +1 Tree</li>
</ul>
<p>You also earn 1 coin for every correct answer. Wrong answers reset your streak, so stay focused!</p>

<h2>Actions Section</h2>

<h3>🌱 Place Plant</h3>
<p>Click this button, then click on an empty tile in your garden to place a plant. Plants need to be watered regularly to stay healthy.</p>

<h3>🌳 Place Tree</h3>
<p>Trees are larger than plants and take up 2x2 tiles. Click this button, then click on an empty tile to place a tree. Trees require 4 water to water them.</p>

<h3>🌰 Place Seed</h3>
<p>Seeds are special! When you place a seed, it will evolve into a colorful plant after 1 week (if kept watered), and then into a cherry blossom tree after another week. Seeds are rare and valuable.</p>

<h3>🪨 Place Path</h3>
<p>Click this button to enter path placement mode. In this mode, click near the edges between tiles to place decorative paths. The button will change to "Exit Path Placing" while in this mode. Click it again to exit.</p>

<h3>💧 Water Garden</h3>
<p>Click this button to enter watering mode. In this mode, click on individual tiles to water them. Plants and seeds cost 1 water each, while trees cost 4 water. The button will change to "Exit Watering" while in this mode.</p>

<h3>☀️ Apply Sunlight</h3>
<p>This powerful action makes everything in your garden bloom for 1 day! It costs 1 sunlight token. Use it to make your garden beautiful and vibrant.</p>

<h3>🗑️ Remove Object</h3>
<p>Click this button to enter remove mode. In this mode, click on any object (plant, tree, seed, or path) to remove it and return it to your inventory. The button will change to "Exit Removing" while in this mode.</p>

<h3>Clear Dead</h3>
<p>Removes all dead items from your garden. Dead items cannot be revived, so make sure to water your plants regularly!</p>

<h2>Inventory Section</h2>
<p>The inventory shows all your current resources:</p>
<ul>
<li><b>💧 Water:</b> Used to water plants, trees, and seeds</li>
<li><b>🌱 Plants:</b> Can be placed in your garden</li>
<li><b>🌳 Trees:</b> Large 2x2 objects for your garden</li>
<li><b>☀️ Sunlight:</b> Makes everything bloom</li>
<li><b>🪙 Coins:</b> Used to purchase items in the shop</li>
<li><b>🌰 Seeds:</b> Evolve into colorful plants and cherry blossoms</li>
<li><b>🪨 Paths:</b> Decorative paths for your garden</li>
</ul>

<p>You can also change the theme of your garden using the theme selector. Some themes need to be unlocked first in the shop.</p>

<h2>Shop Section</h2>
<p>Use your coins to purchase items:</p>
<ul>
<li><b>Water:</b> 20 coins</li>
<li><b>Plant:</b> 50 coins</li>
<li><b>Tree:</b> 100 coins</li>
<li><b>Sunlight:</b> 200 coins</li>
<li><b>Seed:</b> 1000 coins</li>
<li><b>Path:</b> 20 coins</li>
</ul>

<p>You can also unlock new themes for 2000 coins each. Unlocked themes include Night Garden, Summer Garden, Winter Garden, Spring Garden, and Autumn Garden.</p>

<h2>Plant Lifecycle</h2>
<p>All plants, trees, and seeds need regular watering to stay healthy:</p>
<ul>
<li><b>Plants:</b> Need water every 1-2 days. After 3 days without water, they die.</li>
<li><b>Trees:</b> Need water every 1-2 days. After 2 days without water, they die.</li>
<li><b>Seeds:</b> Need water every 1-2 days. After 2 days without water, they die.</li>
</ul>

<p><b>Seed Evolution:</b> Seeds are special! If you keep a seed watered for 1 week, it will evolve into a colorful plant with vibrant flowers. If you keep that colorful plant watered for another week, it will evolve into a beautiful cherry blossom tree (2x2).</p>

<h2>Tips for Success</h2>
<ul>
<li>Water your plants regularly to keep them healthy</li>
<li>Use sunlight to make your garden bloom beautifully</li>
<li>Save up coins to purchase seeds - they're worth the investment!</li>
<li>Plan your garden layout before placing items</li>
<li>Use paths to create beautiful walkways through your garden</li>
<li>Try different themes to find your favorite aesthetic</li>
</ul>

<p><b>Happy Gardening!</b> 🌱🌳🌸</p>
"""
        
        text_edit.setHtml(instructions)
        layout.addWidget(text_edit)
        
        # Add close button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(instructions_dialog.reject)
        layout.addWidget(buttons)
        
        instructions_dialog.exec()

    def on_purchase(self, item: str) -> None:
        """Purchase an item with coins."""
        success, message = self.state.purchase_with_coins(item)
        tooltip(message, parent=self)
        self.refresh()

    def on_mode_changed(self, index: int) -> None:
        """Handle aesthetic mode change."""
        mode_map = {
            0: "default",
            1: "night",
            2: "summer",
            3: "winter",
            4: "spring",
            5: "autumn",
        }
        mode = mode_map.get(index, "default")
        
        # Check if theme is unlocked
        if not self.state.is_theme_unlocked(mode):
            tooltip(f"{mode.title()} theme is locked. Unlock it in the shop for {THEME_UNLOCK_PRICE} coins.", parent=self)
            # Reset to current mode
            self._refresh_mode_selector()
            return
        
        self.state.set_aesthetic_mode(mode)
        # Force immediate refresh of both items and background
        self.garden_view.refresh()
        # Also force a viewport update to ensure background is redrawn
        self.garden_view.viewport().update()
    
    def on_unlock_theme(self, mode: str) -> None:
        """Unlock a theme by spending coins."""
        success, message = self.state.unlock_theme(mode)
        tooltip(message, parent=self)
        if success:
            self.refresh()  # Refresh to update UI

    # ------------------------------------------------------------------
    # Refresh / rendering
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Refresh inventory labels and garden tile representations."""

        self._refresh_inventory()
        self._refresh_buttons()
        self._refresh_mode_selector()
        self.garden_view.refresh()
        
        # Update watering mode button text if needed
        if hasattr(self, '_watering_mode_active'):
            if self._watering_mode_active:
                self.water_garden_btn.setText("Exit Watering")
            else:
                self.water_garden_btn.setText("Water Garden")
        
        # Update path placement mode button text if needed
        if hasattr(self, '_path_placement_mode_active'):
            if self._path_placement_mode_active:
                self.place_path_btn.setText("Exit Path Placing")
            else:
                self.place_path_btn.setText("Place Path")
        
        # Update remove mode button text if needed
        if hasattr(self, '_remove_mode_active'):
            if self._remove_mode_active:
                self.remove_object_btn.setText("Exit Removing")
            else:
                self.remove_object_btn.setText("Remove Object")
        
        # Update mode indicator emoji
        self._update_mode_indicator()
    
    def _refresh_mode_selector(self) -> None:
        """Update the mode selector to reflect current state and unlock status."""
        if not hasattr(self, 'mode_combo'):
            return
        
        unlocked = self.state.get_unlocked_themes()
        mode = self.state.get_aesthetic_mode()
        mode_map = {
            "default": 0,
            "night": 1,
            "summer": 2,
            "winter": 3,
            "spring": 4,
            "autumn": 5,
        }
        
        # Block signals to avoid triggering on_mode_changed
        self.mode_combo.blockSignals(True)
        
        # Update enabled state for each theme
        for theme_mode, index in mode_map.items():
            if theme_mode == "default":
                # Default is always enabled
                self.mode_combo.setItemData(index, None)  # Clear any disabled state
            else:
                if theme_mode in unlocked:
                    # Unlocked: enable and show normal text
                    self.mode_combo.setItemData(index, None)
                    # Update text to remove lock indicator if present
                    theme_names = ["Default", "Night Garden", "Summer Garden", "Winter Garden", "Spring Garden", "Autumn Garden"]
                    self.mode_combo.setItemText(index, theme_names[index])
                else:
                    # Locked: disable and show lock indicator
                    theme_names = ["Default", "Night Garden", "Summer Garden", "Winter Garden", "Spring Garden", "Autumn Garden"]
                    self.mode_combo.setItemText(index, f"{theme_names[index]} 🔒")
                    # Note: Qt ComboBox doesn't have a direct way to disable individual items
                    # We'll handle this in on_mode_changed instead
        
        # Set current index
        index = mode_map.get(mode, 0)
        self.mode_combo.setCurrentIndex(index)
        self.mode_combo.blockSignals(False)

    def _refresh_inventory(self) -> None:
        inv = self.state.get_inventory()
        # Use emojis and bold labels for a more playful, readable inventory.
        # Add spacing between distinct objects
        self.water_label.setText(f"💧 <b>Water:</b> {inv['water']}")
        self.plants_label.setText(f"🌱 <b>Plants:</b> {inv['plants']}")
        self.trees_label.setText(f"🌳 <b>Trees:</b> {inv['trees']}")
        self.sunlight_label.setText(f"☀️ <b>Sunlight:</b> {inv['sunlight']}")
        self.coins_label.setText(f"🪙 <b>Coins:</b> {inv['coins']}")
        self.seeds_label.setText(f"🌰 <b>Seeds:</b> {inv['seeds']}")
        self.path_label.setText(f"🪨 <b>Paths:</b> {inv.get('path', 0)}")
        
        # Add spacing between inventory items
        for label in [self.water_label, self.plants_label, self.trees_label, 
                      self.sunlight_label, self.coins_label, self.seeds_label, self.path_label]:
            label.setStyleSheet("font-size: 12pt; margin-right: 15px;")

    def _update_mode_indicator(self) -> None:
        """Update the emoji indicator based on active mode."""
        if not hasattr(self, 'mode_indicator_label'):
            return
        
        if hasattr(self, '_path_placement_mode_active') and self._path_placement_mode_active:
            self.mode_indicator_label.setText("🪨")
            self.mode_indicator_label.show()
        elif hasattr(self, '_watering_mode_active') and self._watering_mode_active:
            self.mode_indicator_label.setText("💧")
            self.mode_indicator_label.show()
        elif hasattr(self, '_remove_mode_active') and self._remove_mode_active:
            self.mode_indicator_label.setText("🗑️")
            self.mode_indicator_label.show()
        else:
            self.mode_indicator_label.setText("")
            self.mode_indicator_label.hide()

    def _refresh_buttons(self) -> None:
        inv = self.state.get_inventory()
        unlocked = self.state.get_unlocked_themes()
        
        self.place_plant_btn.setEnabled(inv["plants"] > 0)
        self.place_tree_btn.setEnabled(inv["trees"] > 0)
        self.place_seed_btn.setEnabled(inv["seeds"] > 0)
        self.place_path_btn.setEnabled(inv.get("path", 0) > 0)
        self.water_garden_btn.setEnabled(inv["water"] > 0)
        self.sunlight_btn.setEnabled(inv["sunlight"] > 0)
        
        # Enable shop buttons based on coin availability
        self.buy_water_btn.setEnabled(inv["coins"] >= SHOP_PRICES["water"])
        self.buy_plant_btn.setEnabled(inv["coins"] >= SHOP_PRICES["plants"])
        self.buy_tree_btn.setEnabled(inv["coins"] >= SHOP_PRICES["trees"])
        self.buy_sunlight_btn.setEnabled(inv["coins"] >= SHOP_PRICES["sunlight"])
        self.buy_seed_btn.setEnabled(inv["coins"] >= SHOP_PRICES["seeds"])
        self.buy_path_btn.setEnabled(inv["coins"] >= SHOP_PRICES["path"])
        
        # Enable theme unlock buttons based on coin availability and unlock status
        if hasattr(self, 'unlock_night_btn'):
            self.unlock_night_btn.setEnabled(
                inv["coins"] >= THEME_UNLOCK_PRICE and "night" not in unlocked
            )
            self.unlock_summer_btn.setEnabled(
                inv["coins"] >= THEME_UNLOCK_PRICE and "summer" not in unlocked
            )
            self.unlock_winter_btn.setEnabled(
                inv["coins"] >= THEME_UNLOCK_PRICE and "winter" not in unlocked
            )
            self.unlock_spring_btn.setEnabled(
                inv["coins"] >= THEME_UNLOCK_PRICE and "spring" not in unlocked
            )
            self.unlock_autumn_btn.setEnabled(
                inv["coins"] >= THEME_UNLOCK_PRICE and "autumn" not in unlocked
            )


