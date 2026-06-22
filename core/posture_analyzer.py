"""面部分析核心模块：眼神追踪、表情分析、头部姿态检测

基于 MediaPipe Face Landmarker（0.10.x Tasks API）实现台风训练中的镜头感分析。
启用了 face blendshapes（52 维表情系数）和 facial transformation matrixes（4×4 头部姿态矩阵），
相比纯几何计算，表情和头部姿态识别更稳定、更准确。
所有计算在本地 CPU 完成，无需联网。
"""
import math
import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any

import numpy as np

try:
    import mediapipe as mp
    import cv2
    from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions, RunningMode
    from mediapipe.tasks.python.core.base_options import BaseOptions
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    mp = None
    cv2 = None

logger = logging.getLogger(__name__)

# 关键点可见性阈值
_VISIBILITY_THRESHOLD = 0.5

# 默认模型路径
DEFAULT_FACE_MODEL = Path(__file__).parent.parent / "models" / "face_landmarker.task"


@dataclass
class FrameAnalysis:
    """单帧分析结果"""
    timestamp: float  # 秒
    face_detected: bool = False
    # 眼神交流（0-1，1=直视镜头）
    eye_contact: float = 0.0
    # 眨眼（True=闭眼）
    is_blinking: bool = False
    # 表情（0-1，1=明显微笑）
    smile_score: float = 0.0
    # 紧张度（0-1，1=非常紧张，皱眉/抿嘴）
    tension_score: float = 0.0
    # 头部姿态（度）
    head_yaw: float = 0.0   # 左右转头
    head_pitch: float = 0.0  # 上下点头
    head_roll: float = 0.0   # 左右歪头
    # 原始关键点（用于可视化）
    landmarks: Optional[List[Any]] = None
    # 调试信息
    debug_info: Dict[str, Any] = field(default_factory=dict)


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

    def __init__(self, model_path: Optional[str] = None):
        if not MEDIAPIPE_AVAILABLE:
            raise ImportError(
                "MediaPipe 未安装。请运行: pip install mediapipe opencv-python"
            )
        self._model_path = Path(model_path) if model_path else DEFAULT_FACE_MODEL
        self._landmarker: Optional[FaceLandmarker] = None
        self._blink_buffer = deque(maxlen=5)
        self._last_blink_time = 0.0
        self._blink_count = 0
        self._pose_history = deque(maxlen=5)

        # 个人校准基准（可选）
        self._calibration = None

    def initialize(self):
        """初始化 MediaPipe Face Landmarker（启用 blendshapes + transformation matrix）"""
        if self._landmarker is not None:
            return
        if not self._model_path.exists():
            raise FileNotFoundError(
                f"Face Landmarker 模型文件不存在: {self._model_path}\n"
                f"请运行 scripts/download_models.py 自动下载，或从官网手动下载。"
            )
        try:
            options = FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(self._model_path)),
                running_mode=RunningMode.VIDEO,
                num_faces=1,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
            )
            self._landmarker = FaceLandmarker.create_from_options(options)
            logger.info("Face Landmarker 初始化成功（blendshapes + matrix 已启用）")
        except Exception as exc:
            logger.error(f"初始化 Face Landmarker 失败: {exc}")
            raise

    def close(self):
        """释放资源"""
        if self._landmarker:
            try:
                self._landmarker.close()
            except Exception as exc:
                logger.warning(f"关闭 Face Landmarker 时出错: {exc}")
            self._landmarker = None
        self.reset_state()

    def reset_state(self):
        """重置会话状态"""
        self._blink_buffer.clear()
        self._last_blink_time = 0.0
        self._blink_count = 0
        self._pose_history.clear()

    def calibrate_neutral(self, frame_bgr: np.ndarray) -> bool:
        """采集当前表情作为中性基准，用于个性化评分"""
        result = self.analyze_frame(frame_bgr, 0.0)
        if not result.face_detected:
            return False
        self._calibration = {
            "smile": result.smile_score,
            "tension": result.tension_score,
            "eye_contact": result.eye_contact,
        }
        return True

    def _is_valid_frame(self, frame_bgr) -> bool:
        if frame_bgr is None:
            return False
        if not isinstance(frame_bgr, np.ndarray):
            return False
        if frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            return False
        if frame_bgr.size == 0:
            return False
        return True

    def analyze_frame(self, frame_bgr: np.ndarray, timestamp: float) -> FrameAnalysis:
        """分析单帧图像"""
        result = FrameAnalysis(timestamp=timestamp)

        if not self._is_valid_frame(frame_bgr):
            result.debug_info["error"] = "无效帧"
            return result

        try:
            self.initialize()
        except Exception as exc:
            result.debug_info["error"] = f"初始化失败: {exc}"
            return result

        try:
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            mp_result = self._landmarker.detect_for_video(mp_image, int(timestamp * 1000))
        except Exception as exc:
            logger.warning(f"面部处理失败: {exc}")
            result.debug_info["error"] = f"处理失败: {exc}"
            return result

        if not mp_result or not mp_result.face_landmarks:
            result.debug_info["error"] = "未检测到面部"
            return result

        landmarks = mp_result.face_landmarks[0]
        if len(landmarks) < 478:
            result.debug_info["error"] = f"关键点数量不足: {len(landmarks)}"
            return result

        result.face_detected = True
        lm = landmarks
        result.landmarks = landmarks

        # 解析 blendshapes
        blendshapes = {}
        if mp_result.face_blendshapes and mp_result.face_blendshapes[0]:
            for cat in mp_result.face_blendshapes[0].categories:
                blendshapes[cat.category_name] = cat.score

        # 解析 transformation matrix（4x4）
        transform_matrix = None
        if mp_result.facial_transformation_matrixes and len(mp_result.facial_transformation_matrixes) > 0:
            transform_matrix = np.array(mp_result.facial_transformation_matrixes[0]).reshape(4, 4)

        # 调试信息
        result.debug_info = {
            "landmark_count": len(landmarks),
            "blendshape_count": len(blendshapes),
            "has_matrix": transform_matrix is not None,
            "blendshapes": {k: round(v, 3) for k, v in list(blendshapes.items())[:10]},
        }

        # 1. 头部姿态（基于 transformation matrix）
        try:
            if transform_matrix is not None:
                yaw, pitch, roll = self._extract_euler_from_matrix(transform_matrix)
                self._pose_history.append((yaw, pitch, roll))
                result.head_yaw = float(np.median([p[0] for p in self._pose_history]))
                result.head_pitch = float(np.median([p[1] for p in self._pose_history]))
                result.head_roll = float(np.median([p[2] for p in self._pose_history]))
            else:
                result.head_yaw, result.head_pitch, result.head_roll = self._estimate_head_pose(lm)
        except Exception as exc:
            logger.debug(f"头部姿态估计失败: {exc}")

        # 2. 眼神交流（基于 blendshapes + 头部姿态修正）
        try:
            result.eye_contact = self._compute_eye_contact(blendshapes, lm, result.head_yaw, result.head_pitch)
        except Exception as exc:
            logger.debug(f"眼神交流计算失败: {exc}")
            result.eye_contact = 0.0

        # 3. 眨眼检测
        try:
            blink_left = blendshapes.get("eyeBlinkLeft", 0.0)
            blink_right = blendshapes.get("eyeBlinkRight", 0.0)
            ear = self._compute_eye_aspect_ratio(lm)
            # 混合判断：blendshape + 几何 EAR
            blink_score = max((blink_left + blink_right) / 2.0, 1.0 - ear / 0.25)
            self._blink_buffer.append(blink_score)
            result.is_blinking = self._detect_blink()
            if result.is_blinking and timestamp - self._last_blink_time > 0.15:
                self._blink_count += 1
                self._last_blink_time = timestamp
        except Exception as exc:
            logger.debug(f"眨眼检测失败: {exc}")

        # 4. 微笑度
        try:
            result.smile_score = self._compute_smile(blendshapes, lm)
        except Exception as exc:
            logger.debug(f"微笑度计算失败: {exc}")

        # 5. 紧张度
        try:
            result.tension_score = self._compute_tension(blendshapes, lm)
        except Exception as exc:
            logger.debug(f"紧张度计算失败: {exc}")

        # 应用校准
        if self._calibration:
            result.smile_score = max(0.0, result.smile_score - self._calibration["smile"] * 0.5)
            result.tension_score = max(0.0, result.tension_score - self._calibration["tension"] * 0.5)

        return result

    @staticmethod
    def _extract_euler_from_matrix(matrix: np.ndarray) -> tuple:
        """从 4x4 变换矩阵提取 yaw/pitch/roll（度）"""
        # matrix: canonical face model -> camera space
        # 取旋转部分
        R = matrix[:3, :3]
        # MediaPipe 的矩阵可能包含缩放，先归一化
        R = R / np.linalg.norm(R, axis=0, keepdims=True)

        sy = math.sqrt(R[0, 0] * R[0, 0] + R[1, 0] * R[1, 0])
        singular = sy < 1e-6

        if not singular:
            x = math.atan2(R[2, 1], R[2, 2])
            y = math.atan2(-R[2, 0], sy)
            z = math.atan2(R[1, 0], R[0, 0])
        else:
            x = math.atan2(-R[1, 2], R[1, 1])
            y = math.atan2(-R[2, 0], sy)
            z = 0

        return math.degrees(y), math.degrees(x), math.degrees(z)

    def _compute_eye_contact(
        self,
        blendshapes: Dict[str, float],
        lm,
        head_yaw: float,
        head_pitch: float
    ) -> float:
        """计算眼神交流得分

        综合眼睛看向中心的 blendshape 和虹膜位置，并用头部姿态修正：
        如果头部正对镜头，眼睛也看中心 → 直视镜头。
        """
        # blendshape 眼睛看向内侧/上方/下方
        look_in = (blendshapes.get("eyeLookInLeft", 0.0) + blendshapes.get("eyeLookInRight", 0.0)) / 2.0
        look_out = (blendshapes.get("eyeLookOutLeft", 0.0) + blendshapes.get("eyeLookOutRight", 0.0)) / 2.0
        look_up = (blendshapes.get("eyeLookUpLeft", 0.0) + blendshapes.get("eyeLookUpRight", 0.0)) / 2.0
        look_down = (blendshapes.get("eyeLookDownLeft", 0.0) + blendshapes.get("eyeLookDownRight", 0.0)) / 2.0

        # 眼睛看向内侧越多，越可能是直视镜头
        horizontal_score = max(0.0, 1.0 - look_out * 2.0)
        vertical_score = max(0.0, 1.0 - (look_up + look_down) * 1.5)
        gaze_score = (horizontal_score + vertical_score) / 2.0

        # 用虹膜位置辅助
        iris_score = self._compute_iris_center_score(lm)

        # 头部姿态修正：正对镜头时眼神交流更容易得高分
        head_penalty = min(1.0, (abs(head_yaw) + abs(head_pitch)) / 60.0)

        score = (gaze_score * 0.4 + iris_score * 0.4) * (1.0 - head_penalty * 0.5)
        return max(0.0, min(1.0, score))

    def _compute_iris_center_score(self, lm) -> float:
        """基于虹膜位置判断是否直视镜头"""
        LEFT_IRIS = [468, 469, 470, 471, 472]
        RIGHT_IRIS = [473, 474, 475, 476, 477]
        LEFT_EYE = [362, 385, 387, 263, 373, 380]
        RIGHT_EYE = [33, 160, 158, 133, 153, 144]

        if not all(getattr(lm[i], "visibility", 1.0) >= _VISIBILITY_THRESHOLD for i in LEFT_IRIS + RIGHT_IRIS + LEFT_EYE + RIGHT_EYE):
            return 0.5

        left_iris_x = sum(lm[i].x for i in LEFT_IRIS) / len(LEFT_IRIS)
        left_eye_x = sum(lm[i].x for i in LEFT_EYE) / len(LEFT_EYE)
        right_iris_x = sum(lm[i].x for i in RIGHT_IRIS) / len(RIGHT_IRIS)
        right_eye_x = sum(lm[i].x for i in RIGHT_EYE) / len(RIGHT_EYE)

        left_iris_y = sum(lm[i].y for i in LEFT_IRIS) / len(LEFT_IRIS)
        left_eye_y = sum(lm[i].y for i in LEFT_EYE) / len(LEFT_EYE)
        right_iris_y = sum(lm[i].y for i in RIGHT_IRIS) / len(RIGHT_IRIS)
        right_eye_y = sum(lm[i].y for i in RIGHT_EYE) / len(RIGHT_EYE)

        x_offset = abs((left_iris_x - left_eye_x) + (right_iris_x - right_eye_x)) / 2.0
        y_offset = abs((left_iris_y - left_eye_y) + (right_iris_y - right_eye_y)) / 2.0
        offset = math.hypot(x_offset, y_offset)

        # 偏移 < 0.03 视为直视
        score = max(0.0, min(1.0, 1.0 - offset / 0.08))
        return score

    def _compute_eye_aspect_ratio(self, lm) -> float:
        """计算眼睛纵横比 EAR"""
        # 左眼竖直距离 374-386, 380-263; 水平 33-133
        def eye_ear(v_top, v_bottom, h_left, h_right):
            v = math.hypot(lm[v_top].x - lm[v_bottom].x, lm[v_top].y - lm[v_bottom].y)
            h = math.hypot(lm[h_left].x - lm[h_right].x, lm[h_left].y - lm[h_right].y)
            return (v + v) / (2.0 * h) if h > 0 else 0.3

        left_ear = eye_ear(374, 386, 33, 133)
        right_ear = eye_ear(159, 145, 33, 133)
        return (left_ear + right_ear) / 2.0

    def _detect_blink(self) -> bool:
        """基于缓冲区的眨眼检测"""
        if len(self._blink_buffer) < 3:
            return False
        recent = list(self._blink_buffer)[-3:]
        return sum(1 for s in recent if s > 0.55) >= 2

    def _compute_smile(self, blendshapes: Dict[str, float], lm) -> float:
        """微笑度：基于 mouthSmile blendshapes + 嘴角上扬几何"""
        smile_left = blendshapes.get("mouthSmileLeft", 0.0)
        smile_right = blendshapes.get("mouthSmileRight", 0.0)
        smile_blend = (smile_left + smile_right) / 2.0

        # 几何辅助：嘴宽 / 脸长
        mouth_width = math.hypot(lm[291].x - lm[61].x, lm[291].y - lm[61].y)
        face_height = math.hypot(lm[152].y - lm[10].y, lm[152].x - lm[10].x)
        mouth_ratio = mouth_width / face_height if face_height > 0 else 0.0

        # 综合 blendshape（主导）和几何
        score = smile_blend * 0.7 + max(0.0, (mouth_ratio - 0.5) / 0.5) * 0.3
        return max(0.0, min(1.0, score))

    def _compute_tension(self, blendshapes: Dict[str, float], lm) -> float:
        """紧张度：基于皱眉、抿嘴、瞪眼 blendshapes"""
        brow_down = (blendshapes.get("browDownLeft", 0.0) + blendshapes.get("browDownRight", 0.0)) / 2.0
        brow_inner_up = blendshapes.get("browInnerUp", 0.0)
        mouth_press = (blendshapes.get("mouthPressLeft", 0.0) + blendshapes.get("mouthPressRight", 0.0)) / 2.0
        mouth_pucker = blendshapes.get("mouthPucker", 0.0)
        eye_wide = (blendshapes.get("eyeWideLeft", 0.0) + blendshapes.get("eyeWideRight", 0.0)) / 2.0

        # 皱眉 + 眉毛内抬（惊讶/紧张）+ 抿嘴 + 嘟嘴 + 瞪眼
        tension = (
            brow_down * 0.25 +
            brow_inner_up * 0.15 +
            mouth_press * 0.25 +
            mouth_pucker * 0.15 +
            eye_wide * 0.20
        )
        return max(0.0, min(1.0, tension))

    def _estimate_head_pose(self, lm) -> tuple:
        """备用头部姿态估计（当 matrix 不可用时）"""
        left_eye = np.array([lm[33].x, lm[33].y])
        right_eye = np.array([lm[263].x, lm[263].y])
        roll = math.degrees(math.atan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0]))

        nose = np.array([lm[1].x, lm[1].y])
        eye_center = (left_eye + right_eye) / 2.0
        eye_dist = np.linalg.norm(right_eye - left_eye)
        yaw = 0.0
        if eye_dist > 0:
            yaw = math.degrees(math.asin(max(-1, min(1, (nose[0] - eye_center[0]) / eye_dist * 2))))

        forehead = np.array([lm[10].x, lm[10].y])
        chin = np.array([lm[152].x, lm[152].y])
        face_height = np.linalg.norm(chin - forehead)
        pitch = 0.0
        if face_height > 0:
            pitch = ((nose[1] - forehead[1]) / face_height - 0.5) * 180

        return yaw, pitch, roll

    def summarize_session(self, timeline: List[FrameAnalysis]) -> SessionSummary:
        """汇总训练会话结果"""
        if not timeline:
            return SessionSummary()

        summary = SessionSummary(timeline=timeline)
        valid_frames = [f for f in timeline if f.face_detected]

        if not valid_frames:
            return summary

        summary.duration = timeline[-1].timestamp - timeline[0].timestamp if len(timeline) > 1 else 0

        # 眼神交流
        eye_contacts = [f.eye_contact for f in valid_frames]
        eye_contact_ratio = sum(1 for e in eye_contacts if e > 0.5) / len(eye_contacts)
        summary.eye_contact_ratio = eye_contact_ratio
        summary.eye_contact_score = min(100, eye_contact_ratio * 130)

        for f in valid_frames:
            if f.eye_contact < 0.35:
                summary.gaze_away_moments.append(f.timestamp)

        # 眨眼
        summary.blink_count = self._blink_count
        if summary.duration > 0:
            summary.blink_rate = (summary.blink_count / summary.duration) * 60

        # 表情
        smiles = [f.smile_score for f in valid_frames]
        summary.avg_smile = sum(smiles) / len(smiles)
        tensions = [f.tension_score for f in valid_frames]
        summary.avg_tension = sum(tensions) / len(tensions)
        summary.expression_score = max(0, min(100, summary.avg_smile * 110 - summary.avg_tension * 40 + 30))

        # 头部姿态
        yaws = [abs(f.head_yaw) for f in valid_frames]
        pitches = [abs(f.head_pitch) for f in valid_frames]
        rolls = [abs(f.head_roll) for f in valid_frames]
        avg_movement = (sum(yaws) + sum(pitches) + sum(rolls)) / (3 * len(valid_frames))
        summary.head_movement = avg_movement
        summary.head_pose_score = max(0, 100 - avg_movement * 3)

        return summary


def is_mediapipe_available() -> bool:
    """检查 MediaPipe 是否可用"""
    return MEDIAPIPE_AVAILABLE
