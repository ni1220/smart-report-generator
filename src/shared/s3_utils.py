"""
S3 utility functions for uploading, downloading, and generating presigned URLs.
All S3 operations use SSE-KMS encryption as required by competition rules.
"""

import json
import logging
from io import BytesIO
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


def get_s3_client():
    """Get S3 client for the configured region."""
    settings = get_settings()
    return boto3.client("s3", region_name=settings.aws_region)


def upload_json(data: dict | list, key: str, metadata: dict | None = None) -> str:
    """
    Upload JSON data to S3 with SSE-KMS encryption.

    Args:
        data: Python dict/list to serialize as JSON
        key: S3 object key
        metadata: Optional metadata dict

    Returns:
        S3 URI (s3://bucket/key)
    """
    settings = get_settings()
    s3 = get_s3_client()

    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")

    params = {
        "Bucket": settings.s3_bucket_name,
        "Key": key,
        "Body": body,
        "ContentType": "application/json",
        "ServerSideEncryption": "aws:kms",
    }
    if metadata:
        params["Metadata"] = {k: str(v) for k, v in metadata.items()}

    s3.put_object(**params)
    uri = f"s3://{settings.s3_bucket_name}/{key}"
    logger.info(f"Uploaded JSON to {uri}")
    return uri


def upload_file(file_bytes: bytes, key: str, content_type: str = "application/octet-stream") -> str:
    """
    Upload binary file to S3 with SSE-KMS encryption.

    Args:
        file_bytes: File content as bytes
        key: S3 object key
        content_type: MIME type

    Returns:
        S3 URI
    """
    settings = get_settings()
    s3 = get_s3_client()

    s3.put_object(
        Bucket=settings.s3_bucket_name,
        Key=key,
        Body=file_bytes,
        ContentType=content_type,
        ServerSideEncryption="aws:kms",
    )
    uri = f"s3://{settings.s3_bucket_name}/{key}"
    logger.info(f"Uploaded file to {uri}")
    return uri


def download_file(key: str) -> bytes:
    """
    Download file from S3.

    Args:
        key: S3 object key

    Returns:
        File content as bytes
    """
    settings = get_settings()
    s3 = get_s3_client()

    response = s3.get_object(Bucket=settings.s3_bucket_name, Key=key)
    return response["Body"].read()


def download_json(key: str) -> Any:
    """
    Download and parse JSON from S3.

    Args:
        key: S3 object key

    Returns:
        Parsed JSON data
    """
    content = download_file(key)
    return json.loads(content.decode("utf-8"))


def generate_presigned_url(key: str, expiration: int = 3600) -> str:
    """
    Generate a presigned URL for downloading an S3 object.
    Uses presigned URLs instead of public access (competition requirement).

    Args:
        key: S3 object key
        expiration: URL expiration in seconds (default 1 hour)

    Returns:
        Presigned URL string
    """
    settings = get_settings()
    s3 = get_s3_client()

    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_name, "Key": key},
            ExpiresIn=expiration,
        )
        return url
    except ClientError as e:
        logger.error(f"Failed to generate presigned URL for {key}: {e}")
        raise


def get_artifact_key(task_id: str, filename: str) -> str:
    """
    Generate the S3 key for a task artifact.

    Args:
        task_id: Unique task identifier
        filename: Artifact filename

    Returns:
        Full S3 key path
    """
    settings = get_settings()
    return f"{settings.s3_artifacts_prefix}{task_id}/artifacts/{filename}"


def get_output_key(task_id: str, filename: str) -> str:
    """
    Generate the S3 key for a task output file.

    Args:
        task_id: Unique task identifier
        filename: Output filename (e.g., report.pptx)

    Returns:
        Full S3 key path
    """
    settings = get_settings()
    return f"{settings.s3_artifacts_prefix}{task_id}/output/{filename}"
