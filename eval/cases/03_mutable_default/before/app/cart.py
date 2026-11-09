def cart_total(cart):
    return sum(i["price"] * i["qty"] for i in cart)
