"""
Application configuration management.
Loads settings from environment variables with sensible defaults.
"""

import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    """Application settings loaded from environment variables."""

    # AWS
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    aws_account_id: str = os.getenv("AWS_ACCOUNT_ID", "")

    # S3
    s3_bucket_name: str = os.getenv("S3_BUCKET_NAME", "smart-report-dev")
    s3_template_prefix: str = os.getenv("S3_TEMPLATE_PREFIX", "templates/")
    s3_artifacts_prefix: str = os.getenv("S3_ARTIFACTS_PREFIX", "tasks/")

    # Bedrock
    bedrock_model_id: str = os.getenv(
        "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
    )
    bedrock_region: str = os.getenv("BEDROCK_REGION", "us-east-1")
    bedrock_max_rps: float = float(os.getenv("BEDROCK_MAX_RPS", "0.9"))

    # SES
    ses_sender_email: str = os.getenv(
        "SES_SENDER_EMAIL", "noreply@smartreport.example.com"
    )

    # Cognito
    cognito_user_pool_id: str = os.getenv("COGNITO_USER_POOL_ID", "")
    cognito_client_id: str = os.getenv("COGNITO_CLIENT_ID", "")

    # WebSocket
    websocket_api_endpoint: str = os.getenv("WEBSOCKET_API_ENDPOINT", "")

    # DynamoDB
    dynamodb_connections_table: str = os.getenv(
        "DYNAMODB_CONNECTIONS_TABLE", "ws-connections"
    )
    dynamodb_prompts_table: str = os.getenv(
        "DYNAMODB_PROMPTS_TABLE", "prompt-versions"
    )

    # Feature Flags
    enable_voice_agent: bool = os.getenv("ENABLE_VOICE_AGENT", "false").lower() == "true"
    enable_rag: bool = os.getenv("ENABLE_RAG", "false").lower() == "true"

    # Step Functions
    state_machine_arn: str = os.getenv("STATE_MACHINE_ARN", "")

    # ECS
    ecs_cluster: str = os.getenv("ECS_CLUSTER", "")
    ecs_task_definition: str = os.getenv("ECS_TASK_DEFINITION", "")
    ecs_subnets: str = os.getenv("ECS_SUBNETS", "")
    ecs_security_group: str = os.getenv("ECS_SECURITY_GROUP", "")


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
