from app.slugify import slugify


def test_basic():
    assert slugify("Hello, World!") == "hello-world"


def test_trims_dashes():
    assert slugify("--a--") == "a"


def test_empty():
    assert slugify("") == ""
