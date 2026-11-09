def order_summaries(db, customer_ids: list[int]) -> list[dict]:
    out = []
    for cid in customer_ids:
        orders = db.execute(
            "SELECT id, total FROM orders WHERE customer_id = ?", (cid,)
        ).fetchall()
        out.append({"customer_id": cid, "orders": orders})
    return out
