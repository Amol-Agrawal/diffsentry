def in_stock(item: dict) -> bool:
    return item["qty"] > 0


def remove_out_of_stock(items: list[dict]) -> list[dict]:
    for item in items:
        if item["qty"] == 0:
            items.remove(item)
    return items
