"""
Amazon Transcribe client for voice-to-text conversion.

Handles audio file transcription using Amazon Transcribe async API.
"""

import logging
import time
import uuid

import boto3
from botocore.exceptions import ClientError

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class TranscribeClient:
    """
    Amazon Transcribe wrapper for converting audio to text.

    Supports async transcription jobs with polling for completion.
    """

    def __init__(self):
        settings = get_settings()
        self._client = boto3.client("transcribe", region_name=settings.aws_region)
        self._s3_bucket = settings.s3_bucket_name

    def transcribe_audio(
        self,
        audio_s3_key: str,
        language_code: str = "zh-TW",
        media_format: str = "wav",
    ) -> str:
        """
        Transcribe an audio file from S3.

        Args:
            audio_s3_key: S3 key of the audio file
            language_code: Language code (default: zh-TW for Traditional Chinese)
            media_format: Audio format (wav, mp3, mp4, flac)

        Returns:
            Transcribed text string
        """
        job_name = f"voice-report-{uuid.uuid4().hex[:8]}"
        media_uri = f"s3://{self._s3_bucket}/{audio_s3_key}"

        logger.info(f"Starting transcription job: {job_name}")

        try:
            self._client.start_transcription_job(
                TranscriptionJobName=job_name,
                Media={"MediaFileUri": media_uri},
                MediaFormat=media_format,
                LanguageCode=language_code,
                OutputBucketName=self._s3_bucket,
                OutputKey=f"transcriptions/{job_name}.json",
                Settings={
                    "ShowPunctuationInTranscript": True,
                },
            )

            # Poll for completion
            transcript_text = self._wait_for_completion(job_name)
            return transcript_text

        except ClientError as e:
            logger.error(f"Transcribe error: {e}")
            raise

    def _wait_for_completion(self, job_name: str, max_wait: int = 300) -> str:
        """
        Poll transcription job until complete.

        Args:
            job_name: Transcription job name
            max_wait: Maximum wait time in seconds

        Returns:
            Transcribed text
        """
        elapsed = 0
        poll_interval = 5

        while elapsed < max_wait:
            response = self._client.get_transcription_job(
                TranscriptionJobName=job_name
            )
            status = response["TranscriptionJob"]["TranscriptionJobStatus"]

            if status == "COMPLETED":
                # Get transcript from results
                transcript_uri = response["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
                return self._download_transcript(transcript_uri)

            elif status == "FAILED":
                reason = response["TranscriptionJob"].get("FailureReason", "Unknown")
                raise RuntimeError(f"Transcription failed: {reason}")

            time.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"Transcription timed out after {max_wait}s")

    def _download_transcript(self, uri: str) -> str:
        """Download and parse transcript JSON from S3 or URL."""
        import json
        import httpx

        # Transcribe returns a presigned URL
        response = httpx.get(uri, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Extract full transcript text
        transcripts = data.get("results", {}).get("transcripts", [])
        if transcripts:
            return transcripts[0].get("transcript", "")
        return ""
