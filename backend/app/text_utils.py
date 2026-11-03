"""Spanish-aware text normalisation, shared by the fake providers, quote verification and
the prompt-injection detector. Matching is case- and accent-insensitive."""

import re
import unicodedata

_WORD = re.compile(r"[a-z0-9]+")

# Small Spanish stopword list, stored accent-free because it is compared with `fold`ed text.
# A plain word list reads better than a hundred quoted strings.
SPANISH_STOPWORDS = frozenset(
    """
    a al algo alguna algunas alguno algunos ante antes aqui asi aun cada como con contra cual
    cuales cualquier cuando de del desde donde e el ella ellas ello ellos en entre era eran es
    esa esas ese eso esos esta estaba estan estar estas este esto estos fue fueron ha haber
    habia han hasta hay la las le les lo los mas me mi mis muy nada ni nos o os otra otras
    otro otros para pero por porque que quien quienes se sea ser si sido sin sino sobre su sus
    tal tambien tanto te tiene tienen todo todos tu tus u un una unas uno unos usted ustedes
    y ya yo
    """.split()  # noqa: SIM905
)


def fold(text: str) -> str:
    """Lowercase and strip diacritics: 'Póliza Daños' -> 'poliza danos'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokenize(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def content_words(text: str) -> list[str]:
    """Tokens that carry meaning: no stopwords, no single characters."""
    return [t for t in tokenize(text) if len(t) > 1 and t not in SPANISH_STOPWORDS]


def normalize_for_match(text: str) -> str:
    """Canonical form for verbatim-quote checks: case/accent/punctuation/spacing-insensitive."""
    return " ".join(tokenize(text))


def estimate_tokens(text: str) -> int:
    """Rough token count (~4 characters per token) for providers that report none."""
    return max(1, len(text) // 4)
