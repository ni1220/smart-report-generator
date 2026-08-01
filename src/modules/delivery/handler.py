"""
Lambda handler for Module 5: Report Delivery.

Downloads generated files from S3 and sends them via SES
to the specified recipients.
"""

import logging
import traceback
from typing import Any

from src.shared.config import get_settings
from src.shared.s3_utils import download_file, download_json, generate_presigned_url, get_artifact_key
from src.shared.websocket_notifier import notify_progress
from src.modules.ai_insight.models import PresentationPlan
from src.modules.delivery.ses_client import SesClient, build_report_email_html

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for email delivery.

    Input event:
    {
        "task_id": "abc-123",
        "pptx_key": "tasks/abc-123/output/report.pptx",
        "xlsx_key": "tasks/abc-123/output/report_data.xlsx",
        "presentation_plan_key": "tasks/abc-123/artifacts/presentation_plan.json",
        "recipients": ["user@example.com"],
        "quality": {"passed": true, ...}
    }

    Output:
    {
        "task_id": "abc-123",
        "email_sent": true,
        "message_id": "...",
        "pptx_url": "https://...",
        "xlsx_url": "https://..."
    }
    """
    task_id = event["task_id"]
    pptx_key = event["pptx_key"]
    xlsx_key = event["xlsx_key"]
    plan_key = event["presentation_plan_key"]
    recipients = event.get("recipients", [])
    quality = event.get("quality", {})

    logger.info(f"[{task_id}] Starting delivery to {len(recipients)} recipients")

    notify_progress(
        task_id=task_id,
        step="SendReport",
        status="in_progress",
        progress=96,
        message="正在寄送報告...",
    )

    try:
        # Generate presigned URLs (valid for 24 hours)
        pptx_url = generate_presigned_url(pptx_key, expiration=86400)
        xlsx_url = generate_presigned_url(xlsx_key, expiration=86400)

        # Load plan for summary
        plan_data = download_json(plan_key)
        plan = PresentationPlan.model_validate(plan_data)

        email_sent = False
        message_id = None

        if recipients:
            # Download files for attachment
            pptx_bytes = download_file(pptx_key)
            xlsx_bytes = download_file(xlsx_key)

            # Build email
            html_body = build_report_email_html(
                executive_summary=plan.executive_summary,
                slide_count=len(plan.slides),
                quality_passed=quality.get("passed", False),
                download_links={
                    "簡報下載 (PPTX)": pptx_url,
                    "數據下載 (Excel)": xlsx_url,
                },
            )

            # Send via SES
            ses = SesClient()
            result = ses.send_report_email(
                recipients=recipients,
                subject=f"[智匯簡報] 信用卡業務分析報告 — {plan.theme}",
                html_body=html_body,
                attachments=[
                    {
                        "filename": "信用卡業務分析報告.pptx",
                        "content_bytes": pptx_bytes,
                        "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    },
                    {
                        "filename": "信用卡業務數據.xlsx",
                        "content_bytes": xlsx_bytes,
                        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    },
                ],
            )

            email_sent = True
            message_id = result["message_id"]
            logger.info(f"[{task_id}] Email sent: {message_id}")

        # Notify completion
        notify_progress(
            task_id=task_id,
            step="SendReport",
            status="completed",
            progress=100,
            message="報告已成功寄出！",
        )

        return {
            "task_id": task_id,
            "email_sent": email_sent,
            "message_id": message_id,
            "recipients": recipients,
            "pptx_url": pptx_url,
            "xlsx_url": xlsx_url,
        }

    except Exception as e:
        logger.error(f"[{task_id}] Delivery error: {traceback.format_exc()}")
        notify_progress(
            task_id=task_id,
            step="SendReport",
            status="failed",
            progress=0,
            message=f"報告寄送失敗：{str(e)}",
        )
        raise
