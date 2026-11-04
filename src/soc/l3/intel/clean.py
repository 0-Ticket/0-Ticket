"""밖에서 온 제목·요약을 평문으로 만든다.

HTML 태그를 지우고 엔티티를 풀고, 제어 문자·짝 없는 서로게이트를 지우고, 공백을 하나로 줄인다.
PostgreSQL text는 NUL을 받지 않고, 서로게이트는 UTF-8로 바꿀 수 없다.
"""

import re
import unicodedata
from html.parser import HTMLParser

# 단어 중간에 올 수 있는 태그. 나머지 태그는 공백으로 바꿔 앞뒤 낱말이 붙지 않게 한다.
_INLINE = {
    "a",
    "abbr",
    "b",
    "code",
    "em",
    "i",
    "mark",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "u",
}
_SKIP = {"script", "style"}
# 정리한 결과에 아직 태그처럼 보이는 것이 있으면 한 번 더 푼다(이중 인코딩된 RSS 설명).
_TAG_LIKE = re.compile(r"<[A-Za-z/!?]")
_ROUNDS = 3


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP:
            self._skipping += 1
        elif tag not in _INLINE:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skipping = max(0, self._skipping - 1)
        elif tag not in _INLINE:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def _strip_html(value: str) -> str:
    parser = _TextOnly()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


def _drop_control(value: str) -> str:
    out = []
    for ch in value:
        if ch in "\t\n\r":
            out.append(" ")
        elif unicodedata.category(ch) not in ("Cc", "Cs"):
            out.append(ch)
    return "".join(out)


def clean_text(value: str, max_chars: int | None = None) -> str:
    text = _drop_control(value)
    for _ in range(_ROUNDS):
        text = _strip_html(text)
        if not _TAG_LIKE.search(text):
            break
    text = " ".join(_drop_control(text).split())
    if max_chars is not None:
        text = text[:max_chars].rstrip()
    return text
