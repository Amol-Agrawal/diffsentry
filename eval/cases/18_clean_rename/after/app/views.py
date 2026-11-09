from app.formatting import format_price, format_quantity


def cart_line(cents: int, n: int) -> str:
    return f"{format_quantity(n)} - {format_price(cents)}"
