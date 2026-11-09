def apply_discount(price_cents: int, percent: int) -> int:
    return price_cents - price_cents * percent // 100


def average_order_value(total_revenue: float, order_count: int) -> float:
    if order_count == 0:
        return 0.0
    return total_revenue // order_count
