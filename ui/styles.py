"""VoiceTrace QSS 样式表 — Editorial 风格 + Dark/Light 模式"""

LIGHT_THEME = """
QMainWindow, QWidget {
    background-color: #f8f6f1;
    color: #2b2b2b;
    font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif;
    font-size: 14px;
}

QTabWidget::pane {
    border: 1px solid #d4cfc4;
    background: #faf9f6;
    border-radius: 4px;
}

QTabBar::tab {
    background: #e8e4dc;
    color: #5a5a5a;
    padding: 10px 24px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background: #faf9f6;
    color: #1a1a1a;
    font-weight: 700;
    border-bottom: 3px solid #c0392b;
}

QTabBar::tab:hover:!selected {
    background: #ddd8cc;
}

QPushButton {
    background-color: #2c3e50;
    color: #f8f6f1;
    border: none;
    padding: 8px 20px;
    border-radius: 4px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #34495e;
}

QPushButton:pressed {
    background-color: #1a252f;
}

QPushButton:disabled {
    background-color: #bdc3c7;
    color: #ecf0f1;
}

QPushButton:disabled:hover {
    background-color: #bdc3c7;
}

QLineEdit, QTextEdit, QComboBox, QPlainTextEdit {
    background-color: #ffffff;
    border: 1px solid #d4cfc4;
    border-radius: 4px;
    padding: 6px 10px;
    color: #2b2b2b;
}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 2px solid #c0392b;
    padding: 5px 9px;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #d4cfc4;
    selection-background-color: #c0392b;
    selection-color: #ffffff;
}

QListWidget {
    background-color: #ffffff;
    border: 1px solid #d4cfc4;
    border-radius: 4px;
    padding: 4px;
}

QListWidget::item {
    padding: 8px 12px;
    border-radius: 3px;
}

QListWidget::item:selected {
    background-color: #c0392b;
    color: #ffffff;
}

QListWidget::item:hover:!selected {
    background-color: #f0ebe2;
}

QProgressBar {
    border: 1px solid #d4cfc4;
    border-radius: 4px;
    text-align: center;
    background-color: #ffffff;
    height: 24px;
}

QProgressBar::chunk {
    background-color: #c0392b;
    border-radius: 3px;
}

QLabel {
    color: #2b2b2b;
}

QChart {
    background-color: #faf9f6;
}

QChartView {
    background-color: #faf9f6;
    border: 1px solid #d4cfc4;
    border-radius: 4px;
}

QScrollBar:vertical {
    background: #e8e4dc;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #bdc3c7;
    min-height: 30px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #95a5a6;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QDialog {
    background-color: #f8f6f1;
}

QMessageBox {
    background-color: #f8f6f1;
}

QTextEdit[readOnly="true"] {
    background-color: #faf9f6;
    border: 1px solid #e0dbd0;
}
"""

DARK_THEME = """
QMainWindow, QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif;
    font-size: 14px;
}

QTabWidget::pane {
    border: 1px solid #2a2a4a;
    background: #16213e;
    border-radius: 4px;
}

QTabBar::tab {
    background: #0f1628;
    color: #8899aa;
    padding: 10px 24px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background: #16213e;
    color: #e94560;
    font-weight: 700;
    border-bottom: 3px solid #e94560;
}

QTabBar::tab:hover:!selected {
    background: #1a2540;
}

QPushButton {
    background-color: #e94560;
    color: #ffffff;
    border: none;
    padding: 8px 20px;
    border-radius: 4px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #ff5e7a;
}

QPushButton:pressed {
    background-color: #c81d3a;
}

QPushButton:disabled {
    background-color: #3a3a5a;
    color: #666688;
}

QLineEdit, QTextEdit, QComboBox, QPlainTextEdit {
    background-color: #0f1628;
    border: 1px solid #2a2a4a;
    border-radius: 4px;
    padding: 6px 10px;
    color: #e0e0e0;
}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 2px solid #e94560;
    padding: 5px 9px;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox QAbstractItemView {
    background-color: #0f1628;
    border: 1px solid #2a2a4a;
    selection-background-color: #e94560;
    selection-color: #ffffff;
}

QListWidget {
    background-color: #0f1628;
    border: 1px solid #2a2a4a;
    border-radius: 4px;
    padding: 4px;
}

QListWidget::item {
    padding: 8px 12px;
    border-radius: 3px;
    color: #e0e0e0;
}

QListWidget::item:selected {
    background-color: #e94560;
    color: #ffffff;
}

QListWidget::item:hover:!selected {
    background-color: #1a2540;
}

QProgressBar {
    border: 1px solid #2a2a4a;
    border-radius: 4px;
    text-align: center;
    background-color: #0f1628;
    color: #e0e0e0;
    height: 24px;
}

QProgressBar::chunk {
    background-color: #e94560;
    border-radius: 3px;
}

QLabel {
    color: #e0e0e0;
}

QChart {
    background-color: #16213e;
}

QChartView {
    background-color: #16213e;
    border: 1px solid #2a2a4a;
    border-radius: 4px;
}

QScrollBar:vertical {
    background: #0f1628;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #3a3a5a;
    min-height: 30px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #4a4a6a;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QDialog {
    background-color: #1a1a2e;
}

QMessageBox {
    background-color: #1a1a2e;
}

QTextEdit[readOnly="true"] {
    background-color: #16213e;
    border: 1px solid #2a2a4a;
    color: #e0e0e0;
}
"""
