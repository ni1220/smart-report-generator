"""
Main entry point for the Report Generator module (ECS Fargate task).

Orchestrates:
1. Download presentation plan from S3
2. Load template
3. Generate PPTX with native charts
4. Generate Excel with native charts
5. Upload both to S3
"""

import json
import logging
import os
import sys
import traceback

from src.shared.config import get_settings
from src.shared.s3_utils import download_json, upload_file, get_output_key
from src.shared.websocket_notifier import notify_progress
from src.modules.ai_insight.models import PresentationPlan
from src.modules.report_generator.pptx_engine import PptxGenerator
from src.modules.report_generator.xlsx_engine import ExcelGenerator
from src.modules.report_generator.template_loader import TemplateRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run(task_id: str, presentation_plan_key: str, template_name: str = "default"):
    """
    Main report generation function.

    Args:
        task_id: Unique task identifier
        presentation_plan_key: S3 key of the presentation plan JSON
        template_name: Template to use for PPTX generation
    """
    logger.info(f"[{task_id}] Starting report generation")

    notify_progress(
        task_id=task_id,
        step="ReportGeneration",
        status="in_progress",
        progress=72,
        message="正在生成簡報與 Excel...",
    )

    # 1. Load presentation plan
    plan_data = download_json(presentation_plan_key)
    plan = PresentationPlan.model_validate(plan_data)
    logger.info(f"[{task_id}] Loaded plan: {len(plan.slides)} slides")

    # 2. Load template
    template_registry = TemplateRegistry()
    template_bytes = template_registry.get_template_bytes(template_name)

    # 3. Generate PPTX
    notify_progress(
        task_id=task_id,
        step="ReportGeneration",
        status="in_progress",
        progress=75,
        message="正在渲染原生圖表簡報...",
    )

    pptx_gen = PptxGenerator(plan, template_bytes)
    pptx_bytes = pptx_gen.generate()
    logger.info(f"[{task_id}] PPTX generated: {len(pptx_bytes)} bytes")

    # 4. Generate Excel
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

    # 5. Upload to S3
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

    logger.info(f"[{task_id}] Report generation complete: {pptx_key}, {xlsx_key}")

    return {
        "task_id": task_id,
        "pptx_key": pptx_key,
        "xlsx_key": xlsx_key,
        "pptx_size_bytes": len(pptx_bytes),
        "xlsx_size_bytes": len(xlsx_bytes),
    }


if __name__ == "__main__":
    """Entry point when run as ECS Fargate task."""
    task_id = os.environ.get("TASK_ID")
    plan_key = os.environ.get("PRESENTATION_PLAN_KEY")
    template = os.environ.get("TEMPLATE_NAME", "default")

    if not task_id or not plan_key:
        logger.error("Missing required environment variables: TASK_ID, PRESENTATION_PLAN_KEY")
        sys.exit(1)

    try:
        result = run(task_id, plan_key, template)
        # Write result to stdout for Step Functions to capture
        print(json.dumps(result))
    except Exception as e:
        logger.error(f"Report generation failed: {traceback.format_exc()}")
        notify_progress(
            task_id=task_id,
            step="ReportGeneration",
            status="failed",
            progress=0,
            message=f"簡報生成失敗：{str(e)}",
        )
        sys.exit(1)
