"""验证模块导入（不实例化 MainWindow）"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
parent_dir = project_root.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

print("1. 导入核心模块...")
from voicetrace.core.memory_scheduler import MemoryScheduler, Rating, MemoryCard, State
from voicetrace.core.content_analyzer import ContentAnalyzer
from voicetrace.data.database import Database
from voicetrace.data.models import MemoryCard as DBMemoryCard, ReviewLog
print("   OK")

print("2. 导入UI模块...")
from voicetrace.ui.memory_assist_view import MemoryAssistView
print("   OK")

print("3. 导入主窗口模块...")
from voicetrace.ui.main_window import MainWindow
print("   OK")

print("4. 验证QTimer导入...")
from PySide6.QtCore import QTimer
print("   OK")

print("5. 验证 py_compile 主窗口...")
import py_compile
py_compile.compile(str(project_root / "ui" / "main_window.py"), doraise=True)
py_compile.compile(str(project_root / "ui" / "memory_assist_view.py"), doraise=True)
py_compile.compile(str(project_root / "core" / "memory_scheduler.py"), doraise=True)
py_compile.compile(str(project_root / "core" / "content_analyzer.py"), doraise=True)
py_compile.compile(str(project_root / "data" / "database.py"), doraise=True)
py_compile.compile(str(project_root / "data" / "models.py"), doraise=True)
print("   OK: 所有文件语法正确")

print("\n=== 模块导入与语法验证通过 ===")
