"""
File upload API routes.

Generates S3 presigned URLs for direct browser-to-S3 uploads.
Endpoints:
- POST /api/v1/upload/presigned-url — Get a presigned URL for uploading
"""

import logging
import uuid
from typing import Literal

import boto3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.shared.config import get_settings
from src.api.middleware.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/upload", tags=["upload"])


class PresignedUrlRequest(BaseModel):
    """Request for generating an upload presigned URL."""
    filename: str = Field(..., description="Original filename (e.g., data.xlsx)")
    file_type: Literal["data", "template"] = Field(..., description="'data' for Excel, 'template' for PPTX")
    content_type: str = Field("application/octet-stream", description="MIME type")


class PresignedUrlResponse(BaseModel):
    """Response with presigned URL for upload."""
    upload_url: str
    s3_key: str
    expires_in: int = 3600


@router.post("/presigned-url", response_model=PresignedUrlResponse)
async def get_upload_url(
    request: PresignedUrlRequest,
    user: dict = Depends(get_current_user),
):
    """
    Generate a presigned URL for direct file upload to S3.

    The frontend uses this URL to upload files directly to S3
    without passing through the Lambda (avoids payload size limits).
    """
    settings = get_settings()
    s3 = boto3.client("s3", region_name=settings.aws_region)

    # Generate unique key based on file type
    file_id = str(uuid.uuid4())[:8]
    safe_filename = request.filename.replace(" ", "_")

    if request.file_type == "data":
        s3_key = f"uploads/data/{file_id}_{safe_filename}"
    elif request.file_type == "template":
        s3_key = f"uploads/templates/{file_id}_{safe_filename}"
    else:
        raise HTTPException(status_code=400, detail="Invalid file_type")

    try:
        upload_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.s3_bucket_name,
                "Key": s3_key,
                "ContentType": request.content_type,
            },
            ExpiresIn=3600,
        )

        logger.info(f"Generated presigned URL for {s3_key}")

        return PresignedUrlResponse(
            upload_url=upload_url,
            s3_key=s3_key,
            expires_in=3600,
        )
    except Exception as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate upload URL")
