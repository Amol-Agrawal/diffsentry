def paginate(items, page, per_page):
    """Return the items for a 1-indexed page."""
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end]


def total_pages(count, per_page):
    return (count + per_page - 1) // per_page
