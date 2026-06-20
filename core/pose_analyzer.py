"""身体姿态分析模块：站姿/坐姿自适应、手势、稳定性检测

基于 MediaPipe Pose（33 点）实现台风训练中的肢体语言分析。
支持两种模式：
- standing: 站姿演讲（传统台风训练）
- sitting: 坐姿录播（使用电脑/镜头训练场景）
"""
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

import numpy as np

try:
    import mediapipe as mp
    import cv2
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    mp = None
    cv2 = None


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

    def __init__(self, mode: str = "sitting"):
        """
        Args:
            mode: 'sitting'（坐姿，电脑前训练）或 'standing'（站姿，模拟演讲）
        """
        if not MEDIAPIPE_AVAILABLE:
            raise ImportError(
                "MediaPipe 未安装。请运行: pip install mediapipe opencv-python"
            )
        self.mode = mode
        self._pose = None
        self._prev_keypoints: Optional[np.ndarray] = None

    def set_mode(self, mode: str):
        """切换坐姿/站姿模式"""
        if mode in ("sitting", "standing"):
            self.mode = mode

    def initialize(self):
        if self._pose is None:
            self._pose = mp.solutions.pose.Pose(
                static_image_mode=False,
                model_complexity=1,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )

    def close(self):
        if self._pose:
            self._pose.close()
            self._pose = None

    def analyze_frame(self, frame_bgr: np.ndarray, timestamp: float) -> PoseFrameAnalysis:
        """分析单帧身体姿态"""
        self.initialize()
        result = PoseFrameAnalysis(timestamp=timestamp)

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_result = self._pose.process(rgb)

        if not mp_result.pose_landmarks:
            return result

        result.pose_detected = True
        lm = mp_result.pose_landmarks.landmark

        # 关键点
        left_shoulder = np.array([lm[LEFT_SHOULDER].x, lm[LEFT_SHOULDER].y])
        right_shoulder = np.array([lm[RIGHT_SHOULDER].x, lm[RIGHT_SHOULDER].y])
        left_hip = np.array([lm[LEFT_HIP].x, lm[LEFT_HIP].y])
        right_hip = np.array([lm[RIGHT_HIP].x, lm[RIGHT_HIP].y])
        nose = np.array([lm[NOSE].x, lm[NOSE].y])
        left_wrist = np.array([lm[LEFT_WRIST].x, lm[LEFT_WRIST].y])
        right_wrist = np.array([lm[RIGHT_WRIST].x, lm[RIGHT_WRIST].y])

        shoulder_center = (left_shoulder + right_shoulder) / 2
        hip_center = (left_hip + right_hip) / 2
        body_height = abs(shoulder_center[1] - hip_center[1])

        # 1. 肩膀倾斜（两种模式通用）
        shoulder_diff = left_shoulder[1] - right_shoulder[1]
        shoulder_width = abs(left_shoulder[0] - right_shoulder[0])
        if shoulder_width > 0.01:
            result.shoulder_tilt = math.degrees(math.atan2(shoulder_diff, shoulder_width))

        # 2. 身体前后倾斜
        if body_height > 0.01:
            x_offset = shoulder_center[0] - hip_center[0]
            result.body_lean = math.degrees(math.atan2(x_offset, body_height))

        # 3. 坐姿特有：探颈检测（头部相对肩膀前伸）
        if self.mode == "sitting" and shoulder_width > 0.01:
            # 鼻子 x 坐标相对肩膀中心的偏移（归一化到肩宽）
            head_x_offset = (nose[0] - shoulder_center[0]) / shoulder_width
            # 正常应接近 0，> 0.15 为探颈
            result.head_forward = max(0, head_x_offset - 0.05)

        # 4. 手势：手腕高度
        if body_height > 0.01:
            result.left_hand_height = (hip_center[1] - left_wrist[1]) / body_height
            result.right_hand_height = (hip_center[1] - right_wrist[1]) / body_height

            if self.mode == "standing":
                # 站姿：手在腰部以上、肩部以下视为手势区
                result.is_gesturing = (
                    0.2 < result.left_hand_height < 1.2 or
                    0.2 < result.right_hand_height < 1.2
                )
            else:
                # 坐姿：手在桌面以上、肩部以下视为手势区
                # 坐姿时手通常在胸前/桌面，阈值调整
                result.is_gesturing = (
                    0.0 < result.left_hand_height < 1.1 or
                    0.0 < result.right_hand_height < 1.1
                )

        # 5. 稳定性
        current_kp = np.array([
            [lm[LEFT_SHOULDER].x, lm[LEFT_SHOULDER].y],
            [lm[RIGHT_SHOULDER].x, lm[RIGHT_SHOULDER].y],
            [lm[LEFT_HIP].x, lm[LEFT_HIP].y],
            [lm[RIGHT_HIP].x, lm[RIGHT_HIP].y],
            [lm[NOSE].x, lm[NOSE].y],
        ])
        if self._prev_keypoints is not None and current_kp.shape == self._prev_keypoints.shape:
            movement = float(np.mean(np.linalg.norm(current_kp - self._prev_keypoints, axis=1)))
            result.movement = movement
        self._prev_keypoints = current_kp

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
        summary.avg_shoulder_tilt = sum(tilts) / len(tilts)
        summary.avg_body_lean = sum(leans) / len(leans)

        if self.mode == "standing":
            # 站姿：倾斜 < 5 度为佳
            posture_penalty = (summary.avg_shoulder_tilt + summary.avg_body_lean) * 4
            summary.posture_score = max(0, 100 - posture_penalty)
        else:
            # 坐姿：肩膀倾斜 + 探颈检测
            head_forwards = [f.head_forward for f in valid]
            summary.avg_head_forward = sum(head_forwards) / len(head_forwards)
            # 探颈 > 0.15 开始扣分
            forward_penalty = max(0, summary.avg_head_forward - 0.10) * 200
            tilt_penalty = summary.avg_shoulder_tilt * 5
            summary.posture_score = max(0, 100 - forward_penalty - tilt_penalty)

        # 手势评分
        gestures = [f.is_gesturing for f in valid]
        summary.gesture_ratio = sum(gestures) / len(gestures)
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
        summary.avg_movement = sum(movements) / len(movements)
        summary.max_movement = max(movements) if movements else 0
        if self.mode == "standing":
            summary.stability_score = max(0, 100 - summary.avg_movement * 1500)
        else:
            # 坐姿稳定性要求略低
            summary.stability_score = max(0, 100 - summary.avg_movement * 1200)

        return summary
