"""摄像头实时预览组件

用于台风训练时实时显示摄像头画面，支持叠加分析结果可视化。
"""
import time
from typing import Optional, Callable

import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

from PySide6.QtCore import Qt, QTimer, Signal, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QFont, QBrush
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QSizePolicy, QFrame
)


class CameraView(QWidget):
    """摄像头实时预览组件

    信号:
        frame_ready: 每帧图像就绪（BGR numpy 数组 + 时间戳）
    """

    frame_ready = Signal(object, float)  # frame_bgr, timestamp

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cap = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timeout)
        self._timer.setInterval(33)  # ~30 FPS
        self._is_running = False
        self._start_time = 0.0
        self._overlay_data = None  # 叠加显示的数据
        self._mirror = True  # 镜像（自拍模式）

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 视频显示区域
        self._video_label = QLabel()
        self._video_label.setAlignment(Qt.AlignCenter)
        self._video_label.setMinimumSize(480, 360)
        self._video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._video_label.setStyleSheet("""
            QLabel {
                background-color: #1a1a1a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                color: #888;
                font-size: 14px;
            }
        """)
        self._video_label.setText("摄像头未开启\n点击\"开始训练\"启动")
        layout.addWidget(self._video_label)

        # 状态栏
        status_layout = QHBoxLayout()
        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #666; font-size: 12px;")
        self._time_label = QLabel("00:00")
        self._time_label.setStyleSheet("color: #c0392b; font-size: 16px; font-weight: bold;")
        status_layout.addWidget(self._status_label)
        status_layout.addStretch()
        status_layout.addWidget(self._time_label)
        layout.addLayout(status_layout)

    def start(self, camera_index: int = 0) -> bool:
        """启动摄像头

        Args:
            camera_index: 摄像头索引（0=默认摄像头）

        Returns:
            是否成功启动
        """
        if not CV2_AVAILABLE:
            self._status_label.setText("错误：OpenCV 未安装")
            return False

        if self._is_running:
            return True

        self._cap = cv2.VideoCapture(camera_index)
        if not self._cap.isOpened():
            self._status_label.setText("错误：无法打开摄像头")
            self._cap = None
            return False

        # 设置分辨率
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        self._is_running = True
        self._start_time = time.time()
        self._timer.start()
        self._status_label.setText("训练中...")
        return True

    def stop(self):
        """停止摄像头"""
        self._timer.stop()
        self._is_running = False
        if self._cap:
            self._cap.release()
            self._cap = None
        self._status_label.setText("已停止")
        self._overlay_data = None

    def is_running(self) -> bool:
        return self._is_running

    def set_overlay(self, data: Optional[dict]):
        """设置叠加显示数据

        Args:
            data: 包含分析结果的字典，例如：
                {
                    'eye_contact': 0.85,
                    'smile': 0.6,
                    'head_yaw': 5.2,
                    'is_gesturing': True,
                    'posture_ok': True,
                }
        """
        self._overlay_data = data

    def set_mirror(self, mirror: bool):
        """设置是否镜像显示"""
        self._mirror = mirror

    def _on_timeout(self):
        if not self._cap or not self._is_running:
            return

        ret, frame = self._cap.read()
        if not ret:
            return

        timestamp = time.time() - self._start_time

        # 镜像
        if self._mirror:
            frame = cv2.flip(frame, 1)

        # 发送原始帧给分析器
        self.frame_ready.emit(frame.copy(), timestamp)

        # 绘制叠加层
        display_frame = self._draw_overlay(frame, timestamp)
        self._update_display(display_frame)

        # 更新时间显示
        mins = int(timestamp // 60)
        secs = int(timestamp % 60)
        self._time_label.setText(f"{mins:02d}:{secs:02d}")

    def _draw_overlay(self, frame: np.ndarray, timestamp: float) -> np.ndarray:
        """在帧上绘制叠加信息"""
        if not self._overlay_data:
            return frame

        data = self._overlay_data
        h, w = frame.shape[:2]

        # 半透明背景条
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 80), (0, 0, 0), -1)
        cv2.rectangle(overlay, (0, h - 100), (w, h), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.5, frame, 0.5, 0)

        # 顶部：眼神交流
        eye_contact = data.get('eye_contact', 0)
        eye_color = (0, 200, 0) if eye_contact > 0.6 else (0, 200, 200) if eye_contact > 0.4 else (0, 0, 200)
        cv2.putText(frame, f"Eye Contact: {eye_contact:.0%}", (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, eye_color, 2)

        # 微笑
        smile = data.get('smile', 0)
        cv2.putText(frame, f"Smile: {smile:.0%}", (300, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 200), 2)

        # 头部姿态
        head_yaw = data.get('head_yaw', 0)
        cv2.putText(frame, f"Head Yaw: {head_yaw:.1f}°", (500, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 0), 2)

        # 底部：手势和姿态
        is_gesturing = data.get('is_gesturing', False)
        gesture_text = "Gesturing: YES" if is_gesturing else "Gesturing: NO"
        gesture_color = (0, 200, 0) if is_gesturing else (128, 128, 128)
        cv2.putText(frame, gesture_text, (20, h - 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, gesture_color, 2)

        posture_ok = data.get('posture_ok', True)
        posture_text = "Posture: GOOD" if posture_ok else "Posture: CHECK"
        posture_color = (0, 200, 0) if posture_ok else (0, 0, 200)
        cv2.putText(frame, posture_text, (300, h - 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, posture_color, 2)

        # 提示文字
        if data.get('warning'):
            cv2.putText(frame, data['warning'], (20, h - 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 200), 2)

        return frame

    def _update_display(self, frame: np.ndarray):
        """更新显示"""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = frame.shape[:2]
        bytes_per_line = 3 * w
        q_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)

        # 缩放适应标签大小
        scaled = pixmap.scaled(
            self._video_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self._video_label.setPixmap(scaled)

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
