import re

from nova.domain.arithmetic import calculate, is_arithmetic
from nova.domain.text import ActionClassification, Intent, TextResult, matching_text, normalize_text


class IntentRouter:
    """Tam eşleşen kurallar; hiçbir executable, tool veya provider erişimi yok."""

    def route(self, text: str) -> TextResult:
        normalized = normalize_text(text)
        key = matching_text(normalized)
        if key.rstrip(".!?") in {"merhaba", "selam", "selamlar", "günaydın", "iyi akşamlar", "iyi günler"}:
            return TextResult(text, normalized, Intent.GREETING, "Merhaba! Size nasıl yardımcı olabilirim?")

        action = self.action(normalized, key)
        if action is not None:
            return TextResult(text, normalized, Intent.ACTION_REQUEST,
                              "Eylem isteğini sınıflandırdım. Bu yanıt işlem başlatmaz; kayıtlı Windows görevi için ayrıca izin kontrolü gerekir.", action=action)
        if is_arithmetic(normalized):
            arithmetic, reply = calculate(normalized)
            return TextResult(text, normalized, Intent.ARITHMETIC, reply, arithmetic=arithmetic)
        if key.endswith("?") or re.search(r"\b(?:nedir|nasıl|neden|kim|nerede|ne zaman)\b", key):
            return TextResult(text, normalized, Intent.GENERAL_CHAT,
                              "Genel soruları henüz yanıtlayamıyorum. Selamlaşabilir veya aritmetik hesaplayabilirim.")
        return TextResult(text, normalized, Intent.UNKNOWN,
                          "Bu isteği tanıyamadım. “Merhaba” veya “2 + 2 kaç?” yazabilirsiniz.")

    @staticmethod
    def action(normalized: str, key: str) -> ActionClassification | None:
        # Birleşik/belirsiz talebi parçalayıp çalıştırılabilir adımlara dönüştürmez.
        if re.search(r"\b(?:ve|veya|ya da|belki)\b", key):
            return None
        match = re.fullmatch(r"(.+?)\s+(?:aç|başlat)[.!?]?", key)
        if match:
            target = normalized[:match.end(1)]
            target = re.sub(r"['’](?:u|ü|ı|i|yu|yü|yı|yi|nu|nü|nı|ni)$", "", target, flags=re.IGNORECASE)
            if 1 <= len(target) <= 64 and all(c.isalnum() or c in " .-'’" for c in target):
                return ActionClassification("open_application", target)
        match = re.fullmatch(r"(?:dosya ara|web(?:'de|’de)? ara)\s+(.+)", key)
        if match:
            operation = "search_files" if key.startswith("dosya") else "web_search"
            return ActionClassification(operation, normalized[match.start(1):])
        return None
