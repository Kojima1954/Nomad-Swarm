"""Cryptography helpers using PyNaCl (libsodium X25519 / Curve25519)."""

from __future__ import annotations

import base64
from pathlib import Path

from nacl.public import PrivateKey, PublicKey, SealedBox


# ---------------------------------------------------------------------------
# Key generation & persistence
# ---------------------------------------------------------------------------

def generate_keypair() -> tuple[PrivateKey, PublicKey]:
    """Generate a new X25519 keypair."""
    private_key = PrivateKey.generate()
    return private_key, private_key.public_key


def load_or_create_keypair(
    private_path: str | Path, public_path: str | Path
) -> tuple[PrivateKey, PublicKey]:
    """Load an existing keypair from files, or generate and save a new one.

    Both files store raw 32-byte keys encoded as Base64.
    """
    priv_file = Path(private_path)
    pub_file = Path(public_path)

    if priv_file.exists() and pub_file.exists():
        priv_bytes = base64.b64decode(priv_file.read_bytes().strip())
        private_key = PrivateKey(priv_bytes)
        return private_key, private_key.public_key

    # Generate new keypair
    private_key, public_key = generate_keypair()

    # Ensure parent directories exist
    priv_file.parent.mkdir(parents=True, exist_ok=True)
    pub_file.parent.mkdir(parents=True, exist_ok=True)

    priv_file.write_bytes(base64.b64encode(bytes(private_key)))
    pub_file.write_bytes(base64.b64encode(bytes(public_key)))

    priv_file.chmod(0o600)
    pub_file.chmod(0o644)

    return private_key, public_key


# ---------------------------------------------------------------------------
# Encryption / Decryption
# ---------------------------------------------------------------------------

def encrypt_for_nodes(
    plaintext: bytes, recipient_public_keys: dict[str, bytes]
) -> dict[str, str]:
    """Encrypt *plaintext* for each recipient using SealedBox.

    Parameters
    ----------
    plaintext:
        The raw bytes to encrypt.
    recipient_public_keys:
        A mapping of ``{node_id: raw_32_byte_public_key}``.

    Returns
    -------
    dict[str, str]
        ``{node_id: base64_ciphertext}`` for each recipient.
    """
    result: dict[str, str] = {}
    for node_id, raw_pub in recipient_public_keys.items():
        pub_key = PublicKey(raw_pub)
        box = SealedBox(pub_key)
        ciphertext = box.encrypt(plaintext)
        result[node_id] = base64.b64encode(ciphertext).decode()
    return result


def decrypt_from_node(ciphertext: bytes, private_key: PrivateKey) -> bytes:
    """Decrypt *ciphertext* using *private_key*.

    Parameters
    ----------
    ciphertext:
        Raw (non-base64) ciphertext bytes.
    private_key:
        The recipient's X25519 private key.
    """
    box = SealedBox(private_key)
    return box.decrypt(ciphertext)
