"""
Report generation API routes.

Endpoints:
- POST /api/v1/reports          — Trigger report generation
- GET  /api/v1/reports/{task_id} — Query task status & download links
- DELETE /api/v1/reports/{task_id} — Cancel task
"""

import logging
import uuid
from typing import Any

import boto3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.shared.config import get_settings
from src.shared.s3_utils import generate_presigned_url
from src.api.middleware.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


# === Request/Response Models ===


class ReportOptions(BaseModel):
    """Options for report generation."""
    include_executive_summary: bool = True
    chart_style: str = "professional"
    language: str = "zh-TW"


class CreateReportRequest(BaseModel):
    """Request body for creating a new report."""
    data_source: str = Field(..., description="S3 key of the primary Excel data file")
    data_sources: list[str] = Field(default_factory=list, description="S3 keys of all Excel data files (for multi-file analysis)")
    template: str = Field("default", description="Template name to use")
    recipients: list[str] = Field(default_factory=list, description="Email recipients")
    options: ReportOptions = Field(default_factory=ReportOptions)


class CreateReportResponse(BaseModel):
    """Response after triggering report generation."""
    task_id: str
    status: str = "processing"
    message: str = "報告生成已啟動"


class TaskStatusResponse(BaseModel):
    """Response for task status query."""
    task_id: str
    status: str
    progress: int = 0
    duration_seconds: float | None = None
    outputs: dict[str, Any] | None = None
    quality_score: dict[str, Any] | None = None
    error: str | None = None


# === Endpoints ===


@router.post("", response_model=CreateReportResponse)
async def create_report(
    request: CreateReportRequest,
    user: dict = Depends(get_current_user),
):
    """
    Trigger a new report generation workflow.

    Starts the Step Functions state machine with the provided parameters.
    Returns immediately with a task_id for tracking progress.
    """
    settings = get_settings()
    task_id = str(uuid.uuid4())

    logger.info(f"Creating report task {task_id} for user {user.get('sub')}")

    # Prepare Step Functions input
    sf_input = {
        "task_id": task_id,
        "data_source_key": request.data_source,
        "data_source_keys": request.data_sources if request.data_sources else [request.data_source],
        "template_name": request.template,
        "recipients": request.recipients,
        "options": request.options.model_dump(),
        "user_id": user.get("sub", "anonymous"),
        "retryCount": 0,
    }

    # Start Step Functions execution
    if settings.state_machine_arn:
        try:
            sfn_client = boto3.client("stepfunctions", region_name=settings.aws_region)
            sfn_client.start_execution(
                stateMachineArn=settings.state_machine_arn,
                name=f"report-{task_id}",
                input=__import__("json").dumps(sf_input),
            )
        except Exception as e:
            logger.error(f"Failed to start Step Functions: {e}")
            raise HTTPException(status_code=500, detail="Failed to start report generation")
    else:
        logger.warning("STATE_MACHINE_ARN not configured, task created but not executed")

    return CreateReportResponse(
        task_id=task_id,
        status="processing",
        message="報告生成已啟動，可透過 WebSocket 或 GET 端點追蹤進度",
    )


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_report_status(
    task_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Query the status of a report generation task.

    Returns current progress, and download links when complete.
    """
    settings = get_settings()

    if not settings.state_machine_arn:
        return TaskStatusResponse(
            task_id=task_id,
            status="unknown",
            error="Step Functions not configured",
        )

    try:
        sfn_client = boto3.client("stepfunctions", region_name=settings.aws_region)

        # List executions matching this task
        response = sfn_client.list_executions(
            stateMachineArn=settings.state_machine_arn,
            statusFilter="RUNNING",
        )

        # Find our execution
        execution_arn = None
        for execution in response.get("executions", []):
            if task_id in execution["name"]:
                execution_arn = execution["executionArn"]
                break

        if execution_arn:
            return TaskStatusResponse(
                task_id=task_id,
                status="processing",
                progress=50,
            )

        # Check if completed
        response = sfn_client.list_executions(
            stateMachineArn=settings.state_machine_arn,
            statusFilter="SUCCEEDED",
        )

        for execution in response.get("executions", []):
            if task_id in execution["name"]:
                # Get output
                desc = sfn_client.describe_execution(
                    executionArn=execution["executionArn"]
                )
                import json

                output = json.loads(desc.get("output", "{}"))

                pptx_key = output.get("pptx_key", "")
                xlsx_key = output.get("xlsx_key", "")

                outputs = {}
                if pptx_key:
                    outputs["pptx_url"] = generate_presigned_url(pptx_key)
                elif output.get("pptx_url"):
                    outputs["pptx_url"] = output["pptx_url"]

                if xlsx_key:
                    outputs["xlsx_url"] = generate_presigned_url(xlsx_key)
                elif output.get("xlsx_url"):
                    outputs["xlsx_url"] = output["xlsx_url"]

                outputs["email_sent"] = output.get("email_sent", False)

                start_time = execution.get("startDate")
                stop_time = execution.get("stopDate")
                duration = None
                if start_time and stop_time:
                    duration = (stop_time - start_time).total_seconds()

                return TaskStatusResponse(
                    task_id=task_id,
                    status="completed",
                    progress=100,
                    duration_seconds=duration,
                    outputs=outputs,
                    quality_score=output.get("quality"),
                )

        # Check failed
        response = sfn_client.list_executions(
            stateMachineArn=settings.state_machine_arn,
            statusFilter="FAILED",
        )
        for execution in response.get("executions", []):
            if task_id in execution["name"]:
                return TaskStatusResponse(
                    task_id=task_id,
                    status="failed",
                    error="Report generation failed",
                )

        return TaskStatusResponse(task_id=task_id, status="not_found")

    except Exception as e:
        logger.error(f"Status query failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to query task status")


@router.delete("/{task_id}")
async def cancel_report(
    task_id: str,
    user: dict = Depends(get_current_user),
):
    """Cancel a running report generation task."""
    settings = get_settings()

    if not settings.state_machine_arn:
        raise HTTPException(status_code=503, detail="Step Functions not configured")

    try:
        sfn_client = boto3.client("stepfunctions", region_name=settings.aws_region)

        response = sfn_client.list_executions(
            stateMachineArn=settings.state_machine_arn,
            statusFilter="RUNNING",
        )

        for execution in response.get("executions", []):
            if task_id in execution["name"]:
                sfn_client.stop_execution(
                    executionArn=execution["executionArn"],
                    cause="Cancelled by user",
                )
                return {"task_id": task_id, "status": "cancelled"}

        raise HTTPException(status_code=404, detail="Running task not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cancel failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel task")
