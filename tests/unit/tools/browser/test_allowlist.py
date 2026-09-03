from buildagent.tools.browser.allowlist import is_allowed, parse_allowlist


def test_parse_allowlist_strips_and_drops_empty() -> None:
    assert parse_allowlist("") == ()
    assert parse_allowlist(" , ") == ()
    assert parse_allowlist("https://a.com, https://b.com/foo,") == (
        "https://a.com",
        "https://b.com/foo",
    )


def test_is_allowed_empty_allowlist_allows_all() -> None:
    assert is_allowed("https://anything.example", ())


def test_is_allowed_matches_prefix() -> None:
    allowlist = ("https://a.com/", "https://b.com/foo")
    assert is_allowed("https://a.com/x", allowlist)
    assert is_allowed("https://b.com/foo/bar", allowlist)
    assert not is_allowed("https://c.com/", allowlist)
    assert not is_allowed("https://a.com", allowlist)
