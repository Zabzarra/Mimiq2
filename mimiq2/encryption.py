"""Excerpt of mimiq2/encryption.py for security review — only the code shown here."""

import base64
import os
from typing import Optional
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from config import MASTER_KEY_HEX


_MASTER_KEY: bytes = bytes.fromhex(MASTER_KEY_HEX)


_SALT_CACHE: dict[int, bytes] = {}


async def preload_enc_salt(user_id: int) -> None:
    """Ensure the per-user AES salt is cached."""
    if user_id in _SALT_CACHE:
        return
    import database as _db
    salt = await _db.get_enc_salt(user_id)
    if salt is None:
        salt = await _db.get_or_create_enc_salt(user_id, os.urandom(16))
    _SALT_CACHE[user_id] = salt


def _derive_key(user_id: int, salt: Optional[bytes]=None) -> bytes:
    """Derive a 256-bit AES key for user_id."""
    return HKDF(algorithm=SHA256(), length=32, salt=salt, info=f'uid:{user_id}'.encode()).derive(_MASTER_KEY)


def _get_or_create_salt(user_id: int) -> bytes:
    """Return per-user salt from the in-memory cache."""
    salt = _SALT_CACHE.get(user_id)
    if salt is None:
        raise RuntimeError(f'Encryption salt for user {user_id} not loaded. Await encryption.preload_enc_salt(user_id) before calling encrypt/decrypt.')
    return salt


def encrypt(plaintext: str, user_id: int) -> str:
    """Encrypt *plaintext* and return a base64 string safe for DB storage."""
    aad = str(user_id).encode()
    nonce = os.urandom(12)
    salt = _get_or_create_salt(user_id)
    aesgcm = AESGCM(_derive_key(user_id, salt))
    ct = aesgcm.encrypt(nonce, plaintext.encode(), aad)
    return base64.b64encode(nonce + ct).decode()


def decrypt(blob_b64: str, user_id: int) -> str:
    """Decrypt a base64 blob."""
    try:
        blob = base64.b64decode(blob_b64)
    except Exception:
        raise ValueError('Invalid base64 ciphertext blob')
    if len(blob) < 28:
        raise ValueError('Ciphertext blob too short')
    aad = str(user_id).encode()
    nonce, ciphertext = (blob[:12], blob[12:])
    salt = _SALT_CACHE.get(user_id)
    if salt is not None:
        try:
            pt = AESGCM(_derive_key(user_id, salt)).decrypt(nonce, ciphertext, aad)
            return pt.decode('utf-8')
        except (InvalidTag, ValueError):
            pass
        except UnicodeDecodeError:
            raise ValueError('Decrypted data is not valid UTF-8')
    try:
        pt = AESGCM(_derive_key(user_id, None)).decrypt(nonce, ciphertext, aad)
        return pt.decode('utf-8')
    except (InvalidTag, ValueError):
        pass
    except UnicodeDecodeError:
        raise ValueError('Decrypted data is not valid UTF-8')
    try:
        pt = AESGCM(_MASTER_KEY).decrypt(nonce, ciphertext, aad)
        return pt.decode('utf-8')
    except (InvalidTag, ValueError):
        raise ValueError('Decryption failed — wrong key or corrupted data')
    except UnicodeDecodeError:
        raise ValueError('Decrypted data is not valid UTF-8')
