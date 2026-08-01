"""
Lambda handler for Module 4: Quality Assurance Gate.

Downloads generated PPTX and Excel from S3, runs quality checks,
and returns pass/fail to Step Functions for routing.
"""

import logging
import traceback
from typing import Any

from src.shared.s3_utils import download_file, download_json, upload_json, get_artifact_key
from src.shared.websocket_notifier import notify_progress
from src.modules.ai_insight.models import PresentationPlan
from src.modules.quality_checker.checks import run_all_checks

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for quality checking.

    Input event:
    {
        "task_id": "abc-123",
        "pptx_key": "tasks/abc-123/output/report.pptx",
        "xlsx_key": "tasks/abc-123/output/report_data.xlsx",
        "presentation_plan_key": "tasks/abc-123/artifacts/presentation_plan.json",
        "retryCount": 0
    }

    Output:
    {
        "task_id": "abc-123",
        "quality": {"passed": true, "total_checks": 10, ...},
        "pptx_key": "...",
        "xlsx_key": "...",
        "retryCount": 0
    }
    """
    task_id = event["task_id"]
    pptx_key = event["pptx_key"]
    xlsx_key = event["xlsx_key"]
    plan_key = event["presentation_plan_key"]
    retry_count = event.get("retryCount", 0)

    logger.info(f"[{task_id}] Starting quality checks (retry={retry_count})")

    notify_progress(
        task_id=task_id,
        step="QualityCheck",
        status="in_progress",
        progress=92,
        message="正在進行品質檢驗...",
    )

    try:
        # Download files
        pptx_bytes = download_file(pptx_key)
        xlsx_bytes = download_file(xlsx_key)
        plan_data = download_json(plan_key)
        plan = PresentationPlan.model_validate(plan_data)

        # Run checks
        result = run_all_checks(pptx_bytes, xlsx_bytes, plan)

        # Save QA report
        qa_key = get_artifact_key(task_id, "quality_report.json")
        upload_json(result.model_dump(), qa_key)

        # Notify result
        if result.passed:
            notify_progress(
                task_id=task_id,
                step="QualityCheck",
                status="completed",
                progress=95,
                message=f"品質檢驗通過（{result.passed_checks}/{result.total_checks} 項通過）",
            )
        else:
            failed_items = [c.message for c in result.checks if c.status == "fail"]
            notify_progress(
                task_id=task_id,
                step="QualityCheck",
                status="failed",
                progress=92,
                message=f"品質檢驗未通過：{'; '.join(failed_items[:3])}",
            )

        return {
            "task_id": task_id,
            "quality": result.model_dump(),
            "pptx_key": pptx_key,
            "xlsx_key": xlsx_key,
            "presentation_plan_key": plan_key,
            "retryCount": retry_count,
        }

    except Exception as e:
        logger.error(f"[{task_id}] Quality check error: {traceback.format_exc()}")
        notify_progress(
            task_id=task_id,
            step="QualityCheck",
            status="failed",
            progress=0,
            message=f"品質檢驗失敗：{str(e)}",
        )
        raise
