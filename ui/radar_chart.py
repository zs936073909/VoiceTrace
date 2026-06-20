"""雷达图组件：可视化展示台风训练各维度评分

使用 QPainter 自绘，支持 Dark/Light 主题。
"""
import math
from typing import List, Tuple, Optional

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QPolygonF
)
from PySide6.QtWidgets import QWidget


class RadarChart(QWidget):
    """雷达图组件

    用于展示台风训练的六维评分：
    眼神交流、表情管理、头部姿态、站姿、手势、稳定性
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 360)
        self._labels: List[str] = []
        self._values: List[float] = []  # 0-100
        self._max_value = 100.0
        self._theme = "light"

    def set_data(self, labels: List[str], values: List[float]):
        """设置雷达图数据

        Args:
            labels: 各维度标签
            values: 各维度数值（0-100）
        """
        self._labels = labels[:]
        self._values = [max(0, min(100, v)) for v in values]
        self.update()

    def set_theme(self, theme: str):
        """设置主题 ('light' 或 'dark')"""
        self._theme = theme
        self.update()

    def _get_colors(self) -> dict:
        if self._theme == "dark":
            return {
                "bg": QColor(30, 30, 35),
                "grid": QColor(70, 70, 80),
                "text": QColor(220, 220, 225),
                "fill": QColor(192, 57, 43, 80),
                "border": QColor(192, 57, 43, 220),
                "point": QColor(231, 76, 60),
                "axis": QColor(80, 80, 90),
            }
        else:
            return {
                "bg": QColor(250, 249, 246),
                "grid": QColor(212, 207, 196),
                "text": QColor(43, 43, 43),
                "fill": QColor(192, 57, 43, 60),
                "border": QColor(192, 57, 43, 200),
                "point": QColor(231, 76, 60),
                "axis": QColor(180, 175, 165),
            }

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        colors = self._get_colors()
        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h / 2
        radius = min(w, h) / 2 - 50

        # 背景
        painter.fillRect(self.rect(), colors["bg"])

        if not self._labels:
            painter.setPen(colors["text"])
            painter.setFont(QFont("Microsoft YaHei", 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无数据")
            return

        n = len(self._labels)
        if n < 3:
            painter.setPen(colors["text"])
            painter.setFont(QFont("Microsoft YaHei", 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "至少需要 3 个维度")
            return

        # 绘制网格（5 层）
        grid_pen = QPen(colors["grid"], 1, Qt.DashLine)
        painter.setPen(grid_pen)

        for level in range(1, 6):
            r = radius * level / 5
            polygon = QPolygonF()
            for i in range(n):
                angle = -math.pi / 2 + 2 * math.pi * i / n
                x = cx + r * math.cos(angle)
                y = cy + r * math.sin(angle)
                polygon.append(QPointF(x, y))
            polygon.append(polygon[0])
            painter.drawPolygon(polygon)

        # 绘制轴线
        axis_pen = QPen(colors["axis"], 1)
        painter.setPen(axis_pen)
        for i in range(n):
            angle = -math.pi / 2 + 2 * math.pi * i / n
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            painter.drawLine(QPointF(cx, cy), QPointF(x, y))

        # 绘制数据多边形
        if self._values:
            data_polygon = QPolygonF()
            for i in range(n):
                angle = -math.pi / 2 + 2 * math.pi * i / n
                r = radius * self._values[i] / self._max_value
                x = cx + r * math.cos(angle)
                y = cy + r * math.sin(angle)
                data_polygon.append(QPointF(x, y))
            data_polygon.append(data_polygon[0])

            # 填充
            painter.setBrush(QBrush(colors["fill"]))
            painter.setPen(QPen(colors["border"], 2))
            painter.drawPolygon(data_polygon)

            # 数据点
            painter.setBrush(QBrush(colors["point"]))
            painter.setPen(Qt.NoPen)
            for i in range(n):
                angle = -math.pi / 2 + 2 * math.pi * i / n
                r = radius * self._values[i] / self._max_value
                x = cx + r * math.cos(angle)
                y = cy + r * math.sin(angle)
                painter.drawEllipse(QPointF(x, y), 4, 4)

        # 绘制标签
        painter.setPen(colors["text"])
        label_font = QFont("Microsoft YaHei", 10, QFont.Bold)
        painter.setFont(label_font)

        for i in range(n):
            angle = -math.pi / 2 + 2 * math.pi * i / n
            label_r = radius + 25
            x = cx + label_r * math.cos(angle)
            y = cy + label_r * math.sin(angle)

            # 标签文字
            label = self._labels[i]
            value = self._values[i] if i < len(self._values) else 0
            text = f"{label}\n{value:.0f}"

            text_rect = painter.boundingRect(
                QRectF(x - 60, y - 25, 120, 50),
                Qt.AlignCenter,
                label
            )
            painter.drawText(text_rect, Qt.AlignCenter, label)

            # 数值
            value_font = QFont("Microsoft YaHei", 9)
            painter.setFont(value_font)
            value_rect = painter.boundingRect(
                QRectF(x - 60, y - 5, 120, 30),
                Qt.AlignCenter,
                f"{value:.0f}"
            )
            painter.drawText(value_rect, Qt.AlignCenter, f"{value:.0f}")
            painter.setFont(label_font)
