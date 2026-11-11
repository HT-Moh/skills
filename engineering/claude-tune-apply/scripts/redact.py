"""Hide credential values in any text the engine prints or stores.

Two lines of defence: keys whose words name a secret (token, secret, key, password,
authorization, in any case or casing style) and values that look like one (known prefixes,
bearer headers, URL credentials, long hex or base64 runs, private-key blocks, high-entropy
tokens).
"""
import math
import re

REDACTED = "<redacted>"
SECRET_WORDS = frozenset({"token", "secret", "key", "apikey", "password", "passwd", "authorization",
                          "credential", "credentials", "bearer"})
_WORD_SPLIT_RE = re.compile(r"[-_.\s]+|(?<=[a-z0-9])(?=[A-Z])")
_JSON_PAIR_RE = re.compile(r'("(?P<key>(?:[^"\\]|\\.)*)"\s*:\s*")(?P<value>(?:[^"\\]|\\.)*)(")')
# KEY=value with no spaces (shell form), anywhere in the text, so quoted env lines are covered;
# "tokens = 35%" in prose is not an assignment and stays readable
_ENV_LINE_RE = re.compile(r"(?<![A-Za-z0-9_])((?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=)(\S+)")
_QUOTED_ASSIGN_RE = re.compile(r"""(?<![A-Za-z0-9_])(([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(["']))((?:(?!\3).)+)\3""")
# `KEY = value` with spaces is prose or code; redacted only when the key is credential-named
# and the value has a credential shape, so "tokens = 35%" survives
_SPACED_ASSIGN_RE = re.compile(r"(?<![A-Za-z0-9_])(([A-Za-z_][A-Za-z0-9_]*)\s*=\s*)(\S+)")
_VALUE_SHAPE_RE = re.compile(r"[A-Za-z0-9_\-./+=]{4,}")
_PLACEHOLDERS = frozenset({"value", "...", "xxx", "<value>", "<token>", "<literal>", "null", "none"})
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)

SECRET_VALUE_RES = (
    re.compile(r"\bsk_live_[A-Za-z0-9]+"),
    re.compile(r"\brk_live_[A-Za-z0-9]+"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]+"),
    re.compile(r"\bxox[abp]-[A-Za-z0-9-]+"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bfc-[A-Za-z0-9]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_.-]*"),
    # canonical "Bearer <token>" always; other casings only when the token holds a non-letter,
    # so prose such as "bearer headers" stays readable
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{6,}"),
    re.compile(r"(?i)\bbearer\s+(?=[A-Za-z0-9._~+/=-]*[0-9._~+/=-])[A-Za-z0-9._~+/=-]{6,}"),
    re.compile(r"(?<=://)[^\s/@]*:[^\s@]*@"),
    re.compile(r"(?<![A-Za-z0-9])[0-9a-fA-F]{32,}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{32,}={1,2}"),
)
_HIGH_ENTROPY_RE = re.compile(r"[A-Za-z0-9_-]{32,}")
ENTROPY_BITS = 4.5  # 40 random url-safe chars score above 5; English identifiers below 4.2


_STRONG_SUBSTRINGS = ("token", "secret", "password", "passwd", "authorization", "credential", "apikey", "privatekey")


def key_is_sensitive(key: str) -> bool:
    """True when a word of the key names a credential, or a strong word is glued in (GITHUBTOKEN)."""
    words = {w.lower() for w in _WORD_SPLIT_RE.split(key) if w}
    if words & SECRET_WORDS:
        return True
    flat = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(s in flat for s in _STRONG_SUBSTRINGS)  # not endswith("key"): "monkey"


def _redact_json_pair(m: re.Match) -> str:
    if not key_is_sensitive(m.group("key")):
        return m.group(0)
    return m.group(1) + REDACTED + m.group(m.lastindex)


def is_reference(value: str) -> bool:
    """A `${VAR}`, `$VAR`, `<placeholder>` or `{template}` stands for a value; it is not one."""
    v = value.strip().strip("\"'`,;")
    return not v or v.lower() in _PLACEHOLDERS or v.startswith(("<", "$", "{"))


def _redact_env_line(m: re.Match) -> str:
    if key_is_sensitive(m.group(2)) and not is_reference(m.group(3)):
        return m.group(1) + REDACTED
    return m.group(0)


def _redact_quoted_assign(m: re.Match) -> str:
    if key_is_sensitive(m.group(2)) and not is_reference(m.group(4)):
        return m.group(1) + REDACTED + m.group(3)
    return m.group(0)


def real_looking(value: str) -> bool:
    """Fail closed: any credential-shaped value counts unless it is a placeholder or a reference."""
    if is_reference(value):
        return False
    return bool(_VALUE_SHAPE_RE.fullmatch(value.strip().strip("\"'`,;")))


def _redact_spaced_assign(m: re.Match) -> str:
    if key_is_sensitive(m.group(2)) and real_looking(m.group(3)):
        return m.group(1) + REDACTED
    return m.group(0)


def _entropy(token: str) -> float:
    counts = {c: token.count(c) for c in set(token)}
    return -sum(n / len(token) * math.log2(n / len(token)) for n in counts.values())


def _redact_high_entropy(text: str) -> str:
    def swap(m: re.Match) -> str:
        token = m.group(0)
        looks_random = any(c.isdigit() for c in token) and _entropy(token) > ENTROPY_BITS
        return REDACTED if looks_random else token
    return _HIGH_ENTROPY_RE.sub(swap, text)


def redact(text: str) -> str:
    """Return `text` with every credential-looking value replaced by <redacted>."""
    out = _JSON_PAIR_RE.sub(_redact_json_pair, text)
    out = _QUOTED_ASSIGN_RE.sub(_redact_quoted_assign, out)
    out = _ENV_LINE_RE.sub(_redact_env_line, out)
    out = _SPACED_ASSIGN_RE.sub(_redact_spaced_assign, out)
    out = _PRIVATE_KEY_RE.sub(f"-----BEGIN PRIVATE KEY----- {REDACTED}", out)
    for pattern in SECRET_VALUE_RES:
        out = pattern.sub(REDACTED, out)
    return _redact_high_entropy(out)


def _value_only(text: str) -> str:
    out = _PRIVATE_KEY_RE.sub(REDACTED, text)
    for pattern in SECRET_VALUE_RES:
        out = pattern.sub(REDACTED, out)
    return _redact_high_entropy(out)


def has_secret(text: str) -> bool:
    """True for a credential-shaped value, or a credential-named key assigned a real-looking value.

    Key names alone, placeholders and ${VAR} references do not count, so a plan may talk about
    `BROWSERLESS_TOKEN=<literal>` without tripping the validator.
    """
    if _value_only(text) != text:
        return True
    for m in _JSON_PAIR_RE.finditer(text):
        if key_is_sensitive(m.group("key")) and real_looking(m.group("value")):
            return True
    for pattern, key_group, value_group in ((_ENV_LINE_RE, 2, 3), (_QUOTED_ASSIGN_RE, 2, 4), (_SPACED_ASSIGN_RE, 2, 3)):
        for m in pattern.finditer(text):
            if key_is_sensitive(m.group(key_group)) and real_looking(m.group(value_group)):
                return True
    return False
