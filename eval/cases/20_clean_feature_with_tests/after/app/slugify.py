import re


def slugify(text: str) -> str:
    """Lowercase, replace runs of non-alphanumerics with '-', and trim dashes."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return slug.strip("-")
