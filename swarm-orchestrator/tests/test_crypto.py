"""Tests for federation/crypto.py."""

from __future__ import annotations

import base64
import os
import tempfile

import pytest
from nacl.public import PrivateKey

from orchestrator.federation.crypto import (
    decrypt_from_node,
    encrypt_for_nodes,
    generate_keypair,
    load_or_create_keypair,
)


class TestKeygen:
    def test_generate_keypair_returns_valid_keys(self):
        priv, pub = generate_keypair()
        assert isinstance(priv, PrivateKey)
        assert len(bytes(priv)) == 32
        assert len(bytes(pub)) == 32

    def test_generated_keypairs_are_unique(self):
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()
        assert bytes(priv1) != bytes(priv2)
        assert bytes(pub1) != bytes(pub2)

    def test_load_or_create_generates_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            priv_path = os.path.join(tmp, "node.key")
            pub_path = os.path.join(tmp, "node.pub")
            priv, pub = load_or_create_keypair(priv_path, pub_path)
            assert os.path.exists(priv_path)
            assert os.path.exists(pub_path)
            assert isinstance(priv, PrivateKey)

    def test_load_or_create_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            priv_path = os.path.join(tmp, "node.key")
            pub_path = os.path.join(tmp, "node.pub")
            priv1, pub1 = load_or_create_keypair(priv_path, pub_path)
            priv2, pub2 = load_or_create_keypair(priv_path, pub_path)
            assert bytes(priv1) == bytes(priv2)
            assert bytes(pub1) == bytes(pub2)


class TestEncryptDecrypt:
    def test_encrypt_decrypt_round_trip(self):
        priv, pub = generate_keypair()
        plaintext = b"Hello, swarm!"
        pub_bytes = bytes(pub)

        encrypted = encrypt_for_nodes(plaintext, {"node-a": pub_bytes})
        assert "node-a" in encrypted

        ciphertext = base64.b64decode(encrypted["node-a"])
        recovered = decrypt_from_node(ciphertext, priv)
        assert recovered == plaintext

    def test_multi_recipient_encryption(self):
        priv_a, pub_a = generate_keypair()
        priv_b, pub_b = generate_keypair()
        plaintext = b"Multi-recipient test"

        encrypted = encrypt_for_nodes(
            plaintext,
            {
                "node-a": bytes(pub_a),
                "node-b": bytes(pub_b),
            },
        )
        assert "node-a" in encrypted
        assert "node-b" in encrypted

        ct_a = base64.b64decode(encrypted["node-a"])
        ct_b = base64.b64decode(encrypted["node-b"])

        assert decrypt_from_node(ct_a, priv_a) == plaintext
        assert decrypt_from_node(ct_b, priv_b) == plaintext

    def test_wrong_key_cannot_decrypt(self):
        _, pub = generate_keypair()
        wrong_priv, _ = generate_keypair()
        plaintext = b"Secret"

        encrypted = encrypt_for_nodes(plaintext, {"node-x": bytes(pub)})
        ciphertext = base64.b64decode(encrypted["node-x"])

        from nacl.exceptions import CryptoError

        with pytest.raises(CryptoError):
            decrypt_from_node(ciphertext, wrong_priv)

    def test_empty_recipients(self):
        plaintext = b"test"
        result = encrypt_for_nodes(plaintext, {})
        assert result == {}
