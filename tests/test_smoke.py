"""冒烟测试：确认所有核心模块可以正常导入"""
def test_import_pyside6():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCharts import QChart
    assert QApplication is not None


def test_import_data_models():
    from voicetrace.data.models import Script, Recording, Stumble, Analysis, Comparison
    assert Script is not None


def test_import_database():
    from voicetrace.data.database import Database
    assert Database is not None


def test_import_analyzer():
    from voicetrace.core.analyzer import Analyzer
    assert Analyzer is not None


def test_import_comparator():
    from voicetrace.core.comparator import Comparator
    assert Comparator is not None


def test_import_standards():
    from voicetrace.core.standards import get_standard, check_rate
    assert get_standard is not None
    assert check_rate is not None


def test_import_utils():
    from voicetrace.utils.audio import count_chinese_chars, count_english_words
    from voicetrace.utils.export import export_csv
    assert count_chinese_chars is not None
    assert count_english_words is not None
    assert export_csv is not None


def test_count_chinese():
    from voicetrace.utils.audio import count_chinese_chars
    assert count_chinese_chars("你好世界") == 4
    assert count_chinese_chars("hello") == 0
    assert count_chinese_chars("") == 0


def test_count_english():
    from voicetrace.utils.audio import count_english_words
    assert count_english_words("hello world") == 2
    assert count_english_words("") == 0


def test_standards():
    from voicetrace.core.standards import get_standard, check_rate
    std = get_standard("chinese", "news_broadcast")
    assert std["rate_min"] == 250
    assert std["rate_max"] == 300
    result = check_rate(265, "chinese", "news_broadcast")
    assert result["status"] == "pass"
