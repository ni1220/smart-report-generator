"""
Lambda handler for Module 3: Report Generation.

Replaces ECS Fargate for simpler deployment. Generates PPTX and Excel
with native charts, then uploads to S3.
"""

import json
import logging
import traceback
from typing import Any

from src.shared.config import get_settings
from src.shared.s3_utils import download_json, upload_file, get_output_key
from src.shared.websocket_notifier import notify_progress
from src.modules.ai_insight.models import PresentationPlan
from src.modules.report_generator.pptx_engine import PptxGenerator
from src.modules.report_generator.xlsx_engine import ExcelGenerator

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for report generation.

    Input event (from Step Functions / AIInsightGeneration output):
    {
        "task_id": "abc-123",
        "presentation_plan_key": "tasks/abc-123/artifacts/presentation_plan.json",
        ...
    }

    Output:
    {
        "task_id": "abc-123",
        "pptx_key": "tasks/abc-123/output/report.pptx",
        "xlsx_key": "tasks/abc-123/output/report_data.xlsx",
        "presentation_plan_key": "tasks/abc-123/artifacts/presentation_plan.json",
        "pptx_size_bytes": 12345,
        "xlsx_size_bytes": 6789
    }
    """
    task_id = event["task_id"]
    plan_key = event["presentation_plan_key"]
    template_name = event.get("template_name", "default")

    logger.info(f"[{task_id}] Starting report generation (Lambda), template={template_name}")

    notify_progress(
        task_id=task_id,
        step="ReportGeneration",
        status="in_progress",
        progress=72,
        message="正在生成簡報與 Excel...",
    )

    try:
        # 1. Load presentation plan
        plan_data = download_json(plan_key)
        plan = PresentationPlan.model_validate(plan_data)
        logger.info(f"[{task_id}] Loaded plan: {len(plan.slides)} slides")

        # 2. Load template (user-uploaded or from registry)
        template_bytes = None
        if template_name and template_name != "default":
            # User uploaded a custom template (S3 key like "uploads/templates/...")
            try:
                from src.shared.s3_utils import download_file as dl_file
                template_bytes = dl_file(template_name)
                logger.info(f"[{task_id}] Loaded user template: {template_name} ({len(template_bytes)} bytes)")
            except Exception as e:
                logger.warning(f"[{task_id}] Failed to load user template '{template_name}': {e}, using blank")
                template_bytes = None
        else:
            # Try loading from template registry
            try:
                from src.modules.report_generator.template_loader import TemplateRegistry
                registry = TemplateRegistry()
                template_bytes = registry.get_template_bytes("default")
            except Exception as e:
                logger.warning(f"[{task_id}] Template registry unavailable: {e}")

        # 3. Generate PPTX
        notify_progress(
            task_id=task_id,
            step="ReportGeneration",
            status="in_progress",
            progress=75,
            message="正在渲染原生圖表簡報...",
        )

        pptx_gen = PptxGenerator(plan, template_bytes=template_bytes)
        pptx_bytes = pptx_gen.generate()
        logger.info(f"[{task_id}] PPTX generated: {len(pptx_bytes)} bytes")

        # 3. Generate Excel
        notify_progress(
            task_id=task_id,
            step="ReportGeneration",
            status="in_progress",
            progress=82,
            message="正在生成同步 Excel 資料檔...",
        )

        xlsx_gen = ExcelGenerator(plan)
        xlsx_bytes = xlsx_gen.generate()
        logger.info(f"[{task_id}] Excel generated: {len(xlsx_bytes)} bytes")

        # 4. Upload to S3
        notify_progress(
            task_id=task_id,
            step="ReportGeneration",
            status="in_progress",
            progress=88,
            message="正在上傳檔案...",
        )

        pptx_key = get_output_key(task_id, "report.pptx")
        xlsx_key = get_output_key(task_id, "report_data.xlsx")

        upload_file(
            pptx_bytes, pptx_key,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        upload_file(
            xlsx_bytes, xlsx_key,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        notify_progress(
            task_id=task_id,
            step="ReportGeneration",
            status="completed",
            progress=90,
            message="簡報與 Excel 生成完成",
        )

        result = {
            "task_id": task_id,
            "pptx_key": pptx_key,
            "xlsx_key": xlsx_key,
            "presentation_plan_key": plan_key,
            "pptx_size_bytes": len(pptx_bytes),
            "xlsx_size_bytes": len(xlsx_bytes),
        }

        logger.info(f"[{task_id}] Report generation complete: {result}")
        return result

    except Exception as e:
        logger.error(f"[{task_id}] Report generation error: {traceback.format_exc()}")
        notify_progress(
            task_id=task_id,
            step="ReportGeneration",
            status="failed",
            progress=0,
            message=f"簡報生成失敗：{str(e)}",
        )
        raise
