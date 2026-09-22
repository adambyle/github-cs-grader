"""Encrypting secrets stored in the database (GitHub user tokens).

The key is TOKEN_ENCRYPTION_KEY, kept outside the database, so a copy of
the database alone cannot be used to act as anyone on GitHub.
"""

from __future__ import annotations

from cryptography.fernet import Fernet
from flask import current_app


def _fernet() -> Fernet:
    return Fernet(current_app.config["TOKEN_ENCRYPTION_KEY"])


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
