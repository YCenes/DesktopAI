from nova.domain.router import IntentRouter
from nova.domain.text import TextResult


class TextProcessingService:
    def __init__(self, router: IntentRouter | None = None):
        self.router = router if router is not None else IntentRouter()

    def process(self, text: str) -> TextResult:
        return self.router.route(text)
