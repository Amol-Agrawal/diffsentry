class Order:
    def __init__(self) -> None:
        self.lines: list[tuple[str, int, int]] = []

    def total_cents(self) -> int:
        return sum(qty * price for _, qty, price in self.lines)

    def add_line(self, sku: str, qty: int, price_cents: int) -> None:
        self.lines.append((sku, qty, price_cents))
