"""
Amazon Bedrock client wrapper with rate limiting and structured output.

Handles:
- Rate limiting (competition requirement: < 1 RPS)
- Retry with exponential backoff
- Structured JSON output via tool_use
- Error handling for throttling
"""

import json
import logging
import time
from typing import Any, Type

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, ValidationError

from src.shared.config import get_settings
from src.shared.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)


class BedrockClientError(Exception):
    """Raised when Bedrock API call fails after retries."""
    pass


class BedrockClient:
    """
    Wrapper around Bedrock Converse API with rate limiting.

    Features:
    - Automatic rate limiting (< 1 RPS per competition rules)
    - Exponential backoff retry for throttling
    - Structured output via tool_use mode
    - Pydantic model validation of responses
    """

    def __init__(self):
        settings = get_settings()
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=settings.bedrock_region,
        )
        self._model_id = settings.bedrock_model_id
        self._rate_limiter = get_rate_limiter()
        self._max_retries = 3
        self._backoff_base = 2

    def converse(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        """
        Send a message to Bedrock and get text response.

        Args:
            system_prompt: System role prompt
            user_message: User message content
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            Text response from the model
        """
        messages = [{"role": "user", "content": [{"text": user_message}]}]

        for attempt in range(self._max_retries):
            try:
                # Rate limit enforcement
                self._rate_limiter.wait()

                response = self._client.converse(
                    modelId=self._model_id,
                    system=[{"text": system_prompt}],
                    messages=messages,
                    inferenceConfig={
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                )

                # Extract text from response
                output = response["output"]["message"]["content"]
                text_parts = [block["text"] for block in output if "text" in block]
                return "\n".join(text_parts)

            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code in ("ThrottlingException", "TooManyRequestsException"):
                    wait_time = self._backoff_base ** (attempt + 1)
                    logger.warning(
                        f"Bedrock throttled (attempt {attempt + 1}/{self._max_retries}), "
                        f"waiting {wait_time}s"
                    )
                    time.sleep(wait_time)
                else:
                    raise BedrockClientError(
                        f"Bedrock API error: {error_code} - {e.response['Error']['Message']}"
                    )

        raise BedrockClientError(
            f"Bedrock call failed after {self._max_retries} retries"
        )

    def converse_structured(
        self,
        system_prompt: str,
        user_message: str,
        output_model: Type[BaseModel],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> BaseModel:
        """
        Send a message and parse response into a Pydantic model.

        Uses tool_use to force structured JSON output from the model.

        Args:
            system_prompt: System role prompt
            user_message: User message content
            output_model: Pydantic model class for response validation
            max_tokens: Maximum tokens
            temperature: Sampling temperature

        Returns:
            Validated Pydantic model instance
        """
        # Build tool definition from Pydantic schema
        schema = output_model.model_json_schema()
        tool_name = f"output_{output_model.__name__.lower()}"

        tool_config = {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool_name,
                        "description": f"Output structured data as {output_model.__name__}",
                        "inputSchema": {"json": schema},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": tool_name}},
        }

        messages = [{"role": "user", "content": [{"text": user_message}]}]

        for attempt in range(self._max_retries):
            try:
                # Rate limit enforcement
                self._rate_limiter.wait()

                response = self._client.converse(
                    modelId=self._model_id,
                    system=[{"text": system_prompt}],
                    messages=messages,
                    inferenceConfig={
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                    toolConfig=tool_config,
                )

                # Extract tool use result
                output = response["output"]["message"]["content"]
                for block in output:
                    if "toolUse" in block:
                        tool_input = block["toolUse"]["input"]
                        # Validate against Pydantic model
                        return output_model.model_validate(tool_input)

                # Fallback: try to parse text as JSON
                for block in output:
                    if "text" in block:
                        data = json.loads(block["text"])
                        return output_model.model_validate(data)

                raise BedrockClientError("No structured output found in response")

            except ValidationError as e:
                logger.warning(
                    f"Response validation failed (attempt {attempt + 1}): {e}"
                )
                if attempt == self._max_retries - 1:
                    raise BedrockClientError(
                        f"Response validation failed after {self._max_retries} attempts: {e}"
                    )
                # Retry with slightly higher temperature
                temperature = min(temperature + 0.1, 1.0)

            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code in ("ThrottlingException", "TooManyRequestsException"):
                    wait_time = self._backoff_base ** (attempt + 1)
                    logger.warning(f"Bedrock throttled, waiting {wait_time}s")
                    time.sleep(wait_time)
                else:
                    raise BedrockClientError(
                        f"Bedrock API error: {error_code} - {e.response['Error']['Message']}"
                    )

            except json.JSONDecodeError as e:
                logger.warning(f"JSON decode failed (attempt {attempt + 1}): {e}")
                if attempt == self._max_retries - 1:
                    raise BedrockClientError(f"Failed to parse JSON response: {e}")

        raise BedrockClientError("Structured call failed after all retries")


# Module-level singleton
_client: BedrockClient | None = None


def get_bedrock_client() -> BedrockClient:
    """Get the global BedrockClient singleton."""
    global _client
    if _client is None:
        _client = BedrockClient()
    return _client
