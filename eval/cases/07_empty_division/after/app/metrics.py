def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(0.95 * (len(ordered) - 1))
    return ordered[idx]


def mean_latency(samples: list[float]) -> float:
    return sum(samples) / len(samples)
