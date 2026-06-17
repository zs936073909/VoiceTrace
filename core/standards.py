STANDARDS = {
    ("chinese", "news_broadcast"): {"rate_min": 250, "rate_max": 300, "unit": "CPM"},
    ("english", "news_broadcast"): {"rate_min": 170, "rate_max": 190, "unit": "WPM"},
    ("chinese", "improv_commentary"): {"rate_min": 200, "rate_max": 280, "unit": "CPM"},
    ("english", "improv_commentary"): {"rate_min": 140, "rate_max": 180, "unit": "WPM"},
    ("chinese", "mock_host"): {"rate_min": 220, "rate_max": 300, "unit": "CPM"},
    ("english", "mock_host"): {"rate_min": 150, "rate_max": 190, "unit": "WPM"},
}

def get_standard(language: str, category: str) -> dict:
    return STANDARDS.get((language, category), {"rate_min": 0, "rate_max": 999, "unit": "CPM"})

def check_rate(speech_rate: float, language: str, category: str) -> dict:
    std = get_standard(language, category)
    rate_min = std["rate_min"]
    rate_max = std["rate_max"]
    unit = std["unit"]

    if rate_min <= speech_rate <= rate_max:
        return {"status": "pass", "message": f"符合标准区间 ({rate_min}-{rate_max} {unit})", "delta": 0}
    elif speech_rate > rate_max:
        delta = speech_rate - rate_max
        return {"status": "fail", "message": f"语速偏快{delta:.0f}{unit}", "delta": delta}
    else:
        delta = rate_min - speech_rate
        return {"status": "fail", "message": f"语速偏慢{delta:.0f}{unit}", "delta": -delta}
