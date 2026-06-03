from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class UnsupportedReason(str, Enum):
    DESTRUCTIVE_OPERATION = "destructive_operation"
    EXTERNAL_WEB_REQUEST = "external_web_request"
    EXTERNAL_COMMUNICATION_REQUEST = "external_communication_request"
    FILE_GENERATION_REQUEST = "file_generation_request"
    NON_CSV_TASK = "non_csv_task"


@dataclass(frozen=True)
class UnsupportedPattern:
    reason: UnsupportedReason
    signal: str
    pattern: str


@dataclass(frozen=True)
class UnsupportedMatch:
    reason: UnsupportedReason
    signal: str
    pattern: str


class UnsupportedPolicy:
    """
    Classifies requests that are outside the CSV analytics system scope.

    Important:
    The system should handle unrelated requests by routing them to
    unsupported_query with unsupported_reason="non_csv_task", not by trying
    to answer or execute them.
    """

    PATTERNS: list[UnsupportedPattern] = [
        UnsupportedPattern(
            reason=UnsupportedReason.DESTRUCTIVE_OPERATION,
            signal="destructive_dataset_operation",
            pattern=r"\b(delete|drop|truncate|alter|update|insert|overwrite|rename)\b.*\b(dataset|table|database|csv|records?|rows?|columns?)\b",
        ),
        UnsupportedPattern(
            reason=UnsupportedReason.EXTERNAL_COMMUNICATION_REQUEST,
            signal="external_communication_request",
            pattern=r"\b(send|email|message|call)\b",
        ),
        UnsupportedPattern(
            reason=UnsupportedReason.EXTERNAL_WEB_REQUEST,
            signal="external_web_request",
            pattern=r"\b(search|browse|google|look\s+up)\b.*\b(web|internet|online)\b",
        ),
        UnsupportedPattern(
            reason=UnsupportedReason.FILE_GENERATION_REQUEST,
            signal="file_generation_request",
            pattern=r"\b(write|draft|create|generate)\b.*\b(document|essay|assignment|letter|resume|cv|cover\s+letter|poem|story)\b",
        ),
        UnsupportedPattern(
            reason=UnsupportedReason.NON_CSV_TASK,
            signal="joke_request",
            pattern=r"\b(tell\s+me\s+a\s+joke|joke)\b",
        ),
        UnsupportedPattern(
            reason=UnsupportedReason.NON_CSV_TASK,
            signal="programming_explanation_request",
            pattern=r"\b(explain|teach|define)\b.*\b(python|java|javascript|react|node|algorithm|decorator|class|inheritance)\b",
        ),
        UnsupportedPattern(
            reason=UnsupportedReason.NON_CSV_TASK,
            signal="travel_booking_request",
            pattern=r"\b(book|reserve|find)\b.*\b(hotel|flight|restaurant|ticket|trip)\b",
        ),
        UnsupportedPattern(
            reason=UnsupportedReason.NON_CSV_TASK,
            signal="current_info_request",
            pattern=r"\b(weather|news|sports\s+score|stock\s+price|exchange\s+rate)\b",
        ),
        UnsupportedPattern(
            reason=UnsupportedReason.NON_CSV_TASK,
            signal="general_factual_question",
            pattern=r"\b(who\s+is|when\s+is|where\s+is)\b.*\b(president|prime\s+minister|capital|movie|song|celebrity|country)\b",
        ),
    ]

    def classify(self, normalized_question: str) -> UnsupportedMatch | None:
        for unsupported_pattern in self.PATTERNS:
            if re.search(
                unsupported_pattern.pattern,
                normalized_question,
                flags=re.IGNORECASE,
            ):
                return UnsupportedMatch(
                    reason=unsupported_pattern.reason,
                    signal=unsupported_pattern.signal,
                    pattern=unsupported_pattern.pattern,
                )

        return None

    @staticmethod
    def collect_patterns(
        patterns: Iterable[UnsupportedPattern],
    ) -> list[str]:
        return [pattern.signal for pattern in patterns]