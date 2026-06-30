"""Server-side encryption tagging (CP3). The object store does the crypto; the app only tags writes.
Default (unset) sends NO SSE header — today's behavior. These pin the header-building per config."""

from __future__ import annotations

from app import storage


def test_sse_off_by_default(monkeypatch):
    monkeypatch.setattr(storage.settings, "s3_sse", "", raising=False)
    assert storage._sse_args() == {}  # no SSE header — inert


def test_sse_s3_aes256(monkeypatch):
    monkeypatch.setattr(storage.settings, "s3_sse", "AES256", raising=False)
    assert storage._sse_args() == {"ServerSideEncryption": "AES256"}


def test_sse_kms_with_key(monkeypatch):
    monkeypatch.setattr(storage.settings, "s3_sse", "aws:kms", raising=False)
    monkeypatch.setattr(storage.settings, "s3_sse_kms_key_id", "arn:aws:kms:...:key/abc", raising=False)
    assert storage._sse_args() == {
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": "arn:aws:kms:...:key/abc",
    }


def test_sse_kms_without_key_omits_key_id(monkeypatch):
    # aws:kms with no key id still tags KMS (the bucket's default KMS key applies); no empty SSEKMSKeyId.
    monkeypatch.setattr(storage.settings, "s3_sse", "aws:kms", raising=False)
    monkeypatch.setattr(storage.settings, "s3_sse_kms_key_id", "", raising=False)
    assert storage._sse_args() == {"ServerSideEncryption": "aws:kms"}
