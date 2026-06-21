import re
import logging
from typing import List

logger = logging.getLogger(__name__)

CHINESE_ABBREVIATIONS = [
    "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Jr.", "Sr.", "vs.", "etc.",
    "e.g.", "i.e.", "cf.", "p.m.", "a.m.", "Ph.D.", "U.S.", "U.K.",
    "U.N.", "E.U.", "N.Y.", "L.A.", "B.C.", "A.D.",
]

CHINESE_PUNCT = "。！？!?；;"
SENTENCE_SPLIT_PATTERN = re.compile(
    r"(?<=[。！？!?；;])(?=[^\"'）」』】〉》])|"
    r"(?<=[。！？!?；;][\"'）」』】〉》])"
)

DECIMAL_PATTERN = re.compile(r"\d+\.\d+")


def _protect_decimals(text: str) -> tuple:
    placeholders = []
    def replace(match):
        placeholders.append(match.group())
        return f"__DECIMAL_{len(placeholders) - 1}__"
    protected = DECIMAL_PATTERN.sub(replace, text)
    return protected, placeholders


def _restore_decimals(text: str, placeholders: List[str]) -> str:
    for i, ph in enumerate(placeholders):
        text = text.replace(f"__DECIMAL_{i}__", ph)
    return text


def _is_abbreviation_end(sentence: str) -> bool:
    for abbr in CHINESE_ABBREVIATIONS:
        if sentence.rstrip().endswith(abbr):
            return True
    return False


def split_sentences(text: str) -> List[str]:
    if not text or not text.strip():
        return []

    protected, decimals = _protect_decimals(text)

    raw_splits = SENTENCE_SPLIT_PATTERN.split(protected)

    sentences: List[str] = []
    buffer = ""

    for part in raw_splits:
        buffer += part
        stripped = buffer.strip()
        if not stripped:
            buffer = ""
            continue

        if _is_abbreviation_end(stripped):
            continue

        has_ending = any(p in stripped[-3:] if len(stripped) >= 3 else stripped for p in "。！？!?；;")
        if has_ending or len(sentences) == 0 and stripped:
            restored = _restore_decimals(buffer.strip(), decimals)
            if restored:
                sentences.append(restored)
            buffer = ""

    if buffer.strip():
        restored = _restore_decimals(buffer.strip(), decimals)
        if restored:
            sentences.append(restored)

    return [s for s in sentences if s and s.strip()]


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.encode("utf-8", errors="ignore").decode("utf-8")

    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    text = re.sub(
        r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*",
        "",
        text,
    )
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)

    return text.strip()


def preprocess_text(raw_text: str) -> tuple:
    cleaned = clean_text(raw_text)
    sentences = split_sentences(cleaned)
    return cleaned, sentences
