"""面部分析核心模块：眼神追踪、表情分析、头部姿态检测

基于 MediaPipe Face Mesh（468 点）实现台风训练中的镜头感分析。
所有计算在本地 CPU 完成，无需联网。
"""
import math
import time
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


# MediaPipe Face Mesh 关键点索引
# 眼睛相关
LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
LEFT_IRIS = [468, 469, 470, 471, 472]
RIGHT_IRIS = [473, 474, 475, 476, 477]
# 嘴部
MOUTH_LEFT = 61
MOUTH_RIGHT = 291
MOUTH_TOP = 13
MOUTH_BOTTOM = 14
# 眉毛
LEFT_BROW = 105
RIGHT_BROW = 334
BROW_TOP_LEFT = 159
BROW_TOP_RIGHT = 386
# 头部姿态参考点
NOSE_TIP = 1
CHIN = 152
FOREHEAD = 10


@dataclass
class FrameAnalysis:
    """单帧分析结果"""
    timestamp: float  # 秒
    face_detected: bool = False
    # 眼神交流（0-1，1=直视镜头）
    eye_contact: float = 0.0
    # 眨眼（True=闭眼）
    is_blinking: bool = False
    # 表情（0-1，1=微笑）
    smile_score: float = 0.0
    # 紧张度（0-1，1=非常紧张，皱眉）
    tension_score: float = 0.0
    # 头部姿态（度）
    head_yaw: float = 0.0   # 左右转头
    head_pitch: float = 0.0  # 上下点头
    head_roll: float = 0.0   # 左右歪头


@dataclass
class SessionSummary:
    """训练会话汇总"""
    duration: float = 0.0  # 秒
    # 各维度评分（0-100）
    eye_contact_score: float = 0.0
    expression_score: float = 0.0
    head_pose_score: float = 0.0
    # 详细统计
    eye_contact_ratio: float = 0.0  # 看镜头时长占比
    blink_count: int = 0
    blink_rate: float = 0.0  # 次/分钟
    avg_smile: float = 0.0
    avg_tension: float = 0.0
    head_movement: float = 0.0  # 头部总运动量
    # 时间序列数据（用于回放标注）
    timeline: List[FrameAnalysis] = field(default_factory=list)
    # 眼神偏离时刻（秒）
    gaze_away_moments: List[float] = field(default_factory=list)


class PostureAnalyzer:
    """面部分析器（镜头感训练）"""

    def __init__(self):
        if not MEDIAPIPE_AVAILABLE:
            raise ImportError(
                "MediaPipe 未安装。请运行: pip install mediapipe opencv-python"
            )
        self._face_mesh = None
        self._blink_buffer = deque(maxlen=5)  # 用于眨眼检测
        self._last_blink_time = 0
        self._blink_count = 0

    def initialize(self):
        """初始化 MediaPipe Face Mesh"""
        if self._face_mesh is None:
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,  # 启用虹膜追踪
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )

    def close(self):
        """释放资源"""
        if self._face_mesh:
            self._face_mesh.close()
            self._face_mesh = None

    def analyze_frame(self, frame_bgr: np.ndarray, timestamp: float) -> FrameAnalysis:
        """分析单帧图像

        Args:
            frame_bgr: OpenCV BGR 格式图像
            timestamp: 当前时间戳（秒）

        Returns:
            FrameAnalysis 分析结果
        """
        self.initialize()
        result = FrameAnalysis(timestamp=timestamp)

        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_result = self._face_mesh.process(rgb)

        if not mp_result.multi_face_landmarks:
            return result

        result.face_detected = True
        lm = mp_result.multi_face_landmarks[0].landmark

        # 1. 眼神交流检测（基于虹膜位置）
        result.eye_contact = self._compute_eye_contact(lm, w, h)

        # 2. 眨眼检测（基于眼睛纵横比 EAR）
        ear = self._compute_eye_aspect_ratio(lm, w, h)
        self._blink_buffer.append(ear)
        result.is_blinking = ear < 0.20
        if result.is_blinking and timestamp - self._last_blink_time > 0.15:
            self._blink_count += 1
            self._last_blink_time = timestamp

        # 3. 微笑度（嘴角上扬程度）
        result.smile_score = self._compute_smile(lm, w, h)

        # 4. 紧张度（皱眉程度）
        result.tension_score = self._compute_tension(lm, w, h)

        # 5. 头部姿态（简化估计）
        yaw, pitch, roll = self._estimate_head_pose(lm, w, h)
        result.head_yaw = yaw
        result.head_pitch = pitch
        result.head_roll = roll

        return result

    def _compute_eye_contact(self, lm, w: int, h: int) -> float:
        """计算眼神交流得分（0-1）

        原理：虹膜中心相对眼睛中心的偏移量越小，越接近直视镜头。
        """
        try:
            # 左眼虹膜中心
            left_iris_x = sum(lm[i].x for i in LEFT_IRIS) / len(LEFT_IRIS) * w
            left_iris_y = sum(lm[i].y for i in LEFT_IRIS) / len(LEFT_IRIS) * h
            # 左眼眼眶中心
            left_eye_x = sum(lm[i].x for i in LEFT_EYE) / len(LEFT_EYE) * w
            left_eye_y = sum(lm[i].y for i in LEFT_EYE) / len(LEFT_EYE) * h

            # 右眼虹膜中心
            right_iris_x = sum(lm[i].x for i in RIGHT_IRIS) / len(RIGHT_IRIS) * w
            right_iris_y = sum(lm[i].y for i in RIGHT_IRIS) / len(RIGHT_IRIS) * h
            # 右眼眼眶中心
            right_eye_x = sum(lm[i].x for i in RIGHT_EYE) / len(RIGHT_EYE) * w
            right_eye_y = sum(lm[i].y for i in RIGHT_EYE) / len(RIGHT_EYE) * h

            # 眼睛宽度（归一化基准）
            eye_width = abs(lm[RIGHT_EYE[0]].x - lm[LEFT_EYE[3]].x) * w
            if eye_width < 1:
                return 0.5

            # 虹膜偏移（归一化到眼睛宽度）
            left_offset = math.hypot(left_iris_x - left_eye_x, left_iris_y - left_eye_y) / eye_width
            right_offset = math.hypot(right_iris_x - right_eye_x, right_iris_y - right_eye_y) / eye_width
            avg_offset = (left_offset + right_offset) / 2

            # 偏移 < 0.1 视为直视，> 0.3 视为完全偏离
            score = max(0.0, min(1.0, 1.0 - (avg_offset - 0.05) / 0.25))
            return score
        except Exception:
            return 0.5

    def _compute_eye_aspect_ratio(self, lm, w: int, h: int) -> float:
        """计算眼睛纵横比 EAR（用于眨眼检测）

        EAR = 眼睛垂直距离 / 眼睛水平距离
        正常睁眼: 0.25-0.35，闭眼: < 0.20
        """
        try:
            # 左眼
            v1 = math.hypot(
                (lm[374].x - lm[386].x) * w,
                (lm[374].y - lm[386].y) * h
            )
            v2 = math.hypot(
                (lm[380].x - lm[263].x) * w,
                (lm[380].y - lm[263].y) * h
            )
            horiz = math.hypot(
                (lm[33].x - lm[133].x) * w,
                (lm[33].y - lm[133].y) * h
            )
            if horiz < 1:
                return 0.3
            ear_left = (v1 + v2) / (2 * horiz)

            # 右眼
            v1 = math.hypot(
                (lm[159].x - lm[145].x) * w,
                (lm[159].y - lm[145].y) * h
            )
            v2 = math.hypot(
                (lm[153].x - lm[144].x) * w,
                (lm[153].y - lm[144].y) * h
            )
            horiz = math.hypot(
                (lm[33].x - lm[133].x) * w,
                (lm[33].y - lm[133].y) * h
            )
            if horiz < 1:
                return 0.3
            ear_right = (v1 + v2) / (2 * horiz)

            return (ear_left + ear_right) / 2
        except Exception:
            return 0.3

    def _compute_smile(self, lm, w: int, h: int) -> float:
        """计算微笑度（0-1）

        原理：嘴角宽度 / 嘴部到眼睛距离，比值越大越微笑。
        """
        try:
            mouth_width = math.hypot(
                (lm[MOUTH_RIGHT].x - lm[MOUTH_LEFT].x) * w,
                (lm[MOUTH_RIGHT].y - lm[MOUTH_LEFT].y) * h
            )
            # 嘴到眼睛距离（面部尺度参考）
            eye_to_mouth = math.hypot(
                (lm[168].x - lm[MOUTH_TOP].x) * w,
                (lm[168].y - lm[MOUTH_TOP].y) * h
            )
            if eye_to_mouth < 1:
                return 0.0
            ratio = mouth_width / eye_to_mouth
            # ratio 约 0.8-1.0 为正常，> 1.1 为微笑
            score = max(0.0, min(1.0, (ratio - 0.85) / 0.35))
            return score
        except Exception:
            return 0.0

    def _compute_tension(self, lm, w: int, h: int) -> float:
        """计算紧张度（0-1，皱眉程度）

        原理：眉毛到眼睛距离越近，越紧张/皱眉。
        """
        try:
            # 左眉到左眼距离
            left_brow_eye = math.hypot(
                (lm[LEFT_BROW].x - lm[159].x) * w,
                (lm[LEFT_BROW].y - lm[159].y) * h
            )
            # 右眉到右眼距离
            right_brow_eye = math.hypot(
                (lm[RIGHT_BROW].x - lm[386].x) * w,
                (lm[RIGHT_BROW].y - lm[386].y) * h
            )
            avg_dist = (left_brow_eye + right_brow_eye) / 2

            # 面部尺度参考（眼到嘴距离）
            face_scale = math.hypot(
                (lm[168].x - lm[MOUTH_TOP].x) * w,
                (lm[168].y - lm[MOUTH_TOP].y) * h
            )
            if face_scale < 1:
                return 0.0
            ratio = avg_dist / face_scale
            # ratio 约 0.6-0.8 为正常，< 0.5 为皱眉
            score = max(0.0, min(1.0, (0.7 - ratio) / 0.3))
            return score
        except Exception:
            return 0.0

    def _estimate_head_pose(self, lm, w: int, h: int) -> Tuple[float, float, float]:
        """简化头部姿态估计（度）

        基于 2D 关键点近似估计 yaw/pitch/roll。
        """
        try:
            # Roll: 基于双眼连线的角度
            left_eye = np.array([lm[33].x * w, lm[33].y * h])
            right_eye = np.array([lm[263].x * w, lm[263].y * h])
            roll = math.degrees(math.atan2(
                right_eye[1] - left_eye[1],
                right_eye[0] - left_eye[0]
            ))

            # Yaw: 基于鼻尖到两眼中心的左右偏移
            nose = np.array([lm[NOSE_TIP].x * w, lm[NOSE_TIP].y * h])
            eye_center = (left_eye + right_eye) / 2
            eye_dist = np.linalg.norm(right_eye - left_eye)
            if eye_dist > 1:
                yaw_offset = (nose[0] - eye_center[0]) / eye_dist
                yaw = math.degrees(math.asin(max(-1, min(1, yaw_offset * 2))))
            else:
                yaw = 0.0

            # Pitch: 基于鼻尖到下巴/额头比例
            forehead = np.array([lm[FOREHEAD].x * w, lm[FOREHEAD].y * h])
            chin = np.array([lm[CHIN].x * w, lm[CHIN].y * h])
            face_height = np.linalg.norm(chin - forehead)
            if face_height > 1:
                nose_ratio = (nose[1] - forehead[1]) / face_height
                # 正常约 0.5，抬头 < 0.45，低头 > 0.55
                pitch = (nose_ratio - 0.5) * 180
            else:
                pitch = 0.0

            return yaw, pitch, roll
        except Exception:
            return 0.0, 0.0, 0.0

    def summarize_session(self, timeline: List[FrameAnalysis]) -> SessionSummary:
        """汇总训练会话结果

        Args:
            timeline: 所有帧的分析结果

        Returns:
            SessionSummary 汇总
        """
        if not timeline:
            return SessionSummary()

        summary = SessionSummary(timeline=timeline)
        valid_frames = [f for f in timeline if f.face_detected]

        if not valid_frames:
            return summary

        summary.duration = timeline[-1].timestamp - timeline[0].timestamp if len(timeline) > 1 else 0

        # 眼神交流
        eye_contacts = [f.eye_contact for f in valid_frames]
        eye_contact_ratio = sum(1 for e in eye_contacts if e > 0.6) / len(eye_contacts)
        summary.eye_contact_ratio = eye_contact_ratio
        summary.eye_contact_score = min(100, eye_contact_ratio * 130)

        # 记录眼神偏离时刻
        for f in valid_frames:
            if f.eye_contact < 0.4:
                summary.gaze_away_moments.append(f.timestamp)

        # 眨眼
        summary.blink_count = self._blink_count
        if summary.duration > 0:
            summary.blink_rate = (summary.blink_count / summary.duration) * 60

        # 表情
        smiles = [f.smile_score for f in valid_frames]
        summary.avg_smile = sum(smiles) / len(smiles)
        summary.expression_score = min(100, summary.avg_smile * 120)

        # 紧张度（反向：紧张越低分越高）
        tensions = [f.tension_score for f in valid_frames]
        avg_tension = sum(tensions) / len(tensions)
        summary.avg_tension = avg_tension
        summary.expression_score = max(0, summary.expression_score - avg_tension * 30)

        # 头部姿态
        yaws = [abs(f.head_yaw) for f in valid_frames]
        pitches = [abs(f.head_pitch) for f in valid_frames]
        rolls = [abs(f.head_roll) for f in valid_frames]
        avg_yaw = sum(yaws) / len(yaws)
        avg_pitch = sum(pitches) / len(pitches)
        avg_roll = sum(rolls) / len(rolls)
        # 头部运动越小越好（< 10 度为佳）
        summary.head_movement = (avg_yaw + avg_pitch + avg_roll) / 3
        summary.head_pose_score = max(0, 100 - summary.head_movement * 4)

        return summary


def is_mediapipe_available() -> bool:
    """检查 MediaPipe 是否可用"""
    return MEDIAPIPE_AVAILABLE
