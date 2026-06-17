import re


def count_chinese_chars(text: str) -> int:
    """Count Chinese characters excluding punctuation."""
    if not text:
        return 0
    # Match CJK Unified Ideographs (excluding punctuation)
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def count_english_words(text: str) -> int:
    """Count English words, ignoring punctuation and numbers."""
    if not text:
        return 0
    # Match sequences of ASCII letters (including apostrophes in contractions)
    words = re.findall(r"[a-zA-Z]+(?:'[a-zA-Z]+)?", text)
    return len(words)


def count_mixed(text: str) -> int:
    """Count total content units: Chinese chars + English words."""
    return count_chinese_chars(text) + count_english_words(text)
