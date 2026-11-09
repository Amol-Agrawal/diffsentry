def apply_discount(price_cents: int, percent: int) -> int:
    return price_cents - price_cents * percent // 100
