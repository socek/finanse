def priced(name, price, category=None):
    """Jeden produkt transakcji cyklicznej."""
    return [{"name": name, "quantity": "1", "price": price, "category": category}]
