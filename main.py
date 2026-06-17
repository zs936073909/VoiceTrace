import sys
from PySide6.QtWidgets import QApplication

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
