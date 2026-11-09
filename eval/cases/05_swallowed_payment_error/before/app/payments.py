class PaymentError(Exception):
    pass


def charge(gateway, order_id: str, amount_cents: int) -> str:
    return gateway.charge(order_id=order_id, amount=amount_cents)
