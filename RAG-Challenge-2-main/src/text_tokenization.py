"""Local tokenization helpers for exact-term and Chinese sparse retrieval."""

from __future__ import annotations

import re
from typing import List
import unicodedata


_LEXEME_RE = re.compile(
    r"/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+"
    r"|[A-Za-z0-9]+(?:[._:-][A-Za-z0-9]+)+"
    r"|[A-Za-z]+"
    r"|\d+(?:\.\d+)?"
    r"|[\u4e00-\u9fff]+"
)


def technical_tokenize(text: str) -> List[str]:
    """Tokenize Chinese prose while retaining exact engineering identifiers."""
    tokens: List[str] = []
    for match in _LEXEME_RE.finditer(str(text).casefold()):
        lexeme = match.group(0)
        if re.fullmatch(r"[\u4e00-\u9fff]+", lexeme):
            if len(lexeme) <= 12:
                tokens.append(lexeme)
            tokens.extend(lexeme)
            tokens.extend(lexeme[index : index + 2] for index in range(len(lexeme) - 1))
            continue

        tokens.append(lexeme)
        if any(separator in lexeme for separator in ("/", "-", "_", ".", ":")):
            tokens.extend(
                part
                for part in re.split(r"[/_.:-]+", lexeme)
                if part and part != lexeme
            )
    # Preserve corpus term frequency for BM25.  Exact identifiers are added as
    # whole tokens and as components, but repeated source terms stay repeated.
    return tokens


# The frozen BM25 baseline imports ``technical_tokenize``.  Keep an explicit
# name for experiment manifests/tests without changing that function's output.
technical_tokenize_v1 = technical_tokenize


_CAMEL_BOUNDARY_RE = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)


def normalize_technical_text_v2(text: str) -> str:
    """Apply the shared deterministic V2 normalization contract."""
    normalized = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"\s+", " ", normalized).strip()


def _unique_in_order(values: List[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


def technical_tokenize_v2(text: str) -> List[str]:
    """Tokenize technical text with symmetric normalization and bounded splits.

    Each ASCII identifier occurrence contributes its case-folded full token and
    only its first-level separator or camelCase components.  No combination
    n-grams are manufactured, and natural repetitions in the source are kept.
    Chinese segmentation intentionally matches the V1 behavior.
    """
    normalized = normalize_technical_text_v2(text)
    tokens: List[str] = []
    for match in _LEXEME_RE.finditer(normalized):
        raw_lexeme = match.group(0)
        lexeme = raw_lexeme.casefold()
        if re.fullmatch(r"[\u4e00-\u9fff]+", raw_lexeme):
            if len(lexeme) <= 12:
                tokens.append(lexeme)
            tokens.extend(lexeme)
            tokens.extend(lexeme[index : index + 2] for index in range(len(lexeme) - 1))
            continue

        tokens.append(lexeme)
        if any(separator in raw_lexeme for separator in ("/", "-", "_", ".", ":")):
            parts = [
                part.casefold()
                for part in re.split(r"[/_.:-]+", raw_lexeme)
                if part
            ]
            tokens.extend(_unique_in_order(parts))
            continue

        camel_parts = _CAMEL_BOUNDARY_RE.split(raw_lexeme)
        if len(camel_parts) > 1:
            tokens.extend(_unique_in_order([part.casefold() for part in camel_parts]))
    return tokens
