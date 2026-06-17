import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


class Comparator:
    def __init__(self):
        pass

    def compute_similarity(self, features_a: bytes, features_b: bytes) -> float:
        """Compute cosine similarity between two feature vectors.

        Features are stored as float64 bytes (see analyzer.py).
        """
        if not features_a or not features_b:
            return 0.0

        a = np.frombuffer(features_a, dtype=np.float64)
        b = np.frombuffer(features_b, dtype=np.float64)

        # Vectors must be same length for cosine similarity
        min_len = min(len(a), len(b))
        if min_len == 0:
            return 0.0

        a = a[:min_len].reshape(1, -1)
        b = b[:min_len].reshape(1, -1)

        return float(cosine_similarity(a, b)[0, 0])

    def generate_report(self, current_rate: float, baseline_rate: float,
                        current_pauses: int, baseline_pauses: int,
                        similarity_score: float) -> dict:
        rate_delta = current_rate - baseline_rate
        pause_delta = current_pauses - baseline_pauses

        improvements = []
        regressions = []

        if rate_delta > 0:
            improvements.append(f"语速提升 {rate_delta:.0f} 字/分钟")
        elif rate_delta < 0:
            regressions.append(f"语速下降 {abs(rate_delta):.0f} 字/分钟")

        if pause_delta < 0:
            improvements.append(f"卡顿减少 {abs(pause_delta)} 次")
        elif pause_delta > 0:
            regressions.append(f"卡顿增加 {pause_delta} 次")

        if similarity_score > 0.8:
            improvements.append(f"音色相似度高 ({similarity_score:.1%})")
        elif similarity_score < 0.5:
            regressions.append(f"音色相似度低 ({similarity_score:.1%})")

        return {
            "similarity_score": similarity_score,
            "current_rate": current_rate,
            "baseline_rate": baseline_rate,
            "current_pauses": current_pauses,
            "baseline_pauses": baseline_pauses,
            "rate_delta": rate_delta,
            "pause_delta": pause_delta,
            "improvements": improvements,
            "regressions": regressions,
        }
