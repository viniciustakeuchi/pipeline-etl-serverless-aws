"""Acesso ao S3. O endpoint é configurável para apontar para um S3 local em desenvolvimento."""

from typing import TYPE_CHECKING, Any

import boto3

from etl.config import Config

__all__ = ["S3Client", "cliente"]

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
else:
    S3Client = Any


def cliente(cfg: Config) -> S3Client:
    return boto3.client("s3", endpoint_url=cfg.s3_endpoint)
