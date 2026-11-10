"""비밀번호 해시(Argon2id, D-047). 라이브러리 기본 파라미터를 쓴다."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 12
MAX_LENGTH = 128  # 아주 긴 입력으로 해시 계산을 늘리지 못하게 한다

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


# 없는 아이디도 같은 해시 계산을 하게 해 응답 시간 차이를 줄인다
DUMMY_HASH = hash_password(secrets.token_urlsafe(24))
