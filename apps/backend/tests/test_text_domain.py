import ast
from decimal import Inexact, getcontext, localcontext
from pathlib import Path
import os
import socket
import subprocess

import pytest

from nova.application.text_processing import TextProcessingService
from nova.domain.arithmetic import calculate
from nova.domain.router import IntentRouter
from nova.domain.text import MAX_TEXT_LENGTH, TextError, matching_text, normalize_text


@pytest.mark.parametrize("raw,expected", [
    ("  Merhaba\t\n dünya \r\n", "Merhaba dünya"),
    ("IŞIK İSTANBUL ıi ŞĞÜÖÇ", "IŞIK İSTANBUL ıi ŞĞÜÖÇ"),
    ("I\u0307stanbul", "İstanbul"), ("bir\u00a0\u2003iki\u0085üç", "bir iki üç"),
    ("Merhaba 👋", "Merhaba 👋"),
])
def test_normalization_preserves_unicode_meaning(raw, expected):
    assert normalize_text(raw) == expected
    result = IntentRouter().route(raw)
    assert result.original_text == raw
    assert result.normalized_text == expected


def test_turkish_matching_key_is_separate():
    assert matching_text("IŞIK İYİ ÇARPI") == "ışık iyi çarpı"


@pytest.mark.parametrize("text,code", [
    ("", "TEXT_EMPTY"), (" \t\n\u00a0", "TEXT_EMPTY"),
    ("a" * (MAX_TEXT_LENGTH + 1), "TEXT_TOO_LONG"), ("😀" * 1025, "TEXT_TOO_LONG"),
    ("\u0344" * 600, "TEXT_TOO_LONG"),
    ("a\x00b", "TEXT_INVALID"), ("a\u202eb", "TEXT_INVALID"), ("a\ud800", "TEXT_INVALID"),
])
def test_input_rejections(text, code):
    with pytest.raises(TextError) as error:
        normalize_text(text)
    assert error.value.code == code


def test_unicode_character_boundary_not_bytes_or_utf16():
    assert normalize_text("😀" * 1024) == "😀" * 1024
    assert len(normalize_text("Ş" * 1024)) == 1024


@pytest.mark.parametrize("text,value,reply", [
    ("2 + 2 kaç?", "4", "Dört."), ("15 çarpı 4", "60", "Altmış."), ("10 / 2", "5", "Beş."),
    ("iki artı iki", "4", "Dört."), ("on iki bölü üç", "4", "Dört."),
    ("(on eksi üç) kere iki kaç eder?", "14", "On dört."),
    ("2 + 3 * 4", "14", "On dört."), ("(2 + 3) × 4", "20", "Yirmi."),
    ("-2 - -3", "1", "Bir."), ("eksi beş artı iki", "-3", "Eksi üç."),
    ("1,5 + 2.5", "4", "Dört."), ("0,1 + 0,2", "0.3", "Sıfır virgül üç."),
    ("1 / 8", "0.125", "Sıfır virgül bir iki beş."),
    ("iki yüz otuz dört + altı", "240", "İki yüz kırk."),
    ("1000000000000", "1000000000000", "Bir trilyon."),
    ("15 ÇARPI 4", "60", "Altmış."), ("hesapla 10 ÷ 2", "5", "Beş."),
])
def test_safe_arithmetic(text, value, reply):
    result, actual_reply = calculate(text)
    assert result.value == value
    assert actual_reply == reply
    assert not result.rounded


def test_rounding_is_explicit_and_decimal_context_is_not_modified():
    previous = getcontext().copy()
    result, reply = calculate("1 / 3")
    assert result.value == "0.333333" and result.rounded
    assert "yuvarlandı" in reply
    assert getcontext().prec == previous.prec


def test_arithmetic_does_not_inherit_ambient_decimal_flags_or_traps():
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.flags[Inexact] = True
        ambient.traps[Inexact] = True
        result, reply = calculate("2+2")
        assert result.rounded is False and reply == "Dört."
        assert calculate("1/3")[0].rounded is True
        assert ambient.prec == 2 and ambient.traps[Inexact]


@pytest.mark.parametrize("expression", ["1/0", "3 / (2-2)", "0/0"])
def test_division_by_zero(expression):
    with pytest.raises(TextError) as error:
        calculate(expression)
    assert error.value.code == "ARITHMETIC_DIVISION_BY_ZERO"


@pytest.mark.parametrize("expression", [
    "", "2 +", "2 2", "(2+2", "2+2)", "2**8", "2//3", "1e10", "NaN", "Infinity",
    "2+__import__('os').system('calc')", "open('private.txt')", "[1,2][0]", "2;print(1)",
    "lambda: 2", "iki iki + bir", "iki + bilinmeyen", "1.2.3", "2+2 ve Chrome'u aç",
])
def test_malformed_and_injection_expressions_are_rejected(expression):
    with pytest.raises(TextError):
        calculate(expression)


@pytest.mark.parametrize("expression", [
    "9" * 100, "1000000000001", "1000000000000+1", "1000000*10000000",
    "(" * 17 + "1" + ")" * 17, "-" * 17 + "1", "1+" * 128 + "1",
    "0.1234567", "yüz " * 50 + "+ bir", "0.000001" + "*0.000001" * 14,
])
def test_resource_bounds(expression):
    with pytest.raises(TextError) as error:
        calculate(expression)
    assert error.value.code == "ARITHMETIC_LIMIT"


@pytest.mark.parametrize("text,intent", [
    ("Merhaba", "greeting"), ("İYİ GÜNLER!", "greeting"),
    ("2 + 2 kaç?", "arithmetic"), ("15 çarpı 4", "arithmetic"),
    ("yüz artı bir", "arithmetic"), ("eksi beş artı iki", "arithmetic"),
    ("bin eksi bir", "arithmetic"), ("Bugün hava kaç?", "general_chat"),
    ("Chrome'u aç", "action_request"), ("Not Defteri’ni aç", "action_request"),
    ("dosya ara rapor", "action_request"), ("web'de ara hava durumu", "action_request"),
    ("Python nedir?", "general_chat"), ("Chrome'u açmak güvenli mi?", "general_chat"),
    ("Chrome'u aç veya kapat", "unknown"), ("belki Chrome'u aç", "unknown"),
    ("rastgele komut", "unknown"), ("__import__('os')", "unknown"),
])
def test_intent_classification(text, intent):
    result = IntentRouter().route(text)
    assert result.intent == intent
    assert result.external_calls == 0
    assert (result.action is not None) == (intent == "action_request")


def test_action_is_metadata_and_chat_does_not_pretend_to_answer():
    result = IntentRouter().route("Chrome'u aç")
    assert result.action.target == "Chrome"
    assert result.action.operation == "open_application"
    assert result.action.executable is False
    chat = IntentRouter().route("Python nedir?")
    assert chat.action is None
    assert "yanıtlayamıyorum" in chat.reply
    assert IntentRouter().route("CHROME’U AÇ").action.target == "CHROME"


def test_all_intents_are_offline_and_side_effect_free(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Router ağ veya OS yürütme yeteneği kullanamaz")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", forbidden)
    service = TextProcessingService()
    for text in ("Merhaba", "2+2", "Chrome'u aç", "Python nedir?", "bilinmeyen"):
        assert service.process(text).external_calls == 0


def test_domain_has_no_framework_provider_or_execution_dependencies():
    root = Path(__file__).parents[1] / "src/nova/domain"
    forbidden = {"fastapi", "pydantic", "httpx", "requests", "socket", "subprocess", "os", "langgraph", "openai"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(alias.name.split(".")[0] in forbidden for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "compile", "__import__"}
