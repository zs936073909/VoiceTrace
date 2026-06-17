"""VoiceTrace - 语音档案智能追踪系统"""
from pathlib import Path

# 统一的数据目录定义，避免在多个文件中重复
DATA_DIR = Path.home() / ".voicetrace"
DATA_DIR.mkdir(parents=True, exist_ok=True)

RECORDINGS_DIR = DATA_DIR / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "broadcast.db"
