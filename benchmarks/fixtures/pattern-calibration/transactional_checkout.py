"""State and event publication are non-atomic, making outbox migration valuable but costly."""


def checkout(order: dict, database, event_bus) -> None:
    database.begin()
    database.save_order(order)
    database.commit()
    event_bus.publish(
        "order.checked_out",
        {"order_id": order["id"], "total": order["total"]},
    )
