def format_price(cents: int) -> str:
    return f"${cents / 100:.2f}"


def format_quantity(n: int) -> str:
    return f"{n} items"
