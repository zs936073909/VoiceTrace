import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

# 支持直接运行 main.py：把项目根目录加入 Python 路径
if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    if project_root.name == "voicetrace" and str(project_root.parent) not in sys.path:
        sys.path.insert(0, str(project_root.parent))

from voicetrace.ui.main_window import MainWindow
from voicetrace.ui.styles import LIGHT_THEME


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("VoiceTrace")
    app.setStyleSheet(LIGHT_THEME)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
