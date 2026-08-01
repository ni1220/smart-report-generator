"""
Lambda handler for Module 1: Data Ingestion & Validation.

Triggered by Step Functions. Reads Excel from S3, validates,
transforms, and uploads structured JSON artifact.
"""

import json
import logging
import traceback
from typing import Any

from src.shared.config import get_settings
from src.shared.s3_utils import download_file, upload_json, get_artifact_key
from src.shared.websocket_notifier import notify_progress
from src.modules.data_parser.transformer import CreditCardDataTransformer, DataTransformError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for data parsing step.

    Input event:
    {
        "task_id": "abc-123",
        "data_source_key": "sample_data/credit_card_stats_2025.xlsx",
        "data_source_keys": ["file1.xlsx", "file2.xlsx"]  // optional, for multi-file
    }

    Output:
    {
        "task_id": "abc-123",
        "parsed_data_key": "tasks/abc-123/artifacts/parsed_data.json",
        "validation_passed": true,
        "sheet_count": 3,
        "bank_count": 35
    }
    """
    task_id = event["task_id"]
    data_source_key = event["data_source_key"]
    data_source_keys = event.get("data_source_keys", [data_source_key])

    logger.info(f"[{task_id}] Starting data parsing: {len(data_source_keys)} file(s)")

    # Notify progress
    notify_progress(
        task_id=task_id,
        step="DataIngestion",
        status="in_progress",
        progress=10,
        message=f"正在讀取 {len(data_source_keys)} 個 Excel 資料...",
    )

    try:
        # 1. Download and parse all Excel files
        all_llm_json = None
        total_sheets = 0
        validation_passed = True

        for idx, key in enumerate(data_source_keys):
            logger.info(f"[{task_id}] Parsing file {idx+1}/{len(data_source_keys)}: {key}")
            excel_bytes = download_file(key)
            logger.info(f"[{task_id}] Downloaded {len(excel_bytes)} bytes from {key}")

            transformer = CreditCardDataTransformer(excel_bytes)
            transformer.read_sheets()

            file_valid = transformer.validate()
            if not file_valid:
                validation_passed = False

            file_json = transformer.to_llm_json()
            total_sheets += file_json["metadata"]["total_sheets"]

            # Merge data from multiple files
            if all_llm_json is None:
                all_llm_json = file_json
                all_llm_json["metadata"]["source_files"] = [key]
            else:
                # Merge sheets data (handle both dict and list formats)
                if "sheets" in file_json:
                    existing_sheets = all_llm_json.get("sheets")
                    new_sheets = file_json["sheets"]
                    if isinstance(existing_sheets, dict) and isinstance(new_sheets, dict):
                        existing_sheets.update(new_sheets)
                    elif isinstance(existing_sheets, list) and isinstance(new_sheets, list):
                        existing_sheets.extend(new_sheets)
                    elif isinstance(existing_sheets, dict) and isinstance(new_sheets, list):
                        for i, s in enumerate(new_sheets):
                            existing_sheets[f"file{idx+1}_sheet{i}"] = s
                    elif isinstance(existing_sheets, list) and isinstance(new_sheets, dict):
                        for k, v in new_sheets.items():
                            existing_sheets.append({"name": k, "data": v})
                    elif existing_sheets is None:
                        all_llm_json["sheets"] = new_sheets

                # Merge top_banks (deduplicate)
                existing_banks = {b.get("name") for b in all_llm_json.get("top_banks", [])}
                for bank in file_json.get("top_banks", []):
                    if bank.get("name") not in existing_banks:
                        all_llm_json.setdefault("top_banks", []).append(bank)
                # Merge summary stats
                if "summary" in file_json:
                    all_llm_json.setdefault("additional_summaries", []).append(file_json["summary"])
                all_llm_json["metadata"]["source_files"].append(key)

            notify_progress(
                task_id=task_id,
                step="DataIngestion",
                status="in_progress",
                progress=10 + int(8 * (idx + 1) / len(data_source_keys)),
                message=f"已解析 {idx+1}/{len(data_source_keys)} 個檔案...",
            )

        # Update metadata
        all_llm_json["metadata"]["total_sheets"] = total_sheets
        all_llm_json["metadata"]["total_files"] = len(data_source_keys)

        notify_progress(
            task_id=task_id,
            step="DataIngestion",
            status="in_progress",
            progress=18,
            message="正在計算加總與市佔率...",
        )

        # 2. Upload merged result to S3
        artifact_key = get_artifact_key(task_id, "parsed_data.json")
        upload_json(
            data=all_llm_json,
            key=artifact_key,
            metadata={
                "task_id": task_id,
                "validation_passed": str(validation_passed),
                "file_count": str(len(data_source_keys)),
            },
        )

        # 3. Notify completion
        notify_progress(
            task_id=task_id,
            step="DataIngestion",
            status="completed",
            progress=20,
            message=f"資料解析完成（{len(data_source_keys)} 個檔案）",
        )

        result = {
            "task_id": task_id,
            "parsed_data_key": artifact_key,
            "validation_passed": validation_passed,
            "sheet_count": total_sheets,
            "bank_count": len(all_llm_json.get("top_banks", [])),
            "validation_errors": all_llm_json["metadata"].get("validation_errors", []),
            # Pass through fields for downstream steps
            "template_name": event.get("template_name", "default"),
            "recipients": event.get("recipients", []),
            "options": event.get("options", {}),
            "retryCount": event.get("retryCount", 0),
        }

        logger.info(f"[{task_id}] Data parsing completed: {result}")
        return result

    except DataTransformError as e:
        logger.error(f"[{task_id}] Data transform error: {e}")
        notify_progress(
            task_id=task_id,
            step="DataIngestion",
            status="failed",
            progress=0,
            message=f"資料解析失敗：{str(e)}",
        )
        raise

    except Exception as e:
        logger.error(f"[{task_id}] Unexpected error: {traceback.format_exc()}")
        notify_progress(
            task_id=task_id,
            step="DataIngestion",
            status="failed",
            progress=0,
            message=f"系統錯誤：{str(e)}",
        )
        raise
