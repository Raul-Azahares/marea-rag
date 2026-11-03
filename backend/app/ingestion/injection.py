"""Heuristic detection of prompt-injection attempts inside documents.

This is *not* the security boundary: a determined attacker can paraphrase. The real defences
are structural:
- fragments are delimited and declared untrusted in the prompt;
- the model has no tools and cannot take actions;
- every claim must quote a retrieved fragment.

This flag makes suspicious fragments visible: they are counted in logs (by id, never by
content), marked in the prompt and surfaced as a warning to the user.
"""

import re

from app.text_utils import fold

SUSPECTED_INJECTION = "suspected_prompt_injection"

_PATTERNS = [
    re.compile(p)
    for p in (
        r"\b(ignora|ignore|ignorar|ignorad|olvida|olvidad|disregard|forget)\b.{0,60}"
        r"\b(instruccion\w*|indicacion\w*|reglas?|instructions?|previous|anterior\w*|above)\b",
        r"\b(system prompt|prompt del sistema|mensaje del sistema|instrucciones del sistema)\b",
        r"\b(ahora eres|you are now|actua como|act as)\b",
        r"\b(asistente|assistant|modelo de lenguaje|language model|ia|ai)\b.{0,40}"
        r"\b(debe|debes|must|should)\b.{0,40}\b(responder|answer|decir|say)\b",
        r"<\s*/?\s*(system|assistant|instructions?)\s*>",
        r"\[\s*/?\s*(inst|sys)\s*\]",
        r"<\|[a-z_]{2,20}\|>",
    )
]


def detect_injection(text: str) -> bool:
    folded = fold(text)
    return any(pattern.search(folded) for pattern in _PATTERNS)


def chunk_flags(text: str) -> list[str]:
    return [SUSPECTED_INJECTION] if detect_injection(text) else []
