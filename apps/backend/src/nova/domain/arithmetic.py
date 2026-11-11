"""Sınırlı tokenizer + recursive descent; Python değerlendirme mekanizması yok."""
from decimal import Context, Decimal, DecimalException, Inexact, ROUND_HALF_UP, Underflow, localcontext
import re

from nova.domain.text import ArithmeticResult, TextError, matching_text

MAX_EXPRESSION_LENGTH = 256
MAX_TOKENS = 128
MAX_DEPTH = 16
MAX_VALUE = Decimal("1000000000000")
ONES = ("sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz")
TENS = ("", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan")
SCALES = ((10**12, "trilyon"), (10**9, "milyar"), (10**6, "milyon"), (1000, "bin"))
NUMBER_WORDS = {word: value for value, word in enumerate(ONES)} | {word: i * 10 for i, word in enumerate(TENS) if word}
OPERATORS = {"artı": "+", "eksi": "-", "çarpı": "*", "kere": "*", "bölü": "/"}
LEXEME = re.compile(r"[0-9]+(?:[.,][0-9]+)?|[^\W\d_]+|[()+*/-]", re.UNICODE)


def invalid() -> TextError:
    return TextError("ARITHMETIC_INVALID", "Aritmetik ifade geçersiz veya desteklenmiyor.")


def limited() -> TextError:
    return TextError("ARITHMETIC_LIMIT", "Aritmetik ifade güvenli işlem sınırını aşıyor.")


def integer_words(value: int) -> str:
    if value == 0:
        return ONES[0]
    words = []
    for scale, word in SCALES:
        group, value = divmod(value, scale)
        if group:
            if not (scale == 1000 and group == 1):
                words.append(integer_words(group))
            words.append(word)
    hundreds, value = divmod(value, 100)
    if hundreds:
        if hundreds != 1:
            words.append(ONES[hundreds])
        words.append("yüz")
    tens, ones = divmod(value, 10)
    if tens:
        words.append(TENS[tens])
    if ones:
        words.append(ONES[ones])
    return " ".join(words)


def word_number(words: list[str]) -> Decimal:
    total, group = 0, 0
    scales = {name: value for value, name in SCALES}
    for word in words:
        if word in NUMBER_WORDS:
            group += NUMBER_WORDS[word]
        elif word == "yüz":
            group = (group or 1) * 100
        elif word in scales:
            total += (group or 1) * scales[word]
            group = 0
        else:
            raise invalid()
        if total + group > MAX_VALUE:
            raise limited()
    value = total + group
    if integer_words(value) != " ".join(words):
        raise invalid()
    return Decimal(value)


def expression_text(text: str) -> str:
    text = matching_text(text).translate(str.maketrans({"×": "*", "÷": "/", "−": "-"})).strip()
    text = re.sub(r"^hesapla\s+", "", text)
    text = re.sub(r"\s+(?:kaç(?:\s+eder)?|ne\s+eder|hesapla)\s*\??$", "", text)
    return text.removesuffix("?").strip()


def is_arithmetic(text: str) -> bool:
    key = matching_text(text)
    expression = expression_text(text)
    if key.startswith("hesapla "):
        return True
    if re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", expression):
        return True
    first = re.match(r"[^\W\d_]+", expression)
    starting_words = set(NUMBER_WORDS) | {"yüz", "eksi", "artı"} | {name for _, name in SCALES}
    number_start = bool(expression and expression[0] in "0123456789(+-") or bool(first and first[0] in starting_words)
    return number_start and bool(re.search(r"[+*/()-]|\b(?:artı|eksi|çarpı|kere|bölü)\b", expression))


def tokenize(expression: str) -> list[str | Decimal]:
    if not expression or len(expression) > MAX_EXPRESSION_LENGTH:
        raise limited() if len(expression) > MAX_EXPRESSION_LENGTH else invalid()
    raw, position = [], 0
    while position < len(expression):
        if expression[position].isspace():
            position += 1
            continue
        token = LEXEME.match(expression, position)
        if token is None:
            raise invalid()
        raw.append(token[0])
        if len(raw) > MAX_TOKENS:
            raise limited()
        position = token.end()
    result: list[str | Decimal] = []
    index = 0
    words = set(NUMBER_WORDS) | {"yüz"} | {name for _, name in SCALES}
    while index < len(raw):
        token = raw[index]
        if token in words:
            end = index + 1
            while end < len(raw) and raw[end] in words:
                end += 1
            result.append(word_number(raw[index:end]))
            index = end
            continue
        if token in OPERATORS:
            result.append(OPERATORS[token])
        elif token in {"+", "-", "*", "/", "(", ")"}:
            result.append(token)
        elif re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", token):
            parts = re.split(r"[.,]", token)
            if len(parts[0]) > 13 or (len(parts) == 2 and len(parts[1]) > 6):
                raise limited()
            value = Decimal(token.replace(",", "."))
            if value > MAX_VALUE:
                raise limited()
            result.append(value)
        else:
            raise invalid()
        index += 1
    return result


class Parser:
    def __init__(self, tokens: list[str | Decimal]):
        self.tokens = tokens
        self.position = 0

    def peek(self) -> str | Decimal | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    @staticmethod
    def checked(value: Decimal) -> Decimal:
        if not value.is_finite() or abs(value) > MAX_VALUE:
            raise limited()
        return value

    def expression(self, depth: int = 0) -> Decimal:
        value = self.term(depth)
        while self.peek() in {"+", "-"}:
            operator = self.peek()
            self.position += 1
            right = self.term(depth)
            value = self.checked(value + right if operator == "+" else value - right)
        return value

    def term(self, depth: int) -> Decimal:
        value = self.factor(depth)
        while self.peek() in {"*", "/"}:
            operator = self.peek()
            self.position += 1
            right = self.factor(depth)
            if operator == "/" and right == 0:
                raise TextError("ARITHMETIC_DIVISION_BY_ZERO", "Sıfıra bölme yapılamaz.")
            value = self.checked(value * right if operator == "*" else value / right)
        return value

    def factor(self, depth: int) -> Decimal:
        token = self.peek()
        if token in {"+", "-", "("}:
            if depth >= MAX_DEPTH:
                raise limited()
            self.position += 1
            if token == "(":
                value = self.expression(depth + 1)
                if self.peek() != ")":
                    raise invalid()
                self.position += 1
                return value
            value = self.factor(depth + 1)
            return -value if token == "-" else value
        if isinstance(token, Decimal):
            self.position += 1
            return token
        raise invalid()


def calculate(text: str) -> tuple[ArithmeticResult, str]:
    expression = expression_text(text)
    with localcontext(Context(prec=28, Emax=50, Emin=-50)) as context:
        context.traps[Underflow] = True
        try:
            parser = Parser(tokenize(expression))
            value = parser.expression()
            if parser.position != len(parser.tokens):
                raise invalid()
            displayed = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            rounded = displayed != value or context.flags[Inexact]
        except DecimalException:
            raise limited() from None
    if displayed == 0:
        displayed = Decimal(0)
    canonical = format(displayed, "f").rstrip("0").rstrip(".") if "." in format(displayed, "f") else format(displayed, "f")
    magnitude = canonical.removeprefix("-")
    whole, _, fraction = magnitude.partition(".")
    words = ("eksi " if displayed < 0 else "") + integer_words(int(whole))
    if fraction:
        words += " virgül " + " ".join(ONES[int(digit)] for digit in fraction)
    reply = ("İ" if words[0] == "i" else words[0].upper()) + words[1:] + "."
    if rounded:
        reply += " Sonuç altı ondalık basamağa yuvarlandı."
    return ArithmeticResult(expression=expression, value=canonical, rounded=rounded), reply
