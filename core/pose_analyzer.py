"""身体姿态分析模块：站姿/坐姿自适应、手势、稳定性检测

基于 MediaPipe Pose Landmarker（0.10.x Tasks API）实现台风训练中的肢体语言分析。
支持两种模式：
- standing: 站姿演讲（传统台风训练）
- sitting: 坐姿录播（使用电脑/镜头训练场景）
"""
import math
import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Tuple

import numpy as np

try:
    import mediapipe as mp
    import cv2
    from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode
    from mediapipe.tasks.python.core.base_options import BaseOptions
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    mp = None
    cv2 = None

logger = logging.getLogger(__name__)

# MediaPipe Pose 关键点索引
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24
NOSE = 0

# 关键点可见性阈值
_VISIBILITY_THRESHOLD = 0.5

# 默认模型路径
DEFAULT_POSE_MODEL = Path(__file__).parent.parent / "models" / "pose_landmarker_lite.task"


@dataclass
class PoseFrameAnalysis:
    """单帧身体姿态分析"""
    timestamp: float
    pose_detected: bool = False
    # 站姿/坐姿通用
    shoulder_tilt: float = 0.0  # 肩膀倾斜度（度）
    body_lean: float = 0.0  # 身体前后倾斜（度）
    # 手势
    left_hand_height: float = 0.0
    right_hand_height: float = 0.0
    is_gesturing: bool = False
    # 稳定性
    movement: float = 0.0
    # 坐姿特有
    head_forward: float = 0.0  # 头部前倾（探颈）程度


@dataclass
class PoseSessionSummary:
    """身体姿态训练汇总"""
    duration: float = 0.0
    mode: str = "sitting"  # 'sitting' or 'standing'
    # 评分（0-100）
    posture_score: float = 0.0
    gesture_score: float = 0.0
    stability_score: float = 0.0
    # 详细统计
    avg_shoulder_tilt: float = 0.0
    avg_body_lean: float = 0.0
    avg_head_forward: float = 0.0  # 坐姿探颈
    gesture_ratio: float = 0.0
    avg_movement: float = 0.0
    max_movement: float = 0.0
    timeline: List[PoseFrameAnalysis] = field(default_factory=list)


class PoseAnalyzer:
    """身体姿态分析器（支持坐姿/站姿）"""

    def __init__(self, mode: str = "sitting", model_path: Optional[str] = None):
        """
        Args:
            mode: 'sitting'（坐姿，电脑前训练）或 'standing'（站姿，模拟演讲）
            model_path: Pose Landmarker 模型路径，默认使用 models/pose_landmarker_lite.task
        """
        if not MEDIAPIPE_AVAILABLE:
            raise ImportError(
                "MediaPipe 未安装。请运行: pip install mediapipe opencv-python"
            )
        self.mode = mode if mode in ("sitting", "standing") else "sitting"
        self._model_path = Path(model_path) if model_path else DEFAULT_POSE_MODEL
        self._landmarker: Optional[PoseLandmarker] = None
        self._prev_keypoints: Optional[np.ndarray] = None
        self._movement_buffer: deque = deque(maxlen=10)

    def set_mode(self, mode: str):
        """切换坐姿/站姿模式"""
        if mode in ("sitting", "standing"):
            self.mode = mode

    def initialize(self):
        if self._landmarker is not None:
            return
        if not self._model_path.exists():
            raise FileNotFoundError(
                f"Pose Landmarker 模型文件不存在: {self._model_path}\n"
                f"请从 https://developers.google.com/mediapipe/solutions/vision/pose_landmarker 下载模型"
            )
        try:
            options = PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(self._model_path)),
                running_mode=RunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=0.5,
                min_pose_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._landmarker = PoseLandmarker.create_from_options(options)
        except Exception as exc:
            logger.error(f"初始化 Pose Landmarker 失败: {exc}")
            raise

    def close(self):
        if self._landmarker:
            try:
                self._landmarker.close()
            except Exception as exc:
                logger.warning(f"关闭 Pose Landmarker 时出错: {exc}")
            self._landmarker = None
        self.reset_state()

    def reset_state(self):
        """重置会话状态"""
        self._prev_keypoints = None
        self._movement_buffer.clear()

    def _is_valid_frame(self, frame_bgr) -> bool:
        """验证输入帧是否有效"""
        if frame_bgr is None:
            return False
        if not isinstance(frame_bgr, np.ndarray):
            return False
        if frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            return False
        if frame_bgr.size == 0:
            return False
        return True

    def _landmark_visible(self, lm, idx: int) -> bool:
        """检查关键点是否可见"""
        try:
            return getattr(lm[idx], "visibility", 1.0) >= _VISIBILITY_THRESHOLD
        except Exception:
            return False

    def analyze_frame(self, frame_bgr: np.ndarray, timestamp: float) -> PoseFrameAnalysis:
        """分析单帧身体姿态"""
        result = PoseFrameAnalysis(timestamp=timestamp)

        if not self._is_valid_frame(frame_bgr):
            return result

        try:
            self.initialize()
        except Exception:
            return result

        try:
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            mp_result = self._landmarker.detect_for_video(mp_image, int(timestamp * 1000))
        except Exception as exc:
            logger.warning(f"姿态处理失败: {exc}")
            return result

        if not mp_result or not mp_result.pose_landmarks:
            return result

        landmarks = mp_result.pose_landmarks[0]
        if len(landmarks) < 25:
            return result

        result.pose_detected = True
        lm = landmarks

        # 检查必要关键点可见性
        required_indices = [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, NOSE]
        if not all(self._landmark_visible(lm, i) for i in required_indices):
            return result

        # 关键点
        left_shoulder = np.array([lm[LEFT_SHOULDER].x, lm[LEFT_SHOULDER].y])
        right_shoulder = np.array([lm[RIGHT_SHOULDER].x, lm[RIGHT_SHOULDER].y])
        left_hip = np.array([lm[LEFT_HIP].x, lm[LEFT_HIP].y])
        right_hip = np.array([lm[RIGHT_HIP].x, lm[RIGHT_HIP].y])
        nose = np.array([lm[NOSE].x, lm[NOSE].y])

        shoulder_center = (left_shoulder + right_shoulder) / 2
        hip_center = (left_hip + right_hip) / 2
        body_height = abs(shoulder_center[1] - hip_center[1])
        shoulder_width = abs(left_shoulder[0] - right_shoulder[0])

        # 1. 肩膀倾斜（两种模式通用）
        try:
            if shoulder_width > 0.01:
                shoulder_diff = left_shoulder[1] - right_shoulder[1]
                result.shoulder_tilt = math.degrees(math.atan2(shoulder_diff, shoulder_width))
        except Exception as exc:
            logger.debug(f"肩膀倾斜计算失败: {exc}")

        # 2. 身体前后倾斜
        try:
            if body_height > 0.01:
                x_offset = shoulder_center[0] - hip_center[0]
                result.body_lean = math.degrees(math.atan2(x_offset, body_height))
        except Exception as exc:
            logger.debug(f"身体倾斜计算失败: {exc}")

        # 3. 坐姿特有：探颈检测（头部相对肩膀前伸）
        try:
            if self.mode == "sitting" and shoulder_width > 0.01:
                # 鼻子 x 坐标相对肩膀中心的偏移（归一化到肩宽）
                head_x_offset = (nose[0] - shoulder_center[0]) / shoulder_width
                # 正常应接近 0，> 0.15 为探颈
                result.head_forward = max(0, head_x_offset - 0.05)
        except Exception as exc:
            logger.debug(f"探颈检测失败: {exc}")

        # 4. 手势：手腕高度
        try:
            if body_height > 0.01:
                left_wrist_visible = self._landmark_visible(lm, LEFT_WRIST)
                right_wrist_visible = self._landmark_visible(lm, RIGHT_WRIST)

                if left_wrist_visible:
                    left_wrist = np.array([lm[LEFT_WRIST].x, lm[LEFT_WRIST].y])
                    result.left_hand_height = (hip_center[1] - left_wrist[1]) / body_height
                if right_wrist_visible:
                    right_wrist = np.array([lm[RIGHT_WRIST].x, lm[RIGHT_WRIST].y])
                    result.right_hand_height = (hip_center[1] - right_wrist[1]) / body_height

                if self.mode == "standing":
                    # 站姿：手在腰部以上、肩部以下视为手势区
                    result.is_gesturing = (
                        0.2 < result.left_hand_height < 1.2 or
                        0.2 < result.right_hand_height < 1.2
                    )
                else:
                    # 坐姿：手在桌面以上、肩部以下视为手势区
                    result.is_gesturing = (
                        0.0 < result.left_hand_height < 1.1 or
                        0.0 < result.right_hand_height < 1.1
                    )
        except Exception as exc:
            logger.debug(f"手势检测失败: {exc}")

        # 5. 稳定性
        try:
            current_kp = np.array([
                [lm[LEFT_SHOULDER].x, lm[LEFT_SHOULDER].y],
                [lm[RIGHT_SHOULDER].x, lm[RIGHT_SHOULDER].y],
                [lm[LEFT_HIP].x, lm[LEFT_HIP].y],
                [lm[RIGHT_HIP].x, lm[RIGHT_HIP].y],
                [lm[NOSE].x, lm[NOSE].y],
            ])
            if self._prev_keypoints is not None and current_kp.shape == self._prev_keypoints.shape:
                raw_movement = float(np.mean(np.linalg.norm(current_kp - self._prev_keypoints, axis=1)))
                self._movement_buffer.append(raw_movement)
                # 使用中位数平滑，降低离群值影响
                result.movement = float(np.median(self._movement_buffer)) if self._movement_buffer else raw_movement
            self._prev_keypoints = current_kp
        except Exception as exc:
            logger.debug(f"稳定性计算失败: {exc}")

        return result

    def summarize_session(self, timeline: List[PoseFrameAnalysis]) -> PoseSessionSummary:
        """汇总身体姿态训练"""
        if not timeline:
            return PoseSessionSummary(mode=self.mode)

        summary = PoseSessionSummary(timeline=timeline, mode=self.mode)
        valid = [f for f in timeline if f.pose_detected]
        if not valid:
            return summary

        summary.duration = timeline[-1].timestamp - timeline[0].timestamp if len(timeline) > 1 else 0

        # 站姿评分
        tilts = [abs(f.shoulder_tilt) for f in valid]
        leans = [abs(f.body_lean) for f in valid]
        summary.avg_shoulder_tilt = sum(tilts) / len(tilts) if tilts else 0.0
        summary.avg_body_lean = sum(leans) / len(leans) if leans else 0.0

        if self.mode == "standing":
            # 站姿：倾斜 < 5 度为佳
            posture_penalty = (summary.avg_shoulder_tilt + summary.avg_body_lean) * 4
            summary.posture_score = max(0, 100 - posture_penalty)
        else:
            # 坐姿：肩膀倾斜 + 探颈检测
            head_forwards = [f.head_forward for f in valid]
            summary.avg_head_forward = sum(head_forwards) / len(head_forwards) if head_forwards else 0.0
            # 探颈 > 0.15 开始扣分
            forward_penalty = max(0, summary.avg_head_forward - 0.10) * 200
            tilt_penalty = summary.avg_shoulder_tilt * 5
            summary.posture_score = max(0, 100 - forward_penalty - tilt_penalty)

        # 手势评分
        gestures = [f.is_gesturing for f in valid]
        summary.gesture_ratio = sum(gestures) / len(gestures) if gestures else 0.0
        if self.mode == "standing":
            # 站姿：20%-60% 手势时长为佳
            if 0.2 <= summary.gesture_ratio <= 0.6:
                summary.gesture_score = 90
            elif summary.gesture_ratio < 0.2:
                summary.gesture_score = 60
            else:
                summary.gesture_score = max(40, 100 - (summary.gesture_ratio - 0.6) * 100)
        else:
            # 坐姿：10%-50% 手势时长为佳（坐姿手势自然较少）
            if 0.1 <= summary.gesture_ratio <= 0.5:
                summary.gesture_score = 90
            elif summary.gesture_ratio < 0.1:
                summary.gesture_score = 70  # 坐姿手势少可以接受
            else:
                summary.gesture_score = max(40, 100 - (summary.gesture_ratio - 0.5) * 120)

        # 稳定性评分
        movements = [f.movement for f in valid]
        summary.avg_movement = sum(movements) / len(movements) if movements else 0.0
        summary.max_movement = max(movements) if movements else 0
        if self.mode == "standing":
            summary.stability_score = max(0, 100 - summary.avg_movement * 1500)
        else:
            # 坐姿稳定性要求略低
            summary.stability_score = max(0, 100 - summary.avg_movement * 1200)

        return summary


def is_mediapipe_available() -> bool:
    """检查 MediaPipe 是否可用"""
    return MEDIAPIPE_AVAILABLE
