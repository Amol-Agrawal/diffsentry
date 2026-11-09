class Order:
    def __init__(self) -> None:
        self.lines: list[tuple[str, int, int]] = []

    def total_cents(self) -> int:
        return sum(qty * price for _, qty, price in self.lines)
