"""테스트용 가짜 임베더(#257).

soc.store.Embedder와 같은 모양이지만 모델을 내려받지 않는다. 실행마다 값이 달라지는 Python
hash()를 쓰지 않고 hashlib로 만들어, 같은 문장은 언제나 같은 벡터가 된다.
"""

import hashlib

# 작은 차원. 실제 모델(1024)과 달라야 컬렉션 차원을 임베더에서 받아 쓰는지 드러난다.
DIMENSION = 8


class FakeEmbedder:
    """문장을 SHA-256으로 접어 작은 차원의 L2 정규화 벡터를 만든다."""

    def __init__(self, dimension: int = DIMENSION) -> None:
        """인자 dimension은 1 이상이어야 한다."""
        if dimension < 1:
            raise ValueError("dimension은 1 이상이어야 한다")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        """같은 문장에 언제나 같은 벡터를 돌려준다. L2 norm은 1이다."""
        values = []
        block = 0
        while len(values) < self._dimension:
            digest = hashlib.sha256(f"{block}\0{text}".encode()).digest()
            # 바이트를 -1~1 사이 값으로 옮긴다.
            values.extend((byte - 127.5) / 127.5 for byte in digest)
            block += 1
        values = values[: self._dimension]
        norm = sum(value * value for value in values) ** 0.5
        if norm == 0.0:
            # 모든 바이트가 127 또는 128이어야 생기는데, 그래도 영벡터는 돌려주지 않는다.
            values[0] = 1.0
            norm = 1.0
        return [value / norm for value in values]
