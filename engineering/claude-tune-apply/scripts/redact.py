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
_ENV_LINE_RE = re.compile(r"(?m)^(\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=).*$")
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
    re.compile(r"(?i)\bBearer\s+\S+"),
    re.compile(r"(?<=://)[^\s/@]*:[^\s@]*@"),
    re.compile(r"(?<![A-Za-z0-9])[0-9a-fA-F]{32,}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{32,}={1,2}"),
)
_HIGH_ENTROPY_RE = re.compile(r"[A-Za-z0-9_-]{32,}")
ENTROPY_BITS = 4.5  # 40 random url-safe chars score above 5; English identifiers below 4.2


def key_is_sensitive(key: str) -> bool:
    """True when any word of the key (split on -_. and camelCase) names a credential."""
    words = {w.lower() for w in _WORD_SPLIT_RE.split(key) if w}
    return bool(words & SECRET_WORDS)


def _redact_json_pair(m: re.Match) -> str:
    if not key_is_sensitive(m.group("key")):
        return m.group(0)
    return m.group(1) + REDACTED + m.group(m.lastindex)


def _redact_env_line(m: re.Match) -> str:
    return m.group(1) + REDACTED if key_is_sensitive(m.group(2)) else m.group(0)


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
    out = _ENV_LINE_RE.sub(_redact_env_line, out)
    out = _PRIVATE_KEY_RE.sub(f"-----BEGIN PRIVATE KEY----- {REDACTED}", out)
    for pattern in SECRET_VALUE_RES:
        out = pattern.sub(REDACTED, out)
    return _redact_high_entropy(out)


def has_secret(text: str) -> bool:
    """True when `redact` would change the text, excluding key-only matches on empty values."""
    return redact(text) != text
