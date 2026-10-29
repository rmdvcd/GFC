"""Argon2id and AES-256-GCM primitives for the shared backup format."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from argon2.exceptions import HashingError
from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16
DEFAULT_MEMORY_KIB = 65536
FALLBACK_MEMORY_KIB = 32768
ITERATIONS = 3
PARALLELISM = 4
KEY_BYTES = 32


@dataclass(frozen=True)
class DerivedKey:
    key: bytes
    memory_kib: int


def derive_key(password: str, salt: bytes, memory_kib: int = DEFAULT_MEMORY_KIB, *, allow_fallback: bool = True) -> DerivedKey:
    secret = unicodedata.normalize("NFC", password).encode("utf-8")
    def derive(memory: int) -> bytes:
        return hash_secret_raw(secret, salt, time_cost=ITERATIONS, memory_cost=memory,
            parallelism=PARALLELISM, hash_len=KEY_BYTES, type=Type.ID)
    try:
        return DerivedKey(derive(memory_kib), memory_kib)
    except (MemoryError, HashingError):
        if memory_kib != DEFAULT_MEMORY_KIB or not allow_fallback:
            raise
        return DerivedKey(derive(FALLBACK_MEMORY_KIB), FALLBACK_MEMORY_KIB)


def encrypt_aes_gcm(key: bytes, nonce: bytes, aad: bytes, plaintext: bytes) -> bytes:
    return AESGCM(key).encrypt(nonce, plaintext, aad)  # ciphertext || 16-byte tag


def decrypt_aes_gcm(key: bytes, nonce: bytes, aad: bytes, ciphertext_and_tag: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(nonce, ciphertext_and_tag, aad)
    except InvalidTag as exc:
        # GCM does not reveal whether the password or authenticated bytes were wrong.
        raise ValueError("BACKUP_AUTHENTICATION_FAILED") from exc
