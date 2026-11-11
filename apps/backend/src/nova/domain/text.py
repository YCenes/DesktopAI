from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
import unicodedata

MAX_TEXT_LENGTH = 1024


class TextError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Intent(StrEnum):
    GREETING = "greeting"
    ARITHMETIC = "arithmetic"
    ACTION_REQUEST = "action_request"
    GENERAL_CHAT = "general_chat"
    UNKNOWN = "unknown"


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise TextError("TEXT_INVALID", "Mesaj metin olmalıdır.")
    if len(text) > MAX_TEXT_LENGTH:
        raise TextError("TEXT_TOO_LONG", "Mesaj en fazla 1.024 karakter olabilir.")
    if any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} and not c.isspace() for c in text):
        raise TextError("TEXT_INVALID", "Mesaj desteklenmeyen kontrol karakterleri içeriyor.")
    normalized = " ".join(unicodedata.normalize("NFC", text).split())
    if len(normalized) > MAX_TEXT_LENGTH:
        raise TextError("TEXT_TOO_LONG", "Mesaj en fazla 1.024 karakter olabilir.")
    if not normalized:
        raise TextError("TEXT_EMPTY", "Mesaj boş olamaz.")
    return normalized


def matching_text(text: str) -> str:
    # Yalnızca eşleştirme anahtarıdır; özgün/normalize metin değiştirilmez.
    return text.translate(str.maketrans({"I": "ı", "İ": "i"})).lower()


@dataclass(frozen=True)
class ActionClassification:
    operation: Literal["open_application", "search_files", "web_search"]
    target: str
    executable: Literal[False] = False


@dataclass(frozen=True)
class ArithmeticResult:
    expression: str
    value: str
    rounded: bool


@dataclass(frozen=True)
class TextResult:
    original_text: str
    normalized_text: str
    intent: Intent
    reply: str
    action: ActionClassification | None = None
    arithmetic: ArithmeticResult | None = None
    api_version: Literal["1"] = "1"
    external_calls: Literal[0] = 0
