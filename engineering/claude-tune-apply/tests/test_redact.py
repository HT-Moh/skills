import secrets

import redact


def test_json_pair_key_redacted():
    out = redact.redact('"X_TOKEN": "abc"')
    assert "<redacted>" in out and "abc" not in out


def test_json_pair_escaped_quote():
    out = redact.redact('"X_TOKEN": "ab\\"cd"')
    assert "cd" not in out


def test_env_line():
    out = redact.redact("API_KEY=abc123\nexport TOKEN=zz\n")
    assert "abc123" not in out and "zz" not in out


def test_lowercase_key_not_redacted():
    text = '"keyword-research": "off"'
    assert redact.redact(text) == text


def test_value_prefixes():
    samples = ["sk_live_abcdef0123", "sk-ant-api03-xyz", "github_pat_11AAA", "ghp_" + "a" * 36,
               "xoxb-1-2", "AKIA" + "B" * 16, "fc-abcdef", "eyJ" + "a" * 30 + "."]
    for s in samples:
        assert s not in redact.redact(f"value {s} end"), s


def test_bearer_and_url_credentials():
    out = redact.redact("Authorization: Bearer abc.def and https://user:pw@host/path")
    assert "abc.def" not in out and ":pw@" not in out


def test_private_key_block():
    out = redact.redact("-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----")
    assert "AAAA" not in out


def test_high_entropy_token():
    token = secrets.token_urlsafe(30)
    assert token not in redact.redact(f"x={token}")
    low = "configuration-management-tooling"
    assert low in redact.redact(low)


def test_has_secret():
    assert redact.has_secret('"T": "sk_live_x"')
    assert not redact.has_secret("plain text")
