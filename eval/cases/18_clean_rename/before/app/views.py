from app.formatting import fmt_price, fmt_qty


def cart_line(cents: int, n: int) -> str:
    return f"{fmt_qty(n)} - {fmt_price(cents)}"
