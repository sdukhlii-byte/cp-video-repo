"""
story/storage.py — опциональная заливка кейфрейма в S3/R2.

Нужна ТОЛЬКО если видеопровайдер откажется принимать первый кадр как data:-URL.
Без настроенных S3_* переменных модуль не импортируется и не мешает.
"""

from __future__ import annotations

import logging
import mimetypes
import os

import config as C

log = logging.getLogger("storage")


def upload(path: str, key: str) -> str:
    if not C.STORAGE_ENABLED:
        raise RuntimeError("S3 не настроен (нужны S3_ENDPOINT_URL/S3_BUCKET/S3_ACCESS_KEY/S3_PUBLIC_BASE)")
    import boto3
    from botocore.config import Config as BotoConfig

    s3 = boto3.client(
        "s3",
        endpoint_url=C.S3_ENDPOINT_URL,
        aws_access_key_id=C.S3_ACCESS_KEY,
        aws_secret_access_key=C.S3_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4"),
    )
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        s3.put_object(Bucket=C.S3_BUCKET, Key=key, Body=f, ContentType=ctype)
    url = f"{C.S3_PUBLIC_BASE.rstrip('/')}/{key}"
    log.info("uploaded %s → %s", os.path.basename(path), url)
    return url
