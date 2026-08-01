"""
Lambda handler for Module 6 (Bonus): Voice-driven report generation.

Accepts audio file, transcribes it, extracts user intent via LLM,
then triggers the standard report generation pipeline with
customized parameters.
"""

import logging
import traceback
import uuid
from typing import Any

from src.shared.config import get_settings
from src.shared.s3_utils import upload_file, get_artifact_key
from src.shared.rate_limiter import get_rate_limiter
from src.modules.voice_agent.transcribe_client import TranscribeClient
from src.modules.ai_insight.bedrock_client import get_bedrock_client

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

INTENT_EXTRACTION_PROMPT = """你是一位報告生成助手。使用者透過語音描述了他想要的信用卡業務分析報告需求。

請從以下語音轉錄文字中提取使用者的意圖：

語音內容：
{transcript}

請輸出 JSON 格式：
{{
  "focus_areas": ["使用者關注的特定分析面向，如「分期業務市占率」、「各銀行呆帳率比較」等"],
  "specific_banks": ["使用者特別提到的銀行名稱，如沒有則為空陣列"],
  "time_range": "使用者指定的時間範圍，如「全年」或「Q3-Q4」，沒有則為 null",
  "chart_preferences": ["使用者偏好的圖表類型，沒有則為空陣列"],
  "custom_prompt_override": "根據使用者需求，自動生成用於覆寫 Module 2 Stage B 的客製化指示"
}}
"""


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for voice-driven report generation.

    Input event (from API):
    {
        "task_id": "abc-123",
        "audio_s3_key": "uploads/abc-123/voice_command.wav",
        "data_source_key": "sample_data/credit_card_stats_2025.xlsx",
        "template_name": "default",
        "recipients": ["user@example.com"],
        "media_format": "wav",
        "language_code": "zh-TW"
    }

    Output:
    {
        "task_id": "abc-123",
        "transcript": "幫我看各銀行分期業務的市占率變化...",
        "extracted_intent": {...},
        "pipeline_input": {...}  # Ready to feed into Step Functions
    }
    """
    settings = get_settings()

    if not settings.enable_voice_agent:
        return {"error": "Voice agent feature is disabled"}

    task_id = event.get("task_id", str(uuid.uuid4()))
    audio_key = event["audio_s3_key"]
    media_format = event.get("media_format", "wav")
    language_code = event.get("language_code", "zh-TW")

    logger.info(f"[{task_id}] Voice agent: processing {audio_key}")

    try:
        # Step 1: Transcribe audio
        transcribe = TranscribeClient()
        transcript = transcribe.transcribe_audio(
            audio_s3_key=audio_key,
            language_code=language_code,
            media_format=media_format,
        )

        logger.info(f"[{task_id}] Transcription complete: {len(transcript)} chars")

        # Save transcript artifact
        transcript_key = get_artifact_key(task_id, "voice_transcript.txt")
        upload_file(
            transcript.encode("utf-8"),
            transcript_key,
            content_type="text/plain",
        )

        # Step 2: Extract intent using LLM
        bedrock = get_bedrock_client()
        intent_prompt = INTENT_EXTRACTION_PROMPT.format(transcript=transcript)

        intent_response = bedrock.converse(
            system_prompt="你是一位意圖提取助手，只輸出 JSON 格式。",
            user_message=intent_prompt,
            max_tokens=1024,
            temperature=0.2,
        )

        # Parse intent JSON
        import json
        try:
            # Try to extract JSON from response
            json_start = intent_response.find("{")
            json_end = intent_response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                extracted_intent = json.loads(intent_response[json_start:json_end])
            else:
                extracted_intent = {"raw_response": intent_response}
        except json.JSONDecodeError:
            extracted_intent = {"raw_response": intent_response}

        logger.info(f"[{task_id}] Intent extracted: {extracted_intent.get('focus_areas', [])}")

        # Step 3: Build pipeline input with custom overrides
        pipeline_input = {
            "task_id": task_id,
            "data_source_key": event.get("data_source_key", ""),
            "template_name": event.get("template_name", "default"),
            "recipients": event.get("recipients", []),
            "options": {
                "include_executive_summary": True,
                "chart_style": "professional",
                "language": "zh-TW",
            },
            "voice_override": {
                "transcript": transcript,
                "focus_areas": extracted_intent.get("focus_areas", []),
                "specific_banks": extracted_intent.get("specific_banks", []),
                "custom_prompt": extracted_intent.get("custom_prompt_override", ""),
            },
            "retryCount": 0,
        }

        return {
            "task_id": task_id,
            "transcript": transcript,
            "extracted_intent": extracted_intent,
            "pipeline_input": pipeline_input,
        }

    except Exception as e:
        logger.error(f"[{task_id}] Voice agent error: {traceback.format_exc()}")
        raise
