"""Deterministic, corpus-driven version intent detection."""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date
from typing import Iterable

from src.versioning.models import (
    DatePrecision,
    VersionContext,
    VersionIntent,
    VersionMetadata,
)


_DASHES = str.maketrans({"—": "-", "–": "-", "－": "-", "―": "-"})
_CURRENT_TERMS = ("现行", "当前", "目前", "现在", "现版本", "最新版", "有效版本")
_HISTORICAL_TERMS = ("旧版", "历史版本", "原版本", "废止前", "修订前", "当时规定")


def _canonical(value: str) -> str:
    return re.sub(
        r"\s+",
        "",
        unicodedata.normalize("NFKC", value).translate(_DASHES).casefold(),
    )


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


class VersionIntentDetector:
    def __init__(self, documents: Iterable[VersionMetadata]):
        self.documents = list(documents)

    def detect(self, question: str) -> VersionContext:
        canonical_question = _canonical(question)
        matched_document_ids = []
        explicit_versions = []
        matched_families = []
        signals = []

        title_matched_families = {
            document.version_family
            for document in self.documents
            if document.version_family
            and document.title
            and _canonical(document.title) in canonical_question
        }

        for document in self.documents:
            title_match = bool(
                document.title and _canonical(document.title) in canonical_question
            )
            number_match = bool(
                document.document_number
                and _canonical(document.document_number) in canonical_question
            )
            version_match = bool(
                document.version
                and (
                    not title_matched_families
                    or document.version_family in title_matched_families
                )
                and re.search(
                    rf"(?<!\d){re.escape(_canonical(document.version))}(?:版|版本)(?!\d)",
                    canonical_question,
                )
            )
            if number_match or version_match:
                matched_document_ids.append(document.document_id)
                if document.version:
                    explicit_versions.append(document.version)
                if document.version_family:
                    matched_families.append(document.version_family)
                signals.append(
                    f"document_number:{document.document_id}"
                    if number_match
                    else f"version:{document.version}"
                )
            elif title_match and document.version_family:
                matched_families.append(document.version_family)
                signals.append(f"version_family_title:{document.version_family}")

        current_signals = [term for term in _CURRENT_TERMS if term in question]
        historical_signals = [term for term in _HISTORICAL_TERMS if term in question]
        signals.extend(f"current:{term}" for term in current_signals)
        signals.extend(f"historical:{term}" for term in historical_signals)

        temporal = self._extract_temporal_period(question)
        if temporal is not None:
            start, end, precision, signal = temporal
            signals.append(signal)
            query_date = start if precision == DatePrecision.DAY else None
            intent = VersionIntent.TEMPORAL_DATE
        else:
            start = end = query_date = precision = None
            if current_signals:
                intent = VersionIntent.CURRENT
            elif matched_document_ids or explicit_versions:
                intent = VersionIntent.EXPLICIT_VERSION
            elif historical_signals:
                intent = VersionIntent.HISTORICAL
            else:
                intent = VersionIntent.UNSPECIFIED

        return VersionContext(
            intent=intent,
            explicit_versions=_unique(explicit_versions),
            matched_document_ids=_unique(matched_document_ids),
            matched_version_families=_unique(matched_families),
            query_date=query_date,
            query_period_start=start,
            query_period_end=end,
            date_precision=precision,
            signals=_unique(signals),
        )

    @staticmethod
    def _extract_temporal_period(question: str):
        day_match = re.search(
            r"(?<!\d)(\d{4})\s*(?:年|[-/.])\s*(\d{1,2})\s*(?:月|[-/.])\s*(\d{1,2})\s*日?",
            question,
        )
        if day_match:
            point = date(*(int(value) for value in day_match.groups()))
            return point, point, DatePrecision.DAY, f"date:{point.isoformat()}"

        month_match = re.search(r"(?<!\d)(\d{4})\s*年\s*(\d{1,2})\s*月", question)
        if month_match:
            year, month = (int(value) for value in month_match.groups())
            start = date(year, month, 1)
            end = date(year, month, calendar.monthrange(year, month)[1])
            return start, end, DatePrecision.MONTH, f"month:{year:04d}-{month:02d}"

        year_match = re.search(r"(?<!\d)(\d{4})\s*年(?!\s*(?:版|版本))", question)
        if year_match:
            year = int(year_match.group(1))
            return (
                date(year, 1, 1),
                date(year, 12, 31),
                DatePrecision.YEAR,
                f"year:{year:04d}",
            )
        return None
