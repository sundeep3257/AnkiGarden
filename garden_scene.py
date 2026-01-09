"""Graphics-based garden scene and view for AnkiGarden.

This module is intentionally UI-focused: it renders the state and sends actions
back into `AddonState` (which handles persistence/business rules).
"""

from __future__ import annotations

import logging
import math
import time
import traceback
from typing import Dict, List, Optional

from aqt.qt import (
    QCursor,
    QEasingCurve,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QColor,
    QLinearGradient,
    QRadialGradient,
    QPainter,
    QPainterPath,
    QPointF,
    QPen,
    QPixmap,
    QRectF,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from aqt.utils import tooltip

from .constants import GARDEN_HEIGHT, GARDEN_WIDTH
from .state import AddonState, TileStatus, utc_now

logger = logging.getLogger(__name__)

TILE_SIZE = 80.0
ITEM_SIZE = 56.0  # diameter/size within tile


class _ErrorThrottle:
    """Rate-limits user-visible nonfatal error reporting.

    This exists to prevent repaint-loop exceptions from spamming modal Anki error
    dialogs (which can effectively lock the UI). We catch exceptions, log them,
    and show a tooltip at most once per `cooldown_s` per key.
    """

    def __init__(self, cooldown_s: float = 6.0) -> None:
        self.cooldown_s = float(cooldown_s)
        self._last_by_key: Dict[str, float] = {}

    def should_show(self, key: str) -> bool:
        now = time.monotonic()
        last = self._last_by_key.get(key, 0.0)
        if (now - last) < self.cooldown_s:
            return False
        self._last_by_key[key] = now
        return True


class GardenItem(QGraphicsObject):
    """Draggable plant/tree item.

    This class supports two modes:
    - placed item: backed by a tile in state (tile_idx is not None)
    - pending placement: not yet in state (tile_idx is None)
    """

    def __init__(
        self,
        *,
        state: AddonState,
        kind: str,
        tile_idx: Optional[int] = None,
        tile: Optional[dict] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.state = state
        self.kind = kind
        self.tile_idx = tile_idx
        self.tile = tile
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setAcceptHoverEvents(True)
        self._start_pos: QPointF = QPointF()
        self._start_idx: Optional[int] = tile_idx
        self.status: TileStatus = self.state.tile_status(tile, utc_now())
    
    def _get_mode_adjusted_color(self, base_color: QColor, mode: str) -> QColor:
        """Adjust a color based on the aesthetic mode."""
        if mode == "night":
            # Darker, more muted colors with blue tint
            return QColor(
                max(0, base_color.red() - 40),
                max(0, base_color.green() - 30),
                min(255, base_color.blue() + 20)
            )
        elif mode == "summer":
            # Brighter, more saturated colors
            return QColor(
                min(255, base_color.red() + 20),
                min(255, base_color.green() + 15),
                max(0, base_color.blue() - 10)
            )
        elif mode == "winter":
            # Cooler, desaturated colors with blue tint
            return QColor(
                max(0, base_color.red() - 30),
                max(0, base_color.green() - 20),
                min(255, base_color.blue() + 30)
            )
        elif mode == "spring":
            # Fresh, slightly brighter greens
            return QColor(
                min(255, base_color.red() + 10),
                min(255, base_color.green() + 20),
                max(0, base_color.blue() - 5)
            )
        elif mode == "autumn":
            # Warmer, more orange/red tinted
            return QColor(
                min(255, base_color.red() + 25),
                min(255, base_color.green() + 10),
                max(0, base_color.blue() - 20)
            )
        else:  # default
            return base_color

    def boundingRect(self) -> QRectF:
        if self.kind in ("tree", "cherry_blossom"):
            # Trees and cherry blossoms are 2x2 tiles
            size = TILE_SIZE * 2
            return QRectF(-size / 2, -size / 2, size, size)
        else:
            # Plants, seeds, and colorful plants are 1x1 tile
            half = ITEM_SIZE / 2
            return QRectF(-half, -half, ITEM_SIZE, ITEM_SIZE)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: D401
        # IMPORTANT: never raise from paint()—Qt can call this in tight repaint
        # loops, and uncaught exceptions can spam modal error windows.
        try:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = self.boundingRect()
            
            if self.kind == "plant":
                self._draw_plant(painter, rect)
            elif self.kind == "seed":
                self._draw_seed(painter, rect)
            elif self.kind == "colorful_plant":
                self._draw_colorful_plant(painter, rect)
            elif self.kind == "cherry_blossom":
                self._draw_cherry_blossom(painter, rect)
            else:
                self._draw_tree(painter, rect)

            self._draw_overlays(painter)
            painter.restore()
        except Exception:
            scene = self.scene()
            if isinstance(scene, GardenScene):
                scene._report_nonfatal(  # noqa: SLF001
                    "paint",
                    "AnkiGarden: rendering error (see console/log).",
                    exc_info=True,
                )

    def _draw_plant(self, painter: QPainter, rect: QRectF) -> None:
        """Draw a detailed plant with stem, leaves, and optional flowers."""
        center_x = rect.center().x()
        center_y = rect.center().y()
        width = rect.width()
        height = rect.height()
        
        mode = self.state.get_aesthetic_mode()
        
        # Determine colors based on status (with wilt levels for plants)
        if self.status.is_dead:
            stem_color = QColor(100, 100, 100)  # Gray
            leaf_color = QColor(120, 120, 120)
            flower_colors = []
        elif self.status.is_wilted:
            wilt_level = getattr(self.status, "wilt_level", 1)
            if wilt_level >= 2:
                # Heavily wilted: darker, more brown
                stem_color = QColor(120, 72, 30)  # Darker brown
                leaf_color = QColor(110, 78, 40)  # Brownish-green
            else:
                # Mild wilt (current wilt colours)
                stem_color = QColor(139, 90, 43)  # Brownish
                leaf_color = QColor(85, 107, 47)  # Dark olive
            flower_colors = []
        else:
            base_stem_color = QColor(101, 67, 33)  # Brown stem
            base_leaf_color = QColor(34, 139, 34)  # Forest green
            stem_color = self._get_mode_adjusted_color(base_stem_color, mode)
            leaf_color = self._get_mode_adjusted_color(base_leaf_color, mode)
            if self.status.is_blooming:
                # Colorful flowers when blooming - adjust based on mode
                base_flower_colors = [
                    QColor(255, 192, 203),  # Pink
                    QColor(255, 20, 147),   # Deep pink
                    QColor(255, 165, 0),    # Orange
                    QColor(255, 255, 0),    # Yellow
                    QColor(138, 43, 226),    # Blue violet
                ]
                flower_colors = [self._get_mode_adjusted_color(c, mode) for c in base_flower_colors]
            else:
                flower_colors = []
        
        # Draw stem
        stem_width = width * 0.08
        stem_rect = QRectF(
            center_x - stem_width / 2,
            center_y + height * 0.1,
            stem_width,
            height * 0.4
        )
        painter.setBrush(stem_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(stem_rect, 2, 2)
        
        # Draw leaves (2-3 leaves)
        leaf_size = width * 0.25
        leaves = [
            (center_x - width * 0.25, center_y - height * 0.1, -30),  # Left leaf
            (center_x + width * 0.25, center_y - height * 0.15, 30),  # Right leaf
            (center_x, center_y - height * 0.25, 0),  # Top leaf
        ]
        
        for leaf_x, leaf_y, angle in leaves:
            leaf_path = QPainterPath()
            leaf_center = QPointF(leaf_x, leaf_y)
            
            # Create an elliptical leaf shape
            leaf_rect = QRectF(
                leaf_center.x() - leaf_size / 2,
                leaf_center.y() - leaf_size / 2,
                leaf_size,
                leaf_size * 1.3
            )
            
            # Rotate leaf
            painter.save()
            painter.translate(leaf_center)
            painter.rotate(angle)
            painter.translate(-leaf_center)
            
            # Gradient for leaf
            leaf_gradient = QRadialGradient(leaf_center, leaf_size / 2)
            if self.status.is_dead:
                leaf_gradient.setColorAt(0, QColor(140, 140, 140))
                leaf_gradient.setColorAt(1, QColor(100, 100, 100))
            elif self.status.is_wilted:
                wilt_level = getattr(self.status, "wilt_level", 1)
                if wilt_level >= 2:
                    # Heavily wilted: more brown, less green
                    leaf_gradient.setColorAt(0, QColor(139, 90, 43))
                    leaf_gradient.setColorAt(1, QColor(110, 78, 40))
                else:
                    # Mild wilt
                    leaf_gradient.setColorAt(0, QColor(107, 142, 35))
                    leaf_gradient.setColorAt(1, QColor(85, 107, 47))
            else:
                leaf_gradient.setColorAt(0, QColor(50, 205, 50))
                leaf_gradient.setColorAt(1, QColor(34, 139, 34))
            
            painter.setBrush(leaf_gradient)
            painter.setPen(QPen(leaf_color.darker(120), 1))
            painter.drawEllipse(leaf_rect)
            painter.restore()
        
        # Draw flowers when blooming
        if flower_colors and self.status.is_blooming:
            flower_size = width * 0.15
            flower_positions = [
                (center_x - width * 0.2, center_y - height * 0.2),
                (center_x + width * 0.2, center_y - height * 0.15),
                (center_x, center_y - height * 0.3),
            ]
            
            for i, (fx, fy) in enumerate(flower_positions):
                if i >= len(flower_colors):
                    break
                flower_color = flower_colors[i]
                
                # Draw flower petals (5 petals in a circle)
                petal_size = flower_size * 0.4
                flower_center = QPointF(fx, fy)
                petal_distance = flower_size * 0.25
                
                for petal_idx in range(5):
                    angle_deg = (petal_idx * 72) - 90  # 72 degrees per petal, start at top
                    angle_rad = math.radians(angle_deg)
                    
                    # Calculate petal position around the center using proper trigonometry
                    petal_x = flower_center.x() + petal_distance * math.cos(angle_rad)
                    petal_y = flower_center.y() + petal_distance * math.sin(angle_rad)
                    
                    # Simple petal as small ellipse
                    petal_rect = QRectF(
                        petal_x - petal_size / 2,
                        petal_y - petal_size / 2,
                        petal_size,
                        petal_size
                    )
                    
                    # Rotate petal around flower center
                    painter.save()
                    painter.translate(flower_center)
                    painter.rotate(angle_deg)
                    painter.translate(-flower_center)
                    
                    petal_gradient = QRadialGradient(flower_center, petal_size)
                    petal_gradient.setColorAt(0, flower_color.lighter(130))
                    petal_gradient.setColorAt(1, flower_color)
                    painter.setBrush(petal_gradient)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(petal_rect)
                    painter.restore()
                
                # Draw flower center
                center_radius = flower_size * 0.15
                center_gradient = QRadialGradient(flower_center, center_radius)
                center_gradient.setColorAt(0, QColor(255, 215, 0))  # Gold center
                center_gradient.setColorAt(1, QColor(255, 140, 0))
                painter.setBrush(center_gradient)
                painter.drawEllipse(
                    QRectF(
                        flower_center.x() - center_radius,
                        flower_center.y() - center_radius,
                        center_radius * 2,
                        center_radius * 2
                    )
                )

    def _draw_tree(self, painter: QPainter, rect: QRectF) -> None:
        """Draw a detailed tree with trunk and leafy canopy, with optional flowers."""
        center_x = rect.center().x()
        center_y = rect.center().y()
        width = rect.width()
        height = rect.height()
        
        mode = self.state.get_aesthetic_mode()
        
        # Determine colors based on status
        if self.status.is_dead:
            trunk_color = QColor(80, 80, 80)  # Dark gray
            leaf_color = QColor(100, 100, 100)  # Gray
            flower_colors = []
        elif self.status.is_wilted:
            trunk_color = QColor(101, 67, 33)  # Brown
            leaf_color = QColor(85, 107, 47)  # Dark olive
            flower_colors = []
        else:
            base_trunk_color = QColor(101, 67, 33)  # Brown trunk
            base_leaf_color = QColor(34, 139, 34)  # Forest green
            trunk_color = self._get_mode_adjusted_color(base_trunk_color, mode)
            leaf_color = self._get_mode_adjusted_color(base_leaf_color, mode)
            if self.status.is_blooming:
                # Colorful flowers when blooming - adjust based on mode
                base_flower_colors = [
                    QColor(255, 192, 203),  # Pink
                    QColor(255, 20, 147),   # Deep pink
                    QColor(255, 255, 0),    # Yellow
                    QColor(255, 165, 0),    # Orange
                ]
                flower_colors = [self._get_mode_adjusted_color(c, mode) for c in base_flower_colors]
            else:
                flower_colors = []
        
        # Draw trunk (centered, bottom portion)
        trunk_width = width * 0.15
        trunk_height = height * 0.3
        trunk_rect = QRectF(
            center_x - trunk_width / 2,
            center_y + height * 0.2,
            trunk_width,
            trunk_height
        )
        
        # Trunk gradient
        trunk_gradient = QLinearGradient(
            trunk_rect.topLeft(),
            trunk_rect.topRight()
        )
        trunk_gradient.setColorAt(0, trunk_color.lighter(110))
        trunk_gradient.setColorAt(1, trunk_color.darker(120))
        painter.setBrush(trunk_gradient)
        painter.setPen(QPen(trunk_color.darker(150), 1))
        painter.drawRoundedRect(trunk_rect, 3, 3)
        
        # Draw leafy canopy (multiple overlapping circles/ellipses)
        canopy_y = center_y - height * 0.1
        canopy_radius = width * 0.35
        
        # Main canopy layers (3-4 layers for depth)
        canopy_layers = [
            (center_x, canopy_y, canopy_radius, 0.9),
            (center_x - width * 0.15, canopy_y - height * 0.1, canopy_radius * 0.8, 0.85),
            (center_x + width * 0.15, canopy_y - height * 0.1, canopy_radius * 0.8, 0.85),
            (center_x, canopy_y - height * 0.2, canopy_radius * 0.7, 0.8),
        ]
        
        for cx, cy, radius, alpha in canopy_layers:
            canopy_center = QPointF(cx, cy)
            
            # Canopy gradient
            canopy_gradient = QRadialGradient(canopy_center, radius)
            if self.status.is_dead:
                canopy_gradient.setColorAt(0, QColor(120, 120, 120, int(255 * alpha)))
                canopy_gradient.setColorAt(1, QColor(80, 80, 80, int(255 * alpha)))
            elif self.status.is_wilted:
                canopy_gradient.setColorAt(0, QColor(107, 142, 35, int(255 * alpha)))
                canopy_gradient.setColorAt(1, QColor(85, 107, 47, int(255 * alpha)))
            else:
                canopy_gradient.setColorAt(0, QColor(50, 205, 50, int(255 * alpha)))
                canopy_gradient.setColorAt(0.5, QColor(34, 139, 34, int(255 * alpha)))
                canopy_gradient.setColorAt(1, QColor(0, 100, 0, int(255 * alpha)))
            
            painter.setBrush(canopy_gradient)
            painter.setPen(QPen(leaf_color.darker(130), 1))
            
            # Draw as ellipse for more natural shape
            canopy_rect = QRectF(
                cx - radius,
                cy - radius * 0.9,
                radius * 2,
                radius * 1.8
            )
            painter.drawEllipse(canopy_rect)
        
        # Draw flowers when blooming
        if flower_colors and self.status.is_blooming:
            flower_size = width * 0.12
            # Distribute flowers across the canopy
            flower_positions = [
                (center_x - width * 0.2, canopy_y - height * 0.15),
                (center_x + width * 0.2, canopy_y - height * 0.15),
                (center_x, canopy_y - height * 0.25),
                (center_x - width * 0.1, canopy_y),
                (center_x + width * 0.1, canopy_y),
            ]
            
            for i, (fx, fy) in enumerate(flower_positions):
                if i >= len(flower_colors):
                    break
                flower_color = flower_colors[i % len(flower_colors)]
                
                # Draw flower (simpler than plant flowers, but still visible)
                flower_center = QPointF(fx, fy)
                petal_size = flower_size * 0.35
                
                # 5 petals
                petal_distance = flower_size * 0.25
                for petal_idx in range(5):
                    angle_deg = petal_idx * 72 - 90
                    angle_rad = math.radians(angle_deg)
                    
                    # Calculate petal position around the center using proper trigonometry
                    petal_x = flower_center.x() + petal_distance * math.cos(angle_rad)
                    petal_y = flower_center.y() + petal_distance * math.sin(angle_rad)
                    
                    petal_rect = QRectF(
                        petal_x - petal_size / 2,
                        petal_y - petal_size / 2,
                        petal_size,
                        petal_size
                    )
                    
                    painter.save()
                    painter.translate(flower_center)
                    painter.rotate(angle_deg)
                    painter.translate(-flower_center)
                    
                    petal_gradient = QRadialGradient(flower_center, petal_size)
                    petal_gradient.setColorAt(0, flower_color.lighter(140))
                    petal_gradient.setColorAt(1, flower_color)
                    painter.setBrush(petal_gradient)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(petal_rect)
                    painter.restore()
                
                # Flower center
                center_radius = flower_size * 0.12
                center_gradient = QRadialGradient(flower_center, center_radius)
                center_gradient.setColorAt(0, QColor(255, 215, 0))
                center_gradient.setColorAt(1, QColor(255, 140, 0))
                painter.setBrush(center_gradient)
                painter.drawEllipse(
                    QRectF(
                        flower_center.x() - center_radius,
                        flower_center.y() - center_radius,
                        center_radius * 2,
                        center_radius * 2
                    )
                )

    def _draw_seed(self, painter: QPainter, rect: QRectF) -> None:
        """Draw a detailed seed with potential for growth."""
        center_x = rect.center().x()
        center_y = rect.center().y()
        width = rect.width()
        height = rect.height()
        
        # Determine colors based on status
        if self.status.is_dead:
            seed_color = QColor(80, 80, 80)  # Dark gray
            highlight_color = QColor(100, 100, 100)
        elif self.status.is_wilted:
            seed_color = QColor(139, 90, 43)  # Brownish
            highlight_color = QColor(160, 110, 50)
        else:
            seed_color = QColor(139, 69, 19)  # Saddle brown
            highlight_color = QColor(160, 82, 45)  # Sienna
        
        # Draw seed as an oval/ellipse with gradient
        seed_rect = QRectF(
            center_x - width * 0.15,
            center_y - height * 0.1,
            width * 0.3,
            height * 0.4
        )
        
        seed_gradient = QRadialGradient(seed_rect.center(), seed_rect.width() / 2)
        seed_gradient.setColorAt(0, highlight_color)
        seed_gradient.setColorAt(1, seed_color)
        painter.setBrush(seed_gradient)
        painter.setPen(QPen(seed_color.darker(150), 1))
        painter.drawEllipse(seed_rect)
        
        # Add a small highlight/shine
        if not self.status.is_dead and not self.status.is_wilted:
            shine_rect = QRectF(
                center_x - width * 0.08,
                center_y - height * 0.15,
                width * 0.1,
                height * 0.15
            )
            painter.setBrush(QColor(255, 255, 255, 120))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(shine_rect)
        
        # Draw small sprout lines if healthy (indicating potential)
        if not self.status.is_dead and not self.status.is_wilted:
            painter.setPen(QPen(QColor(34, 139, 34, 150), 1.5))
            # Small curved line suggesting growth
            sprout_path = QPainterPath()
            sprout_path.moveTo(center_x, center_y + height * 0.15)
            sprout_path.quadTo(center_x + width * 0.05, center_y + height * 0.05, center_x + width * 0.1, center_y - height * 0.05)
            painter.drawPath(sprout_path)

    def _get_color_for_name(self, color_name: str) -> QColor:
        """Convert color name to QColor."""
        color_map = {
            "red": QColor(220, 20, 60),  # Crimson
            "orange": QColor(255, 140, 0),  # Dark orange
            "yellow": QColor(255, 215, 0),  # Gold
            "dark_blue": QColor(25, 25, 112),  # Midnight blue
            "light_blue": QColor(135, 206, 250),  # Light sky blue
            "purple": QColor(138, 43, 226),  # Blue violet
            "pink": QColor(255, 192, 203),  # Pink
            "teal": QColor(0, 128, 128),  # Teal
        }
        return color_map.get(color_name, QColor(255, 192, 203))  # Default to pink

    def _draw_colorful_plant(self, painter: QPainter, rect: QRectF) -> None:
        """Draw an ethereal, intricate, rare colorful plant with vibrant flowers."""
        center_x = rect.center().x()
        center_y = rect.center().y()
        width = rect.width()
        height = rect.height()
        
        mode = self.state.get_aesthetic_mode()
        
        # Get color from tile
        color_name = self.tile.get("color", "pink") if self.tile else "pink"
        base_primary_color = self._get_color_for_name(color_name)
        # Adjust primary color based on mode (but keep it colorful)
        primary_color = self._get_mode_adjusted_color(base_primary_color, mode)
        
        # Determine colors based on status
        if self.status.is_dead:
            stem_color = QColor(100, 100, 100)
            leaf_color = QColor(120, 120, 120)
            flower_color = QColor(140, 140, 140)
        elif self.status.is_wilted:
            stem_color = QColor(139, 90, 43)
            leaf_color = QColor(85, 107, 47)
            flower_color = primary_color.darker(150)
        else:
            base_stem_color = QColor(101, 67, 33)
            base_leaf_color = QColor(34, 139, 34)
            stem_color = self._get_mode_adjusted_color(base_stem_color, mode)
            leaf_color = self._get_mode_adjusted_color(base_leaf_color, mode)
            flower_color = primary_color
            
            # Add ethereal glow around the entire plant when healthy
            glow_radius = width * 0.6
            glow_gradient = QRadialGradient(center_x, center_y - height * 0.2, glow_radius)
            glow_color = QColor(primary_color.red(), primary_color.green(), primary_color.blue(), 30)
            glow_gradient.setColorAt(0, glow_color)
            glow_gradient.setColorAt(0.5, QColor(primary_color.red(), primary_color.green(), primary_color.blue(), 15))
            glow_gradient.setColorAt(1, QColor(primary_color.red(), primary_color.green(), primary_color.blue(), 0))
            painter.setBrush(glow_gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(center_x - glow_radius, center_y - height * 0.2 - glow_radius, glow_radius * 2, glow_radius * 2))
        
        # Draw detailed stem with texture
        stem_width = width * 0.1
        stem_rect = QRectF(
            center_x - stem_width / 2,
            center_y + height * 0.05,
            stem_width,
            height * 0.5
        )
        stem_gradient = QLinearGradient(stem_rect.topLeft(), stem_rect.bottomRight())
        stem_gradient.setColorAt(0, stem_color.lighter(110))
        stem_gradient.setColorAt(1, stem_color.darker(120))
        painter.setBrush(stem_gradient)
        painter.setPen(QPen(stem_color.darker(150), 1))
        painter.drawRoundedRect(stem_rect, 2, 2)
        
        # Draw multiple detailed leaves with intricate veins (6-7 leaves)
        leaf_size = width * 0.3
        leaves = [
            (center_x - width * 0.3, center_y - height * 0.05, -45, 0.9),
            (center_x + width * 0.3, center_y - height * 0.1, 45, 0.9),
            (center_x - width * 0.15, center_y - height * 0.2, -20, 0.85),
            (center_x + width * 0.15, center_y - height * 0.25, 20, 0.85),
            (center_x, center_y - height * 0.3, 0, 0.8),
            (center_x - width * 0.22, center_y - height * 0.15, -30, 0.75),
            (center_x + width * 0.22, center_y - height * 0.12, 30, 0.75),
        ]
        
        for leaf_x, leaf_y, angle, scale in leaves:
            leaf_path = QPainterPath()
            leaf_center = QPointF(leaf_x, leaf_y)
            scaled_size = leaf_size * scale
            
            leaf_rect = QRectF(
                leaf_center.x() - scaled_size / 2,
                leaf_center.y() - scaled_size / 2,
                scaled_size,
                scaled_size * 1.4
            )
            
            painter.save()
            painter.translate(leaf_center)
            painter.rotate(angle)
            painter.translate(-leaf_center)
            
            # Multi-layer leaf gradient for depth
            leaf_gradient = QRadialGradient(leaf_center, scaled_size / 2)
            if self.status.is_dead:
                leaf_gradient.setColorAt(0, QColor(140, 140, 140))
                leaf_gradient.setColorAt(1, QColor(100, 100, 100))
            elif self.status.is_wilted:
                leaf_gradient.setColorAt(0, QColor(107, 142, 35))
                leaf_gradient.setColorAt(1, QColor(85, 107, 47))
            else:
                leaf_gradient.setColorAt(0, QColor(60, 220, 60))  # Brighter center
                leaf_gradient.setColorAt(0.4, QColor(50, 205, 50))
                leaf_gradient.setColorAt(0.7, QColor(40, 180, 40))
                leaf_gradient.setColorAt(1, QColor(34, 139, 34))
            
            painter.setBrush(leaf_gradient)
            painter.setPen(QPen(leaf_color.darker(120), 1))
            painter.drawEllipse(leaf_rect)
            
            # Add intricate leaf veins when healthy
            if not self.status.is_dead and not self.status.is_wilted:
                vein_color = QColor(20, 100, 20, 100)
                painter.setPen(QPen(vein_color, 0.5))
                # Central vein
                vein_path = QPainterPath()
                vein_path.moveTo(leaf_center.x(), leaf_center.y() - scaled_size * 0.7)
                vein_path.lineTo(leaf_center.x(), leaf_center.y() + scaled_size * 0.7)
                painter.drawPath(vein_path)
                # Side veins
                for side in [-1, 1]:
                    for offset in [-0.3, 0, 0.3]:
                        vein_path = QPainterPath()
                        start_y = leaf_center.y() + offset * scaled_size * 0.5
                        vein_path.moveTo(leaf_center.x(), start_y)
                        vein_path.lineTo(leaf_center.x() + side * scaled_size * 0.3, start_y + side * scaled_size * 0.2)
                        painter.drawPath(vein_path)
            
            painter.restore()
        
        # Draw vibrant, ethereal, intricate flowers (spread out across the plant)
        if not self.status.is_dead:
            flower_size = width * 0.25
            flower_positions = [
                # Top flowers - spread wider
                (center_x - width * 0.35, center_y - height * 0.3),
                (center_x + width * 0.35, center_y - height * 0.28),
                (center_x, center_y - height * 0.35),
                # Middle flowers - spread horizontally
                (center_x - width * 0.32, center_y - height * 0.1),
                (center_x + width * 0.32, center_y - height * 0.08),
                (center_x - width * 0.28, center_y - height * 0.18),
                (center_x + width * 0.28, center_y - height * 0.15),
                # Lower flowers - spread out
                (center_x - width * 0.25, center_y + height * 0.05),
                (center_x + width * 0.25, center_y + height * 0.08),
            ]
            
            for fx, fy in flower_positions:
                flower_center = QPointF(fx, fy)
                
                # Ethereal glow around each flower
                if not self.status.is_wilted:
                    glow_radius = flower_size * 0.8
                    flower_glow = QRadialGradient(flower_center, glow_radius)
                    glow_alpha = 40
                    flower_glow.setColorAt(0, QColor(flower_color.red(), flower_color.green(), flower_color.blue(), glow_alpha))
                    flower_glow.setColorAt(0.5, QColor(flower_color.red(), flower_color.green(), flower_color.blue(), glow_alpha // 2))
                    flower_glow.setColorAt(1, QColor(flower_color.red(), flower_color.green(), flower_color.blue(), 0))
                    painter.setBrush(flower_glow)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(QRectF(flower_center.x() - glow_radius, flower_center.y() - glow_radius, glow_radius * 2, glow_radius * 2))
                
                # Draw flower with multiple intricate layers of petals
                petal_size = flower_size * 0.45
                petal_distance = flower_size * 0.3
                
                # Outermost petals (12 petals for more intricacy)
                for petal_idx in range(12):
                    angle_deg = petal_idx * 30 - 90
                    angle_rad = math.radians(angle_deg)
                    
                    petal_x = flower_center.x() + petal_distance * 1.1 * math.cos(angle_rad)
                    petal_y = flower_center.y() + petal_distance * 1.1 * math.sin(angle_rad)
                    
                    petal_rect = QRectF(
                        petal_x - petal_size * 0.9 / 2,
                        petal_y - petal_size * 0.9 / 2,
                        petal_size * 0.9,
                        petal_size * 0.9
                    )
                    
                    painter.save()
                    painter.translate(flower_center)
                    painter.rotate(angle_deg)
                    painter.translate(-flower_center)
                    
                    petal_gradient = QRadialGradient(flower_center, petal_size)
                    if self.status.is_wilted:
                        petal_gradient.setColorAt(0, flower_color.lighter(130))
                        petal_gradient.setColorAt(1, flower_color.darker(150))
                    else:
                        petal_gradient.setColorAt(0, QColor(255, 255, 255, 200))  # Almost white center
                        petal_gradient.setColorAt(0.3, flower_color.lighter(180))
                        petal_gradient.setColorAt(0.7, flower_color.lighter(130))
                        petal_gradient.setColorAt(1, flower_color)
                    
                    painter.setBrush(petal_gradient)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(petal_rect)
                    painter.restore()
                
                # Middle petals (8 petals)
                for petal_idx in range(8):
                    angle_deg = petal_idx * 45 - 90
                    angle_rad = math.radians(angle_deg)
                    
                    petal_x = flower_center.x() + petal_distance * math.cos(angle_rad)
                    petal_y = flower_center.y() + petal_distance * math.sin(angle_rad)
                    
                    petal_rect = QRectF(
                        petal_x - petal_size / 2,
                        petal_y - petal_size / 2,
                        petal_size,
                        petal_size
                    )
                    
                    painter.save()
                    painter.translate(flower_center)
                    painter.rotate(angle_deg)
                    painter.translate(-flower_center)
                    
                    petal_gradient = QRadialGradient(flower_center, petal_size)
                    if self.status.is_wilted:
                        petal_gradient.setColorAt(0, flower_color.lighter(130))
                        petal_gradient.setColorAt(1, flower_color.darker(150))
                    else:
                        petal_gradient.setColorAt(0, flower_color.lighter(160))
                        petal_gradient.setColorAt(0.5, flower_color.lighter(140))
                        petal_gradient.setColorAt(1, flower_color)
                    
                    painter.setBrush(petal_gradient)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(petal_rect)
                    painter.restore()
                
                # Inner petals (5 petals, smaller)
                inner_petal_size = petal_size * 0.65
                inner_distance = petal_distance * 0.5
                for petal_idx in range(5):
                    angle_deg = petal_idx * 72 - 90
                    angle_rad = math.radians(angle_deg)
                    
                    petal_x = flower_center.x() + inner_distance * math.cos(angle_rad)
                    petal_y = flower_center.y() + inner_distance * math.sin(angle_rad)
                    
                    petal_rect = QRectF(
                        petal_x - inner_petal_size / 2,
                        petal_y - inner_petal_size / 2,
                        inner_petal_size,
                        inner_petal_size
                    )
                    
                    painter.save()
                    painter.translate(flower_center)
                    painter.rotate(angle_deg)
                    painter.translate(-flower_center)
                    
                    inner_gradient = QRadialGradient(flower_center, inner_petal_size)
                    inner_gradient.setColorAt(0, QColor(255, 255, 255, 220))
                    inner_gradient.setColorAt(0.4, flower_color.lighter(180))
                    inner_gradient.setColorAt(1, flower_color.lighter(140))
                    painter.setBrush(inner_gradient)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(petal_rect)
                    painter.restore()
                
                # Intricate multi-layer flower center
                center_radius = flower_size * 0.22
                # Outer center ring
                center_gradient = QRadialGradient(flower_center, center_radius)
                center_gradient.setColorAt(0, QColor(255, 255, 200, 255))
                center_gradient.setColorAt(0.4, QColor(255, 240, 150, 255))
                center_gradient.setColorAt(0.7, QColor(255, 215, 0, 255))
                center_gradient.setColorAt(1, QColor(255, 165, 0, 255))
                painter.setBrush(center_gradient)
                painter.setPen(QPen(QColor(255, 140, 0), 1.5))
                painter.drawEllipse(
                    QRectF(
                        flower_center.x() - center_radius,
                        flower_center.y() - center_radius,
                        center_radius * 2,
                        center_radius * 2
                    )
                )
                # Inner center highlight
                inner_center_radius = center_radius * 0.6
                inner_center_gradient = QRadialGradient(flower_center, inner_center_radius)
                inner_center_gradient.setColorAt(0, QColor(255, 255, 255, 255))
                inner_center_gradient.setColorAt(1, QColor(255, 240, 180, 255))
                painter.setBrush(inner_center_gradient)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(
                    QRectF(
                        flower_center.x() - inner_center_radius,
                        flower_center.y() - inner_center_radius,
                        inner_center_radius * 2,
                        inner_center_radius * 2
                    )
                )
                
                # Add sparkle particles around flowers when healthy
                if not self.status.is_wilted:
                    sparkle_positions = [
                        (flower_center.x() + flower_size * 0.5, flower_center.y() - flower_size * 0.3),
                        (flower_center.x() - flower_size * 0.4, flower_center.y() + flower_size * 0.4),
                        (flower_center.x() + flower_size * 0.3, flower_center.y() + flower_size * 0.5),
                        (flower_center.x() - flower_size * 0.5, flower_center.y() - flower_size * 0.2),
                    ]
                    for sp_x, sp_y in sparkle_positions:
                        sparkle_size = 2
                        sparkle_color = QColor(255, 255, 255, 180)
                        painter.setBrush(sparkle_color)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawEllipse(QRectF(sp_x - sparkle_size, sp_y - sparkle_size, sparkle_size * 2, sparkle_size * 2))
                        # Cross sparkle
                        painter.setPen(QPen(sparkle_color, 1))
                        painter.drawLine(sp_x - sparkle_size * 2, sp_y, sp_x + sparkle_size * 2, sp_y)
                        painter.drawLine(sp_x, sp_y - sparkle_size * 2, sp_x, sp_y + sparkle_size * 2)

    def _draw_cherry_blossom(self, painter: QPainter, rect: QRectF) -> None:
        """Draw an ethereal, intricate, rare cherry blossom tree with vibrant colored blossoms."""
        center_x = rect.center().x()
        center_y = rect.center().y()
        width = rect.width()
        height = rect.height()
        
        mode = self.state.get_aesthetic_mode()
        
        # Get color from tile
        color_name = self.tile.get("color", "pink") if self.tile else "pink"
        base_blossom_color = self._get_color_for_name(color_name)
        # Adjust blossom color based on mode (but keep it colorful)
        blossom_color = self._get_mode_adjusted_color(base_blossom_color, mode)
        
        # Determine colors based on status
        if self.status.is_dead:
            trunk_color = QColor(80, 80, 80)
            branch_color = QColor(100, 100, 100)
            blossom_color = QColor(140, 140, 140)
        elif self.status.is_wilted:
            trunk_color = QColor(101, 67, 33)
            branch_color = QColor(120, 80, 50)
            blossom_color = blossom_color.darker(150)
        else:
            base_trunk_color = QColor(101, 67, 33)
            base_branch_color = QColor(120, 80, 50)
            trunk_color = self._get_mode_adjusted_color(base_trunk_color, mode)
            branch_color = self._get_mode_adjusted_color(base_branch_color, mode)
            
            # Add ethereal glow around the entire tree when healthy
            glow_radius = width * 0.7
            glow_gradient = QRadialGradient(center_x, center_y - height * 0.1, glow_radius)
            glow_alpha = 25
            glow_gradient.setColorAt(0, QColor(blossom_color.red(), blossom_color.green(), blossom_color.blue(), glow_alpha))
            glow_gradient.setColorAt(0.4, QColor(blossom_color.red(), blossom_color.green(), blossom_color.blue(), glow_alpha // 2))
            glow_gradient.setColorAt(1, QColor(blossom_color.red(), blossom_color.green(), blossom_color.blue(), 0))
            painter.setBrush(glow_gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(center_x - glow_radius, center_y - height * 0.1 - glow_radius, glow_radius * 2, glow_radius * 2))
        
        # Draw detailed trunk with texture
        trunk_width = width * 0.18
        trunk_height = height * 0.35
        trunk_rect = QRectF(
            center_x - trunk_width / 2,
            center_y + height * 0.15,
            trunk_width,
            trunk_height
        )
        
        trunk_gradient = QLinearGradient(trunk_rect.topLeft(), trunk_rect.topRight())
        trunk_gradient.setColorAt(0, trunk_color.lighter(110))
        trunk_gradient.setColorAt(0.5, trunk_color)
        trunk_gradient.setColorAt(1, trunk_color.darker(130))
        painter.setBrush(trunk_gradient)
        painter.setPen(QPen(trunk_color.darker(150), 2))
        painter.drawRoundedRect(trunk_rect, 4, 4)
        
        # Draw intricate, detailed branches (more branches with varying thickness)
        branch_thickness = width * 0.04
        branches = [
            # Left branches (main)
            (center_x - width * 0.1, center_y + height * 0.05, center_x - width * 0.3, center_y - height * 0.1, branch_thickness),
            (center_x - width * 0.15, center_y - height * 0.05, center_x - width * 0.35, center_y - height * 0.25, branch_thickness * 0.9),
            (center_x - width * 0.12, center_y - height * 0.15, center_x - width * 0.28, center_y - height * 0.3, branch_thickness * 0.75),
            # Right branches (main)
            (center_x + width * 0.1, center_y + height * 0.05, center_x + width * 0.3, center_y - height * 0.1, branch_thickness),
            (center_x + width * 0.15, center_y - height * 0.05, center_x + width * 0.35, center_y - height * 0.25, branch_thickness * 0.9),
            (center_x + width * 0.12, center_y - height * 0.15, center_x + width * 0.28, center_y - height * 0.3, branch_thickness * 0.75),
            # Top branches
            (center_x, center_y - height * 0.1, center_x - width * 0.15, center_y - height * 0.3, branch_thickness * 0.8),
            (center_x, center_y - height * 0.1, center_x + width * 0.15, center_y - height * 0.3, branch_thickness * 0.8),
            (center_x, center_y - height * 0.2, center_x - width * 0.12, center_y - height * 0.38, branch_thickness * 0.7),
            (center_x, center_y - height * 0.2, center_x + width * 0.12, center_y - height * 0.38, branch_thickness * 0.7),
            # Secondary branches
            (center_x - width * 0.2, center_y - height * 0.2, center_x - width * 0.32, center_y - height * 0.15, branch_thickness * 0.6),
            (center_x + width * 0.2, center_y - height * 0.2, center_x + width * 0.32, center_y - height * 0.15, branch_thickness * 0.6),
        ]
        
        for x1, y1, x2, y2, thickness in branches:
            branch_path = QPainterPath()
            branch_path.moveTo(x1, y1)
            # More natural curved branch with multiple control points
            control_x1 = x1 + (x2 - x1) * 0.3
            control_y1 = y1 - height * 0.08
            control_x2 = x1 + (x2 - x1) * 0.7
            control_y2 = (y1 + y2) / 2 - height * 0.12
            branch_path.cubicTo(control_x1, control_y1, control_x2, control_y2, x2, y2)
            
            # Branch gradient for depth
            branch_gradient = QLinearGradient(QPointF(x1, y1), QPointF(x2, y2))
            branch_gradient.setColorAt(0, branch_color.lighter(110))
            branch_gradient.setColorAt(1, branch_color.darker(120))
            
            branch_pen = QPen(branch_gradient, thickness)
            branch_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            branch_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(branch_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(branch_path)
        
        # Draw ethereal, intricate cherry blossoms (many blossoms with varying sizes and detail)
        if not self.status.is_dead:
            base_blossom_size = width * 0.08
            # Distribute many blossoms across branches and canopy with varying sizes
            blossom_positions = [
                # Left side (main)
                (center_x - width * 0.25, center_y - height * 0.15, 1.0),
                (center_x - width * 0.3, center_y - height * 0.05, 1.1),
                (center_x - width * 0.35, center_y - height * 0.2, 0.9),
                (center_x - width * 0.2, center_y - height * 0.25, 1.0),
                (center_x - width * 0.28, center_y - height * 0.12, 0.85),
                (center_x - width * 0.32, center_y - height * 0.28, 0.95),
                # Right side (main)
                (center_x + width * 0.25, center_y - height * 0.15, 1.0),
                (center_x + width * 0.3, center_y - height * 0.05, 1.1),
                (center_x + width * 0.35, center_y - height * 0.2, 0.9),
                (center_x + width * 0.2, center_y - height * 0.25, 1.0),
                (center_x + width * 0.28, center_y - height * 0.12, 0.85),
                (center_x + width * 0.32, center_y - height * 0.28, 0.95),
                # Top
                (center_x, center_y - height * 0.3, 1.2),
                (center_x - width * 0.1, center_y - height * 0.35, 1.0),
                (center_x + width * 0.1, center_y - height * 0.35, 1.0),
                (center_x - width * 0.05, center_y - height * 0.2, 0.9),
                (center_x + width * 0.05, center_y - height * 0.2, 0.9),
                (center_x, center_y - height * 0.38, 1.1),
                (center_x - width * 0.08, center_y - height * 0.32, 0.8),
                (center_x + width * 0.08, center_y - height * 0.32, 0.8),
                # Additional scattered blossoms
                (center_x - width * 0.15, center_y, 0.85),
                (center_x + width * 0.15, center_y, 0.85),
                (center_x - width * 0.2, center_y - height * 0.1, 0.9),
                (center_x + width * 0.2, center_y - height * 0.1, 0.9),
                (center_x - width * 0.18, center_y - height * 0.18, 0.75),
                (center_x + width * 0.18, center_y - height * 0.18, 0.75),
                (center_x - width * 0.22, center_y - height * 0.08, 0.8),
                (center_x + width * 0.22, center_y - height * 0.08, 0.8),
            ]
            
            for fx, fy, size_mult in blossom_positions:
                blossom_center = QPointF(fx, fy)
                blossom_size = base_blossom_size * size_mult
                
                # Ethereal glow around each blossom
                if not self.status.is_wilted:
                    glow_radius = blossom_size * 1.2
                    blossom_glow = QRadialGradient(blossom_center, glow_radius)
                    glow_alpha = 50
                    blossom_glow.setColorAt(0, QColor(blossom_color.red(), blossom_color.green(), blossom_color.blue(), glow_alpha))
                    blossom_glow.setColorAt(0.6, QColor(blossom_color.red(), blossom_color.green(), blossom_color.blue(), glow_alpha // 3))
                    blossom_glow.setColorAt(1, QColor(blossom_color.red(), blossom_color.green(), blossom_color.blue(), 0))
                    painter.setBrush(blossom_glow)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(QRectF(blossom_center.x() - glow_radius, blossom_center.y() - glow_radius, glow_radius * 2, glow_radius * 2))
                
                # Draw intricate cherry blossom with multiple petal layers
                petal_size = blossom_size * 0.45
                petal_distance = blossom_size * 0.3
                
                # Outer petals (8 petals for more detail)
                for petal_idx in range(8):
                    angle_deg = petal_idx * 45 - 90
                    angle_rad = math.radians(angle_deg)
                    
                    petal_x = blossom_center.x() + petal_distance * 1.1 * math.cos(angle_rad)
                    petal_y = blossom_center.y() + petal_distance * 1.1 * math.sin(angle_rad)
                    
                    petal_rect = QRectF(
                        petal_x - petal_size * 0.85 / 2,
                        petal_y - petal_size * 0.85 / 2,
                        petal_size * 0.85,
                        petal_size * 0.85
                    )
                    
                    painter.save()
                    painter.translate(blossom_center)
                    painter.rotate(angle_deg)
                    painter.translate(-blossom_center)
                    
                    petal_gradient = QRadialGradient(blossom_center, petal_size)
                    if self.status.is_wilted:
                        petal_gradient.setColorAt(0, blossom_color.lighter(130))
                        petal_gradient.setColorAt(1, blossom_color.darker(150))
                    else:
                        petal_gradient.setColorAt(0, QColor(255, 255, 255, 220))
                        petal_gradient.setColorAt(0.3, blossom_color.lighter(180))
                        petal_gradient.setColorAt(0.7, blossom_color.lighter(140))
                        petal_gradient.setColorAt(1, blossom_color)
                    
                    painter.setBrush(petal_gradient)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(petal_rect)
                    painter.restore()
                
                # Inner petals (5 petals)
                inner_petal_size = petal_size * 0.7
                inner_distance = petal_distance * 0.6
                for petal_idx in range(5):
                    angle_deg = petal_idx * 72 - 90
                    angle_rad = math.radians(angle_deg)
                    
                    petal_x = blossom_center.x() + inner_distance * math.cos(angle_rad)
                    petal_y = blossom_center.y() + inner_distance * math.sin(angle_rad)
                    
                    petal_rect = QRectF(
                        petal_x - inner_petal_size / 2,
                        petal_y - inner_petal_size / 2,
                        inner_petal_size,
                        inner_petal_size
                    )
                    
                    painter.save()
                    painter.translate(blossom_center)
                    painter.rotate(angle_deg)
                    painter.translate(-blossom_center)
                    
                    inner_gradient = QRadialGradient(blossom_center, inner_petal_size)
                    if self.status.is_wilted:
                        inner_gradient.setColorAt(0, blossom_color.lighter(130))
                        inner_gradient.setColorAt(1, blossom_color.darker(150))
                    else:
                        inner_gradient.setColorAt(0, QColor(255, 255, 255, 240))
                        inner_gradient.setColorAt(0.5, blossom_color.lighter(160))
                        inner_gradient.setColorAt(1, blossom_color.lighter(130))
                    
                    painter.setBrush(inner_gradient)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(petal_rect)
                    painter.restore()
                
                # Intricate multi-layer blossom center
                center_radius = blossom_size * 0.18
                # Outer center ring
                center_gradient = QRadialGradient(blossom_center, center_radius)
                center_gradient.setColorAt(0, QColor(255, 255, 200, 255))
                center_gradient.setColorAt(0.4, QColor(255, 240, 150, 255))
                center_gradient.setColorAt(0.7, QColor(255, 215, 0, 255))
                center_gradient.setColorAt(1, QColor(255, 180, 0, 255))
                painter.setBrush(center_gradient)
                painter.setPen(QPen(QColor(255, 140, 0), 1))
                painter.drawEllipse(
                    QRectF(
                        blossom_center.x() - center_radius,
                        blossom_center.y() - center_radius,
                        center_radius * 2,
                        center_radius * 2
                    )
                )
                # Inner center highlight
                inner_center_radius = center_radius * 0.55
                inner_center_gradient = QRadialGradient(blossom_center, inner_center_radius)
                inner_center_gradient.setColorAt(0, QColor(255, 255, 255, 255))
                inner_center_gradient.setColorAt(1, QColor(255, 245, 200, 255))
                painter.setBrush(inner_center_gradient)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(
                    QRectF(
                        blossom_center.x() - inner_center_radius,
                        blossom_center.y() - inner_center_radius,
                        inner_center_radius * 2,
                        inner_center_radius * 2
                    )
                )
            
            # Add floating petal particles around the tree when healthy
            if not self.status.is_wilted:
                floating_petals = [
                    (center_x - width * 0.15, center_y + height * 0.1, 0.6),
                    (center_x + width * 0.12, center_y + height * 0.15, 0.5),
                    (center_x - width * 0.2, center_y + height * 0.2, 0.7),
                    (center_x + width * 0.18, center_y + height * 0.12, 0.55),
                    (center_x - width * 0.1, center_y + height * 0.18, 0.65),
                ]
                for px, py, petal_scale in floating_petals:
                    petal_size = base_blossom_size * 0.3 * petal_scale
                    petal_color = QColor(blossom_color.red(), blossom_color.green(), blossom_color.blue(), 150)
                    painter.setBrush(petal_color)
                    painter.setPen(Qt.PenStyle.NoPen)
                    # Draw as small ellipse (falling petal)
                    painter.drawEllipse(QRectF(px - petal_size, py - petal_size * 0.5, petal_size * 2, petal_size))

    def mousePressEvent(self, event):
        scene: GardenScene = self.scene()  # type: ignore[assignment]
        # Don't handle item clicks when in special modes - let scene handle it
        if scene is not None and (scene._watering_mode or scene._path_placement_mode or scene._remove_mode):
            event.ignore()
            return
        self._start_pos = self.pos()
        self._start_idx = self.tile_idx
        self.setFocus()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene: GardenScene = self.scene()  # type: ignore[assignment]
        if scene is None:
            return
        success = scene.handle_drop(self, self.pos())
        if not success:
            # Revert to start position
            self.setPos(self._start_pos)

    # Simple overlays
    def _draw_overlays(self, painter: QPainter) -> None:
        try:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = self.boundingRect()

            # Note: Blooming is now handled by flowers in _draw_plant/_draw_tree
            # No need for "*" overlay anymore

            # Wilted indicator: small "w" in a corner (visual status is already shown in colors).
            if self.status.is_wilted and not self.status.is_dead:
                painter.setPen(QPen(Qt.GlobalColor.darkYellow, 2))
                w_rect = QRectF(rect.left() + 2, rect.bottom() - 18, 16, 16)
                painter.drawText(w_rect, int(Qt.AlignmentFlag.AlignCenter), "w")

            # Dead overlay: "X" on top (base is grayscale).
            if self.status.is_dead:
                painter.setPen(QPen(Qt.GlobalColor.white, 2))
                painter.drawLine(rect.topLeft(), rect.bottomRight())
                painter.drawLine(rect.topRight(), rect.bottomLeft())
            painter.restore()
        except Exception:
            # Let paint() handle reporting; overlays are non-critical.
            pass

    def refresh_status(self):
        self.status = self.state.tile_status(self.tile, utc_now())
        self.update()


class GardenScene(QGraphicsScene):
    """Scene that renders the garden grid and items."""

    stateChanged = pyqtSignal()

    def __init__(self, state: AddonState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self.dialog_reference = None  # Reference to dialog for special tile clicks
        self.items_by_idx: Dict[int, GardenItem] = {}
        self.setSceneRect(0, 0, GARDEN_WIDTH * TILE_SIZE, GARDEN_HEIGHT * TILE_SIZE)
        self._animations: List[QVariantAnimation] = []
        self._pending_item: Optional[GardenItem] = None
        self._watering_mode = False
        self._path_placement_mode = False
        self._remove_mode = False
        self._hover_tile_row: Optional[int] = None
        self._hover_tile_col: Optional[int] = None
        self._watering_overlays: List[QGraphicsEllipseItem] = []
        self._err_throttle = _ErrorThrottle(cooldown_s=6.0)
        # Track consecutive clicks on special tiles
        self._bottom_left_clicks = 0
        self._bottom_right_clicks = 0
        self.refresh_items()
    
    def set_dialog_reference(self, dialog) -> None:
        """Set reference to the dialog for special tile click handling."""
        self.dialog_reference = dialog

    def _report_nonfatal(self, key: str, msg: str, *, exc_info: bool = False) -> None:
        """Log exception and (rate-limited) show tooltip; never raises."""

        try:
            if exc_info:
                logger.exception(msg)
            else:
                logger.warning(msg)

            # Also print to stdout/stderr for easy debugging in add-on console.
            if exc_info:
                traceback.print_exc()

            if self._err_throttle.should_show(key):
                parent = self.views()[0] if self.views() else None
                tooltip(msg, parent=parent)
        except Exception:
            # Absolute last resort: never allow reporting to crash UI.
            pass

    # Grid drawing -----------------------------------------------------
    def _get_aesthetic_colors(self) -> tuple[QColor, QColor]:
        """Get tile background and border colors based on aesthetic mode."""
        mode = self.state.get_aesthetic_mode()
        
        if mode == "night":
            return (QColor(30, 30, 50), QColor(40, 40, 60))  # Dark blue-gray
        elif mode == "summer":
            return (QColor(255, 248, 220), QColor(255, 235, 180))  # Bright sandy
        elif mode == "winter":
            return (QColor(240, 248, 255), QColor(220, 230, 240))  # Light blue-white
        elif mode == "spring":
            return (QColor(220, 255, 220), QColor(200, 240, 200))  # Light pastel green
        elif mode == "autumn":
            return (QColor(255, 245, 220), QColor(255, 230, 200))  # Warm orange-tinted
        else:  # default
            return (QColor("#f2d2a9"), QColor("#e1bf92"))
    
    def _draw_tile_decorations(self, painter: QPainter, x: float, y: float, mode: str) -> None:
        """Draw decorative elements on tiles based on aesthetic mode."""
        import random
        
        # Use tile position as seed for consistent decoration placement
        tile_seed = hash((int(x // TILE_SIZE), int(y // TILE_SIZE))) % 1000
        
        if mode == "autumn":
            # Draw fallen leaves
            if tile_seed % 3 == 0:  # 1/3 of tiles get leaves
                leaf_count = (tile_seed % 3) + 1
                for i in range(leaf_count):
                    leaf_x = x + (tile_seed % 50) + i * 15
                    leaf_y = y + (tile_seed % 40) + i * 12
                    leaf_size = 4 + (tile_seed % 3)
                    # Orange/red/brown leaves
                    leaf_colors = [
                        QColor(255, 140, 0, 120),  # Dark orange
                        QColor(255, 69, 0, 120),   # Red orange
                        QColor(139, 69, 19, 120),  # Saddle brown
                    ]
                    leaf_color = leaf_colors[(tile_seed + i) % len(leaf_colors)]
                    painter.setBrush(leaf_color)
                    painter.setPen(Qt.PenStyle.NoPen)
                    # Draw as small ellipse
                    painter.drawEllipse(QRectF(leaf_x, leaf_y, leaf_size, leaf_size * 0.7))
        
        elif mode == "winter":
            # Draw snowflakes
            if tile_seed % 4 == 0:  # 1/4 of tiles get snowflakes
                snow_x = x + (tile_seed % 60) + 10
                snow_y = y + (tile_seed % 50) + 10
                snow_size = 3
                painter.setBrush(QColor(255, 255, 255, 200))
                painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
                # Simple snowflake as small circle with cross
                painter.drawEllipse(QRectF(snow_x - snow_size, snow_y - snow_size, snow_size * 2, snow_size * 2))
                painter.drawLine(snow_x - snow_size * 1.5, snow_y, snow_x + snow_size * 1.5, snow_y)
                painter.drawLine(snow_x, snow_y - snow_size * 1.5, snow_x, snow_y + snow_size * 1.5)
        
        elif mode == "spring":
            # Draw small flowers/grass
            if tile_seed % 5 == 0:  # 1/5 of tiles get small flowers
                flower_x = x + (tile_seed % 50) + 15
                flower_y = y + (tile_seed % 50) + 15
                flower_size = 2
                # Pastel colors
                flower_colors = [
                    QColor(255, 182, 193, 150),  # Light pink
                    QColor(221, 160, 221, 150),  # Plum
                    QColor(176, 224, 230, 150),  # Powder blue
                ]
                flower_color = flower_colors[tile_seed % len(flower_colors)]
                painter.setBrush(flower_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QRectF(flower_x - flower_size, flower_y - flower_size, flower_size * 2, flower_size * 2))
        
        elif mode == "summer":
            # Draw sun rays (gradient overlay)
            if tile_seed % 2 == 0:  # 1/2 of tiles get subtle sun effect
                sun_gradient = QRadialGradient(
                    x + TILE_SIZE * 0.3, y + TILE_SIZE * 0.2,
                    TILE_SIZE * 0.4
                )
                sun_gradient.setColorAt(0, QColor(255, 255, 200, 20))
                sun_gradient.setColorAt(1, QColor(255, 255, 200, 0))
                painter.setBrush(sun_gradient)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(QRectF(x, y, TILE_SIZE, TILE_SIZE))
        
        elif mode == "night":
            # Draw stars
            if tile_seed % 6 == 0:  # 1/6 of tiles get stars
                star_x = x + (tile_seed % 60) + 10
                star_y = y + (tile_seed % 50) + 10
                star_size = 1.5
                painter.setBrush(QColor(255, 255, 200, 180))
                painter.setPen(Qt.PenStyle.NoPen)
                # Small star as tiny cross
                painter.drawEllipse(QRectF(star_x - star_size, star_y - star_size, star_size * 2, star_size * 2))
                painter.setPen(QPen(QColor(255, 255, 200, 150), 0.5))
                painter.drawLine(star_x - star_size * 2, star_y, star_x + star_size * 2, star_y)
                painter.drawLine(star_x, star_y - star_size * 2, star_x, star_y + star_size * 2)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        try:
            super().drawBackground(painter, rect)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)  # Enable for decorations

            mode = self.state.get_aesthetic_mode()
            tile_bg, border_color = self._get_aesthetic_colors()

            left = max(0.0, rect.left())
            right = min(self.sceneRect().right(), rect.right())
            top = max(0.0, rect.top())
            bottom = min(self.sceneRect().bottom(), rect.bottom())

            start_col = int(left // TILE_SIZE)
            end_col = int(right // TILE_SIZE) + 1
            start_row = int(top // TILE_SIZE)
            end_row = int(bottom // TILE_SIZE) + 1

            # Fill tiles with background color (with gradient for some modes)
            for row in range(start_row, min(end_row, GARDEN_HEIGHT)):
                for col in range(start_col, min(end_col, GARDEN_WIDTH)):
                    x = col * TILE_SIZE
                    y = row * TILE_SIZE
                    tile_rect = QRectF(x, y, TILE_SIZE, TILE_SIZE)
                    
                    # Apply gradient for certain modes
                    if mode == "summer":
                        # Bright sunlight gradient
                        tile_gradient = QLinearGradient(x, y, x + TILE_SIZE, y + TILE_SIZE)
                        tile_gradient.setColorAt(0, tile_bg.lighter(110))
                        tile_gradient.setColorAt(1, tile_bg)
                        painter.setBrush(tile_gradient)
                    elif mode == "night":
                        # Subtle moonlight gradient
                        tile_gradient = QLinearGradient(x, y, x + TILE_SIZE, y + TILE_SIZE)
                        tile_gradient.setColorAt(0, QColor(tile_bg.red() + 5, tile_bg.green() + 5, tile_bg.blue() + 10))
                        tile_gradient.setColorAt(1, tile_bg)
                        painter.setBrush(tile_gradient)
                    elif mode == "spring":
                        # Soft spring gradient
                        tile_gradient = QLinearGradient(x, y, x + TILE_SIZE, y + TILE_SIZE)
                        tile_gradient.setColorAt(0, tile_bg.lighter(105))
                        tile_gradient.setColorAt(1, tile_bg)
                        painter.setBrush(tile_gradient)
                    else:
                        painter.setBrush(tile_bg)
                    
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRect(tile_rect)
                    
                    # Draw decorations
                    self._draw_tile_decorations(painter, x, y, mode)

            # Draw borders
            pen = QPen(border_color)
            pen.setWidthF(1.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            for col in range(start_col, min(end_col, GARDEN_WIDTH + 1)):
                x = col * TILE_SIZE
                painter.drawLine(x, 0, x, GARDEN_HEIGHT * TILE_SIZE)
            for row in range(start_row, min(end_row, GARDEN_HEIGHT + 1)):
                y = row * TILE_SIZE
                painter.drawLine(0, y, GARDEN_WIDTH * TILE_SIZE, y)
            
            # Draw paths on edges
            self._draw_paths(painter, start_row, end_row, start_col, end_col)

            painter.restore()
        except Exception:
            self._report_nonfatal("drawBackground", "AnkiGarden: grid render error.", exc_info=True)
    
    def _draw_paths(self, painter: QPainter, start_row: int, end_row: int, start_col: int, end_col: int) -> None:
        """Draw detailed cobblestone paths on edges."""
        try:
            paths = self.state.get_paths()
            if not paths:
                return
            
            mode = self.state.get_aesthetic_mode()
            
            # Get theme-adaptive cobblestone colors
            base_color = QColor(200, 200, 200)  # Light grey base
            if mode == "night":
                base_color = QColor(180, 180, 200)  # Slightly blue-tinted
            elif mode == "summer":
                base_color = QColor(220, 220, 200)  # Warm beige-tinted
            elif mode == "winter":
                base_color = QColor(220, 230, 240)  # Cool blue-white
            elif mode == "spring":
                base_color = QColor(210, 220, 200)  # Soft green-tinted
            elif mode == "autumn":
                base_color = QColor(220, 210, 190)  # Warm orange-tinted
            
            # Cobblestone colors
            stone_dark = base_color.darker(115)
            stone_light = base_color.lighter(110)
            stone_mid = base_color
            
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            
            for row, col, direction in paths:
                if row < start_row or row >= end_row or col < start_col or col >= end_col:
                    continue
                
                x = col * TILE_SIZE
                y = row * TILE_SIZE
                
                # Draw cobblestones based on direction
                if direction == "n":  # North edge (top)
                    self._draw_cobblestone_line(painter, x, y, x + TILE_SIZE, y, stone_dark, stone_light, stone_mid, horizontal=True)
                elif direction == "s":  # South edge (bottom)
                    self._draw_cobblestone_line(painter, x, y + TILE_SIZE, x + TILE_SIZE, y + TILE_SIZE, stone_dark, stone_light, stone_mid, horizontal=True)
                elif direction == "e":  # East edge (right)
                    self._draw_cobblestone_line(painter, x + TILE_SIZE, y, x + TILE_SIZE, y + TILE_SIZE, stone_dark, stone_light, stone_mid, horizontal=False)
                elif direction == "w":  # West edge (left)
                    self._draw_cobblestone_line(painter, x, y, x, y + TILE_SIZE, stone_dark, stone_light, stone_mid, horizontal=False)
        except Exception:
            self._report_nonfatal("_draw_paths", "AnkiGarden: path render error.", exc_info=True)
    
    def _draw_cobblestone_line(self, painter: QPainter, x1: float, y1: float, x2: float, y2: float, 
                               dark_color: QColor, light_color: QColor, mid_color: QColor, horizontal: bool) -> None:
        """Draw a line of cobblestones."""
        import random
        
        # Path width
        PATH_WIDTH = 6.0
        
        if horizontal:
            length = abs(x2 - x1)
            # Number of cobblestones (roughly 1 per 8-12 pixels)
            num_stones = max(3, int(length / 10))
            stone_width = length / num_stones
            
            for i in range(num_stones):
                stone_x = min(x1, x2) + i * stone_width
                stone_y = y1 - PATH_WIDTH / 2
                
                # Vary stone size slightly
                stone_seed = hash((int(stone_x), int(stone_y))) % 1000
                width_variation = stone_width * (0.8 + (stone_seed % 20) / 100.0)
                height_variation = PATH_WIDTH * (0.9 + (stone_seed % 10) / 100.0)
                
                # Draw individual cobblestone
                stone_rect = QRectF(stone_x, stone_y, width_variation, height_variation)
                
                # Choose color variation
                color_choice = stone_seed % 3
                if color_choice == 0:
                    stone_color = dark_color
                elif color_choice == 1:
                    stone_color = light_color
                else:
                    stone_color = mid_color
                
                # Draw stone with rounded corners effect
                painter.setBrush(stone_color)
                painter.setPen(QPen(stone_color.darker(120), 0.5))
                painter.drawRoundedRect(stone_rect, 1.5, 1.5)
                
                # Add highlight for depth
                highlight_rect = QRectF(stone_x + 0.5, stone_y + 0.5, width_variation * 0.4, height_variation * 0.3)
                highlight_gradient = QLinearGradient(highlight_rect.topLeft(), highlight_rect.bottomRight())
                highlight_gradient.setColorAt(0, light_color.lighter(120))
                highlight_gradient.setColorAt(1, Qt.GlobalColor.transparent)
                painter.setBrush(highlight_gradient)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(highlight_rect, 1.0, 1.0)
        else:
            # Vertical line
            length = abs(y2 - y1)
            num_stones = max(3, int(length / 10))
            stone_height = length / num_stones
            
            for i in range(num_stones):
                stone_x = x1 - PATH_WIDTH / 2
                stone_y = min(y1, y2) + i * stone_height
                
                # Vary stone size slightly
                stone_seed = hash((int(stone_x), int(stone_y))) % 1000
                width_variation = PATH_WIDTH * (0.9 + (stone_seed % 10) / 100.0)
                height_variation = stone_height * (0.8 + (stone_seed % 20) / 100.0)
                
                # Draw individual cobblestone
                stone_rect = QRectF(stone_x, stone_y, width_variation, height_variation)
                
                # Choose color variation
                color_choice = stone_seed % 3
                if color_choice == 0:
                    stone_color = dark_color
                elif color_choice == 1:
                    stone_color = light_color
                else:
                    stone_color = mid_color
                
                # Draw stone with rounded corners effect
                painter.setBrush(stone_color)
                painter.setPen(QPen(stone_color.darker(120), 0.5))
                painter.drawRoundedRect(stone_rect, 1.5, 1.5)
                
                # Add highlight for depth
                highlight_rect = QRectF(stone_x + 0.5, stone_y + 0.5, width_variation * 0.3, height_variation * 0.4)
                highlight_gradient = QLinearGradient(highlight_rect.topLeft(), highlight_rect.bottomRight())
                highlight_gradient.setColorAt(0, light_color.lighter(120))
                highlight_gradient.setColorAt(1, Qt.GlobalColor.transparent)
                painter.setBrush(highlight_gradient)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(highlight_rect, 1.0, 1.0)

    # Item management --------------------------------------------------
    def clear_items(self) -> None:
        try:
            for item in list(self.items_by_idx.values()):
                self.removeItem(item)
            self.items_by_idx.clear()
        except Exception:
            self._report_nonfatal("clear_items", "AnkiGarden: failed clearing items.", exc_info=True)

    def refresh_items(self) -> None:
        try:
            self.clear_items()
            tiles = self.state.get_tiles()
            now = utc_now()
            processed_indices = set()  # Track which tiles we've already processed (for 2x2 trees/cherry blossoms)
            
            # First pass: check for evolution
            for idx, tile in enumerate(tiles):
                if tile is None:
                    continue
                # Skip reference tiles (part of 2x2 cherry blossoms)
                if tile.get("is_reference"):
                    continue
                # Check and perform evolution if needed
                self.state._evolve_tile_if_needed(tile, idx)
            
            # Reload tiles after evolution
            tiles = self.state.get_tiles()
            
            # Second pass: render items
            for idx, tile in enumerate(tiles):
                if tile is None or idx in processed_indices:
                    continue
                # Skip reference tiles (part of 2x2 cherry blossoms)
                if tile.get("is_reference"):
                    continue
                    
                status = self.state.tile_status(tile, now)
                row, col = self.state.index_to_row_col(idx)
                kind = tile.get("kind") or "plant"
                
                # Position: for trees and cherry blossoms (2x2), center on the 2x2 block
                if kind in ("tree", "cherry_blossom"):
                    # Center on the 2x2 block (top-left tile is at row, col)
                    pos = QPointF(
                        col * TILE_SIZE + TILE_SIZE,  # Center of 2 tiles
                        row * TILE_SIZE + TILE_SIZE
                    )
                    # Mark all 4 tiles as processed
                    for dr in range(2):
                        for dc in range(2):
                            check_idx = self.state.row_col_to_index(row + dr, col + dc)
                            if check_idx is not None:
                                processed_indices.add(check_idx)
                else:
                    # Plants, seeds, colorful plants: center on single tile
                    pos = QPointF(
                        col * TILE_SIZE + TILE_SIZE / 2, row * TILE_SIZE + TILE_SIZE / 2
                    )
                
                item = GardenItem(state=self.state, kind=kind, tile_idx=idx, tile=tile)
                item.status = status
                item.setPos(pos)
                self.addItem(item)
                self.items_by_idx[idx] = item

            # Keep pending placement item on top if present.
            if self._pending_item is not None:
                self._pending_item.setZValue(10)
            
            # Force background to be redrawn by invalidating the entire scene
            # Invalidate the background layer to ensure tiles are redrawn
            try:
                self.invalidate(self.sceneRect(), QGraphicsScene.SceneLayer.BackgroundLayer)
            except AttributeError:
                # Fallback for older Qt versions - just update the entire scene
                self.update(self.sceneRect())
        except Exception:
            self._report_nonfatal("refresh_items", "AnkiGarden: failed refreshing scene.", exc_info=True)

    def begin_place(self, kind: str) -> bool:
        """Enter 'drag-to-place' mode by spawning a pending item."""
        try:
            if kind not in ("plant", "tree", "seed"):
                return False

            inv = self.state.get_inventory()
            if kind == "plant":
                inv_key = "plants"
            elif kind == "tree":
                inv_key = "trees"
            elif kind == "seed":
                inv_key = "seeds"
            else:
                return False
                
            if int(inv.get(inv_key, 0)) <= 0:
                return False

            # Disable watering mode when placing
            self._watering_mode = False

            # Only one pending item at a time.
            self.cancel_place()

            pending = GardenItem(state=self.state, kind=kind, tile_idx=None, tile=None)
            pending.setOpacity(0.85)
            pending.setZValue(10)
            pending.setPos(self.sceneRect().center())
            self.addItem(pending)
            self._pending_item = pending
            tooltip(
                "Drag onto an empty tile to place.",
                parent=self.views()[0] if self.views() else None,
            )
            return True
        except Exception:
            self._report_nonfatal("begin_place", "AnkiGarden: cannot begin placement.", exc_info=True)
            return False

    def cancel_place(self) -> None:
        try:
            if self._pending_item is not None:
                self.removeItem(self._pending_item)
                self._pending_item = None
        except Exception:
            self._report_nonfatal("cancel_place", "AnkiGarden: cannot cancel placement.", exc_info=True)

    # Drag/drop --------------------------------------------------------
    def handle_drop(self, item: GardenItem, scene_pos: QPointF) -> bool:
        """Attempt to snap to nearest tile/cross-hatch and update state.

        Plants (1x1) snap to tile centres; trees (2x2) snap to grid intersections
        (cross-hatches) between four tiles.
        """
        try:
            if item.kind in ("tree", "cherry_blossom"):
                # Snap to nearest grid intersection (cross-hatch)
                cross_row = int(round(scene_pos.y() / TILE_SIZE))
                cross_col = int(round(scene_pos.x() / TILE_SIZE))

                # Top-left tile of the 2x2 block is one up/left from the intersection.
                row = cross_row - 1
                col = cross_col - 1

                # Ensure tree/cherry blossom fits entirely within the garden.
                if row < 0 or col < 0 or row > GARDEN_HEIGHT - 2 or col > GARDEN_WIDTH - 2:
                    tooltip(
                        f"{item.kind.title()} must fit within garden (2x2 tiles).",
                        parent=self.views()[0] if self.views() else None,
                    )
                    return False

                # Center of the 2x2 block is exactly at the intersection.
                snapped_pos = QPointF(
                    cross_col * TILE_SIZE,
                    cross_row * TILE_SIZE,
                )
            else:
                # Plant, seed, colorful_plant: snap to centre of single tile.
                row = int(round((scene_pos.y() - TILE_SIZE / 2) / TILE_SIZE))
                col = int(round((scene_pos.x() - TILE_SIZE / 2) / TILE_SIZE))
                snapped_pos = QPointF(
                    col * TILE_SIZE + TILE_SIZE / 2, row * TILE_SIZE + TILE_SIZE / 2
                )

            idx = self.state.row_col_to_index(row, col)
            if idx is None:
                return False

            # Pending placement item: try to place new tile into state.
            if item.tile_idx is None:
                # For trees and cherry blossoms, check all 4 tiles are empty
                if item.kind in ("tree", "cherry_blossom"):
                    occupied_tiles = []
                    for dr in range(2):
                        for dc in range(2):
                            check_idx = self.state.row_col_to_index(row + dr, col + dc)
                            if check_idx is None:
                                tooltip(
                                    f"{item.kind.title()} must fit within garden.",
                                    parent=self.views()[0] if self.views() else None,
                                )
                                return False
                            if check_idx in self.items_by_idx:
                                occupied_tiles.append(check_idx)
                    if occupied_tiles:
                        tooltip(
                            "That area is occupied.",
                            parent=self.views()[0] if self.views() else None,
                        )
                        return False
                else:
                    # Plant, seed, colorful_plant: check single tile
                    if idx in self.items_by_idx:
                        tooltip(
                            "That tile is occupied.",
                            parent=self.views()[0] if self.views() else None,
                        )
                        return False
                
                created = self.state.place_at_index(item.kind, idx)
                if created is None:
                    tooltip(
                        "Cannot place (no inventory?).",
                        parent=self.views()[0] if self.views() else None,
                    )
                    return False

                # Convert pending into a placed item.
                item.tile_idx = idx
                item.tile = created
                item.setOpacity(1.0)
                item.setPos(snapped_pos)
                item.refresh_status()
                self.items_by_idx[idx] = item
                self._pending_item = None
                self.stateChanged.emit()
                return True

            # Placed item: attempt move
            if item.kind in ("tree", "cherry_blossom"):
                # For trees and cherry blossoms, check all 4 tiles are empty (except current item)
                occupied_tiles = []
                for dr in range(2):
                    for dc in range(2):
                        check_idx = self.state.row_col_to_index(row + dr, col + dc)
                        if check_idx is None:
                            return False
                        if check_idx in self.items_by_idx:
                            other_item = self.items_by_idx[check_idx]
                            # Allow if it's the same item (we're moving it)
                            if other_item is not item:
                                occupied_tiles.append(check_idx)
                if occupied_tiles:
                    return False
            else:
                # Plant, seed, colorful_plant: check single tile
                if idx in self.items_by_idx and self.items_by_idx[idx] is not item:
                    return False
            
            if item.tile_idx == idx:
                item.setPos(snapped_pos)
                return True
            
            if not self.state.move_tile(int(item.tile_idx), idx):
                return False

            # Update mapping and snap position.
            old_idx = int(item.tile_idx)
            if old_idx in self.items_by_idx:
                del self.items_by_idx[old_idx]
            item.tile_idx = idx
            item.setPos(snapped_pos)
            self.items_by_idx[idx] = item
            self.stateChanged.emit()
            return True
        except Exception:
            self._report_nonfatal("handle_drop", "AnkiGarden: error handling drop.", exc_info=True)
            return False

    def move_item_by_delta(self, item: GardenItem, drow: int, dcol: int) -> bool:
        """Move an item by a row/col delta (used for keyboard movement)."""

        try:
            if item.tile_idx is None:
                return False

            from_idx = int(item.tile_idx)
            from_row, from_col = self.state.index_to_row_col(from_idx)
            to_row = from_row + int(drow)
            to_col = from_col + int(dcol)

            idx = self.state.row_col_to_index(to_row, to_col)
            if idx is None:
                return False

            # For plants, seeds, colorful_plants, ensure destination tile isn't occupied by another item.
            if item.kind in ("plant", "seed", "colorful_plant"):
                if idx in self.items_by_idx and self.items_by_idx[idx] is not item:
                    return False

            # For trees and cherry blossoms, rely on state.move_tile() 2x2 occupancy checks.
            if not self.state.move_tile(from_idx, idx):
                return False

            # Update mapping and snap position.
            if from_idx in self.items_by_idx:
                del self.items_by_idx[from_idx]
            item.tile_idx = idx

            to_row2, to_col2 = self.state.index_to_row_col(idx)
            if item.kind in ("tree", "cherry_blossom"):
                # Center of 2x2 block
                snapped_pos = QPointF(
                    to_col2 * TILE_SIZE + TILE_SIZE,
                    to_row2 * TILE_SIZE + TILE_SIZE,
                )
            else:
                snapped_pos = QPointF(
                    to_col2 * TILE_SIZE + TILE_SIZE / 2,
                    to_row2 * TILE_SIZE + TILE_SIZE / 2,
                )

            item.setPos(snapped_pos)
            self.items_by_idx[idx] = item
            self.stateChanged.emit()
            return True
        except Exception:
            self._report_nonfatal("move_item_by_delta", "AnkiGarden: error moving item by keys.", exc_info=True)
            return False

    # Animations -------------------------------------------------------
    def _pulse_items(
        self,
        *,
        scale_from: float,
        scale_to: float,
        duration: int = 200,
        living_only: bool = True,
    ):
        self._animations = []
        for item in self.items_by_idx.values():
            if item.tile_idx is None:
                continue
            item.refresh_status()
            if living_only and item.status.is_dead:
                continue
            anim = QVariantAnimation()
            anim.setDuration(duration)
            anim.setStartValue(scale_from)
            anim.setEndValue(scale_to)
            anim.setEasingCurve(QEasingCurve.Type.OutQuad)

            def update(value, it=item):
                it.setScale(float(value))

            anim.valueChanged.connect(update)  # type: ignore[arg-type]

            def reset_state(it=item):
                it.setScale(1.0)

            anim.finished.connect(reset_state)
            anim.start()
            self._animations.append(anim)

    def splash(self):
        """Quick scale pulse for watering."""

        self._pulse_items(scale_from=1.0, scale_to=1.1, duration=180, living_only=True)

    def glow(self):
        """Quick scale/glow pulse for sunlight."""

        self._pulse_items(scale_from=1.0, scale_to=1.15, duration=220, living_only=True)

    def set_watering_mode(self, enabled: bool) -> None:
        """Enable or disable watering mode (click tiles to water them)."""
        self._watering_mode = enabled
        # Disable other modes when watering is enabled
        if enabled:
            self._path_placement_mode = False
            self._remove_mode = False
        # Update cursor for all views
        for view in self.views():
            if enabled:
                # Use pointing hand cursor to indicate clickable mode
                view.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                view.setCursor(Qt.CursorShape.ArrowCursor)
        # Clear hover overlay
        self._clear_hover_overlay()
    
    def set_path_placement_mode(self, enabled: bool) -> None:
        """Enable or disable path placement mode (click edges to place paths)."""
        self._path_placement_mode = enabled
        # Disable other modes when path placement is enabled
        if enabled:
            self._watering_mode = False
            self._remove_mode = False
            self._clear_hover_overlay()
        # Update cursor for all views
        for view in self.views():
            if enabled:
                view.setCursor(Qt.CursorShape.CrossCursor)
            else:
                view.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
    
    def set_remove_mode(self, enabled: bool) -> None:
        """Enable or disable remove object mode (click objects to remove them)."""
        self._remove_mode = enabled
        # Disable other modes when remove is enabled
        if enabled:
            self._watering_mode = False
            self._path_placement_mode = False
            self._clear_hover_overlay()
        # Update cursor for all views
        for view in self.views():
            if enabled:
                view.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                view.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def _clear_hover_overlay(self) -> None:
        """Remove the hover overlay for watering mode."""
        for overlay in self._watering_overlays:
            self.removeItem(overlay)
        self._watering_overlays.clear()
        self._hover_tile_row = None
        self._hover_tile_col = None

    def _update_hover_overlay(self, row: int, col: int) -> None:
        """Update the hover overlay to highlight the tile under the cursor."""
        if not self._watering_mode:
            return
        
        # Only update if tile changed
        if self._hover_tile_row == row and self._hover_tile_col == col:
            return
        
        self._clear_hover_overlay()
        self._hover_tile_row = row
        self._hover_tile_col = col
        
        # Check if this is a tree/cherry_blossom (2x2) or plant/seed/colorful_plant (1x1)
        idx = self.state.row_col_to_index(row, col)
        if idx is None:
            return
        
        tiles = self.state.get_tiles()
        if idx >= len(tiles) or tiles[idx] is None:
            return
        
        tile = tiles[idx]
        # Skip reference tiles, find the main tile
        if tile.get("is_reference"):
            main_id = tile.get("id")
            for t in tiles:
                if t is not None and t.get("id") == main_id and not t.get("is_reference"):
                    tile = t
                    break
        
        kind = tile.get("kind")
        
        # For trees and cherry blossoms, find the top-left tile
        if kind in ("tree", "cherry_blossom"):
            tree_idx = self.state._find_tree_at_tile(row, col)
            if tree_idx is None:
                return
            tree_row, tree_col = self.state.index_to_row_col(tree_idx)
            # Highlight all 4 tiles
            for dr in range(2):
                for dc in range(2):
                    highlight_row = tree_row + dr
                    highlight_col = tree_col + dc
                    x = highlight_col * TILE_SIZE
                    y = highlight_row * TILE_SIZE
                    overlay = QGraphicsEllipseItem(x + 2, y + 2, TILE_SIZE - 4, TILE_SIZE - 4)
                    overlay.setPen(QPen(QColor(100, 150, 255, 200), 3))  # Light blue border
                    overlay.setBrush(QColor(100, 150, 255, 30))  # Light blue fill
                    overlay.setZValue(1)  # Above background, below items
                    self.addItem(overlay)
                    self._watering_overlays.append(overlay)
        else:
            # Plant: highlight single tile
            x = col * TILE_SIZE
            y = row * TILE_SIZE
            overlay = QGraphicsEllipseItem(x + 2, y + 2, TILE_SIZE - 4, TILE_SIZE - 4)
            overlay.setPen(QPen(QColor(100, 150, 255, 200), 3))  # Light blue border
            overlay.setBrush(QColor(100, 150, 255, 30))  # Light blue fill
            overlay.setZValue(1)  # Above background, below items
            self.addItem(overlay)
            self._watering_overlays.append(overlay)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        """Handle mouse movement to show hover overlay in watering mode."""
        try:
            if self._watering_mode:
                scene_pos = event.scenePos()
                row = int(scene_pos.y() // TILE_SIZE)
                col = int(scene_pos.x() // TILE_SIZE)
                
                # Check bounds
                if 0 <= row < GARDEN_HEIGHT and 0 <= col < GARDEN_WIDTH:
                    self._update_hover_overlay(row, col)
                else:
                    self._clear_hover_overlay()
            else:
                self._clear_hover_overlay()
            
            super().mouseMoveEvent(event)
        except Exception:
            self._report_nonfatal("mouseMoveEvent", "AnkiGarden: error handling mouse move.", exc_info=True)
            super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """Handle mouse clicks for watering mode, path placement, and object removal."""
        try:
            scene_pos = event.scenePos()
            row = int(scene_pos.y() // TILE_SIZE)
            col = int(scene_pos.x() // TILE_SIZE)
            
            # Handle special tile clicks (only when not in any special mode)
            if not self._remove_mode and not self._path_placement_mode and not self._watering_mode:
                # Bottom left tile (row 6, col 0): toggle fast forward button
                if row == GARDEN_HEIGHT - 1 and col == 0:
                    self._bottom_left_clicks += 1
                    # Reset other tile's counter
                    self._bottom_right_clicks = 0
                    if self._bottom_left_clicks >= 10:
                        self._bottom_left_clicks = 0
                        if self.dialog_reference:
                            self.dialog_reference.toggle_fast_forward_button()
                        parent = self.views()[0] if self.views() else None
                        tooltip("Fast Forward button toggled!", parent=parent)
                    return
                
                # Bottom right tile (row 6, col 14): give 20000 coins
                if row == GARDEN_HEIGHT - 1 and col == GARDEN_WIDTH - 1:
                    self._bottom_right_clicks += 1
                    # Reset other tile's counter
                    self._bottom_left_clicks = 0
                    if self._bottom_right_clicks >= 10:
                        self._bottom_right_clicks = 0
                        self.state.award_token("coins", 20000)
                        parent = self.views()[0] if self.views() else None
                        tooltip("You received 20000 coins!", parent=parent)
                        self.stateChanged.emit()
                    return
                
                # Reset click counters if clicking elsewhere (only when not in special modes)
                if row != GARDEN_HEIGHT - 1 or col != 0:
                    self._bottom_left_clicks = 0
                if row != GARDEN_HEIGHT - 1 or col != GARDEN_WIDTH - 1:
                    self._bottom_right_clicks = 0
            
            if self._remove_mode:
                # Remove object mode: check for paths first, then objects
                x_in_tile = scene_pos.x() % TILE_SIZE
                y_in_tile = scene_pos.y() % TILE_SIZE
                EDGE_THRESHOLD = TILE_SIZE * 0.2  # 20% of tile size
                
                # Check if clicking near an edge (for path removal)
                direction = None
                if y_in_tile < EDGE_THRESHOLD and row > 0:
                    direction = "n"  # North edge
                elif y_in_tile > TILE_SIZE - EDGE_THRESHOLD and row < GARDEN_HEIGHT - 1:
                    direction = "s"  # South edge
                elif x_in_tile > TILE_SIZE - EDGE_THRESHOLD and col < GARDEN_WIDTH - 1:
                    direction = "e"  # East edge
                elif x_in_tile < EDGE_THRESHOLD and col > 0:
                    direction = "w"  # West edge
                
                if direction:
                    # Try to remove path at this edge
                    paths = self.state.get_paths()
                    path_key = (row, col, direction)
                    if path_key in paths:
                        success = self.state.remove_path(row, col, direction)
                        parent = self.views()[0] if self.views() else None
                        if success:
                            tooltip("Path removed and returned to inventory.", parent=parent)
                            self.update()  # Refresh to hide path
                            self.stateChanged.emit()
                        else:
                            tooltip("Failed to remove path.", parent=parent)
                        return
                
                # If no path found, try to remove object at clicked position
                idx = self.state.row_col_to_index(row, col)
                if idx is not None:
                    # Check if there's an item at this position
                    tiles = self.state.get_tiles()
                    tile = tiles[idx] if idx < len(tiles) else None
                    if tile is not None and not tile.get("is_reference"):
                        # Find the actual item (might be part of 2x2 tree/cherry blossom)
                        if tile.get("kind") in ("tree", "cherry_blossom"):
                            # Find top-left tile
                            top_left_idx = self.state._find_tree_at_tile(row, col)
                            if top_left_idx is not None:
                                idx = top_left_idx
                        
                        success, message = self.state.remove_object_at_index(idx)
                        parent = self.views()[0] if self.views() else None
                        tooltip(message, parent=parent)
                        if success:
                            self.refresh_items()
                            self.stateChanged.emit()
                return
            
            if self._path_placement_mode:
                # Path placement mode: detect which edge was clicked
                x_in_tile = scene_pos.x() % TILE_SIZE
                y_in_tile = scene_pos.y() % TILE_SIZE
                EDGE_THRESHOLD = TILE_SIZE * 0.2  # 20% of tile size
                
                direction = None
                if y_in_tile < EDGE_THRESHOLD and row > 0:
                    direction = "n"  # North edge
                elif y_in_tile > TILE_SIZE - EDGE_THRESHOLD and row < GARDEN_HEIGHT - 1:
                    direction = "s"  # South edge
                elif x_in_tile > TILE_SIZE - EDGE_THRESHOLD and col < GARDEN_WIDTH - 1:
                    direction = "e"  # East edge
                elif x_in_tile < EDGE_THRESHOLD and col > 0:
                    direction = "w"  # West edge
                
                if direction:
                    success, message = self.state.place_path(row, col, direction)
                    parent = self.views()[0] if self.views() else None
                    tooltip(message, parent=parent)
                    if success:
                        self.update()  # Refresh to show new path
                        self.stateChanged.emit()
                else:
                    parent = self.views()[0] if self.views() else None
                    tooltip("Click near an edge between tiles to place a path.", parent=parent)
                return
            
            if self._watering_mode:
                # Water the tile
                success, message = self.state.water_tile(row, col)
                
                parent = self.views()[0] if self.views() else None
                tooltip(message, parent=parent)
                
                if success:
                    # Find the item to animate
                    idx = self.state.row_col_to_index(row, col)
                    item = None
                    if idx is not None and idx in self.items_by_idx:
                        item = self.items_by_idx[idx]
                        # For trees and cherry blossoms, find the actual item
                        if item.tile is not None and item.tile.get("kind") in ("tree", "cherry_blossom"):
                            tree_idx = self.state._find_tree_at_tile(row, col)
                            if tree_idx is not None and tree_idx in self.items_by_idx:
                                item = self.items_by_idx[tree_idx]
                    
                    # Create water splash effect
                    self._create_water_splash(scene_pos, item)
                    
                    # Refresh items to show updated status
                    self.refresh_items()
                    self.stateChanged.emit()
                return
            
            # Default behavior: let items handle their own mouse events
            super().mousePressEvent(event)
        except Exception:
            self._report_nonfatal("mousePressEvent", "AnkiGarden: error handling mouse click.", exc_info=True)
            super().mousePressEvent(event)

    def _create_water_splash(self, pos: QPointF, item: Optional[GardenItem]) -> None:
        """Create a visual water splash effect at the given position."""
        try:
            # Create multiple water droplets
            for i in range(8):
                droplet = QGraphicsEllipseItem(0, 0, 6, 6)
                droplet.setBrush(QColor(173, 216, 230, 200))  # Light blue
                droplet.setPen(QPen(Qt.PenStyle.NoPen))
                droplet.setPos(pos)
                droplet.setZValue(100)  # Above everything
                self.addItem(droplet)
                
                # Animate droplet
                anim = QVariantAnimation()
                anim.setDuration(400)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutQuad)
                
                # Random direction for each droplet
                angle = (i * 45) * math.pi / 180  # 8 droplets in circle
                distance = 30 + (i % 3) * 10  # Varying distances
                
                def update(value, drop=droplet, a=angle, d=distance):
                    progress = float(value)
                    x = pos.x() + d * progress * math.cos(a)
                    y = pos.y() + d * progress * math.sin(a)
                    drop.setPos(x - 3, y - 3)
                    # Fade out
                    alpha = int(200 * (1 - progress))
                    drop.setBrush(QColor(173, 216, 230, alpha))
                
                anim.valueChanged.connect(update)  # type: ignore[arg-type]
                
                def remove_droplet(drop=droplet):
                    self.removeItem(drop)
                
                anim.finished.connect(remove_droplet)
                anim.start()
                self._animations.append(anim)
            
            # Also animate the item itself (scale + color flash)
            if item is not None:
                # Scale animation
                scale_anim = QVariantAnimation()
                scale_anim.setDuration(300)
                scale_anim.setStartValue(1.0)
                scale_anim.setEndValue(1.15)
                scale_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
                
                def update_scale(value, it=item):
                    it.setScale(float(value))
                
                scale_anim.valueChanged.connect(update_scale)  # type: ignore[arg-type]
                
                def reset_scale(it=item):
                    it.setScale(1.0)
                
                scale_anim.finished.connect(reset_scale)
                scale_anim.start()
                self._animations.append(scale_anim)
        except Exception:
            self._report_nonfatal("_create_water_splash", "AnkiGarden: error creating splash effect.", exc_info=True)


class GardenView(QGraphicsView):
    """View wrapper that hosts the GardenScene."""

    stateChanged = pyqtSignal()

    def __init__(self, state: AddonState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self.dialog_reference = None  # Reference to the dialog for special tile clicks
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMinimumSize(
            int(GARDEN_WIDTH * TILE_SIZE + 8), int(GARDEN_HEIGHT * TILE_SIZE + 8)
        )
        self.garden_scene = GardenScene(state, self)
        self.garden_scene.stateChanged.connect(self.stateChanged.emit)
        self.setScene(self.garden_scene)
    
    def set_dialog_reference(self, dialog) -> None:
        """Set reference to the dialog for special tile click handling."""
        self.dialog_reference = dialog
        self.garden_scene.set_dialog_reference(dialog)

    def refresh(self) -> None:
        self.garden_scene.refresh_items()
        # Force a full scene update to redraw background when mode changes
        self.garden_scene.update(self.garden_scene.sceneRect())

    def begin_place(self, kind: str) -> bool:
        return self.garden_scene.begin_place(kind)

    def set_watering_mode(self, enabled: bool) -> None:
        """Enable or disable watering mode."""
        self.garden_scene.set_watering_mode(enabled)
    
    def begin_place_path(self) -> bool:
        """Enter path placement mode."""
        inv = self.garden_scene.state.get_inventory()
        if inv.get("path", 0) <= 0:
            return False
        self.garden_scene.set_path_placement_mode(True)
        return True
    
    def set_remove_mode(self, enabled: bool) -> None:
        """Enable or disable remove object mode."""
        self.garden_scene.set_remove_mode(enabled)

    def splash(self) -> None:
        self.garden_scene.splash()

    def glow(self) -> None:
        self.garden_scene.glow()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        """Allow arrow keys to move the currently focused item."""

        try:
            key = event.key()
            focused = self.scene().focusItem() if self.scene() is not None else None  # type: ignore[union-attr]

            if isinstance(focused, GardenItem):
                drow = dcol = 0
                if key == Qt.Key_Left:
                    dcol = -1
                elif key == Qt.Key_Right:
                    dcol = 1
                elif key == Qt.Key_Up:
                    drow = -1
                elif key == Qt.Key_Down:
                    drow = 1

                if drow != 0 or dcol != 0:
                    moved = self.garden_scene.move_item_by_delta(focused, drow, dcol)
                    if moved:
                        return
        except Exception:
            # Never let key handling crash UI; just fall back to default.
            pass

        super().keyPressEvent(event)

