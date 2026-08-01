"""
Lambda handler for Module 2: AI Insight Generation (Staged).

Implements three-stage generation:
  Stage A: Outline generation (1 Bedrock call)
  Stage B: Page-by-page detailed insights (16 Bedrock calls)
  Stage C: Consistency review (1 Bedrock call)

Total: ~18 Bedrock calls, ~74 seconds with rate limiting.
"""

import json
import logging
import traceback
from typing import Any

from src.shared.config import get_settings
from src.shared.s3_utils import download_json, upload_json, get_artifact_key
from src.shared.websocket_notifier import notify_progress
from src.modules.ai_insight.bedrock_client import get_bedrock_client, BedrockClientError
from src.modules.ai_insight.models import (
    PresentationOutline,
    SlideContent,
    PresentationPlan,
    ConsistencyReview,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Prompt templates (loaded from S3 in production, inline for development)
SYSTEM_PROMPT = """你是一位頂尖的金融策略顧問，曾任職於 McKinsey、BCG、Deloitte 等全球策略諮詢公司。
你擅長從信用卡業務統計數據中挖掘深層商業洞察，而非只做表面的數據描述。

關鍵要求：
1. 不要只說「A銀行成長5%」這種流水帳，必須分析驅動因素（如數位生態圈策略、高回饋策略、通路佈局等）
2. 所有洞察必須有數據支撐，引用具體數字
3. 圖表建議必須選擇最能呈現洞察的類型（排名圖、趨勢圖、散點圖等）
4. 語言使用繁體中文，專業但不生硬
5. 輸出必須嚴格遵守指定的 JSON 格式
"""

OUTLINE_PROMPT_TEMPLATE = """基於以下信用卡業務統計數據，規劃一份 16 頁策略分析簡報的大綱。

數據摘要：
{data_summary}

要求：
- 恰好 16 頁，涵蓋：封面(1頁)、執行摘要(1頁)、市場總覽(2頁)、各維度深度分析(8頁)、競爭態勢(2頁)、策略建議(1頁)、附錄(1頁)
- 每頁指定適合的圖表類型
- 確保整體邏輯連貫，有明確的故事線

請輸出 PresentationOutline 格式的結構化 JSON。
"""

PAGE_DETAIL_PROMPT_TEMPLATE = """你正在製作一份 16 頁策略分析簡報的第 {page_number} 頁。

簡報大綱主題：{outline_title}
此頁聚焦主題：{focus_topic}
建議圖表類型：{chart_type}
數據來源指引：{data_source}

完整數據：
{data_json}

要求：
1. 撰寫 3-5 個關鍵洞察 bullet points（每個 30-50 字，含具體數字）
2. 如有圖表，提供完整的繪圖數據（categories + data_series）
3. insight_driver 必須說明「為什麼」而非「是什麼」
4. 確保數據準確，直接從提供的資料中計算

請輸出 SlideContent 格式的結構化 JSON。
"""

REVIEW_PROMPT_TEMPLATE = """請審核以下 16 頁簡報內容的一致性與品質：

{slides_json}

檢查項目：
1. 數據一致性：各頁引用的數字是否矛盾
2. 邏輯連貫性：故事線是否流暢
3. 洞察深度：是否都有分析「為什麼」
4. 圖表適切性：圖表類型是否能有效呈現該頁洞察

請輸出 ConsistencyReview 格式的結構化 JSON。
"""


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for AI insight generation.

    Input event:
    {
        "task_id": "abc-123",
        "parsed_data_key": "tasks/abc-123/artifacts/parsed_data.json"
    }

    Output:
    {
        "task_id": "abc-123",
        "presentation_plan_key": "tasks/abc-123/artifacts/presentation_plan.json",
        "quality_score": 8,
        "slide_count": 16
    }
    """
    task_id = event["task_id"]
    parsed_data_key = event["parsed_data_key"]

    logger.info(f"[{task_id}] Starting AI insight generation")

    try:
        # Load parsed data
        parsed_data = download_json(parsed_data_key)
        bedrock = get_bedrock_client()

        # === Stage A: Outline Generation ===
        notify_progress(
            task_id=task_id,
            step="AIInsightGeneration",
            status="in_progress",
            progress=25,
            message="正在生成簡報大綱...",
        )

        data_summary = _build_data_summary(parsed_data)
        outline_prompt = OUTLINE_PROMPT_TEMPLATE.format(data_summary=data_summary)

        outline = bedrock.converse_structured(
            system_prompt=SYSTEM_PROMPT,
            user_message=outline_prompt,
            output_model=PresentationOutline,
            max_tokens=4096,
            temperature=0.3,
        )

        logger.info(f"[{task_id}] Stage A complete: {len(outline.slides)} slide outlines")

        # Save outline artifact
        outline_key = get_artifact_key(task_id, "outline.json")
        upload_json(outline.model_dump(), outline_key)

        # === Stage B: Page-by-Page Insights ===
        slides: list[SlideContent] = []
        data_json = json.dumps(parsed_data, ensure_ascii=False, default=str)

        for i, slide_outline in enumerate(outline.slides):
            progress = 30 + int((i / 16) * 30)  # 30% - 60%
            notify_progress(
                task_id=task_id,
                step="AIInsightGeneration",
                status="in_progress",
                progress=progress,
                message=f"正在生成第 {i+1}/16 頁洞察...",
            )

            page_prompt = PAGE_DETAIL_PROMPT_TEMPLATE.format(
                page_number=slide_outline.page_number,
                outline_title=outline.theme,
                focus_topic=slide_outline.focus_topic,
                chart_type=slide_outline.chart_type or "無（純文字）",
                data_source=slide_outline.data_source,
                data_json=data_json[:8000],  # Limit context to avoid token overflow
            )

            slide_content = bedrock.converse_structured(
                system_prompt=SYSTEM_PROMPT,
                user_message=page_prompt,
                output_model=SlideContent,
                max_tokens=4096,
                temperature=0.3,
            )

            slides.append(slide_content)
            logger.info(f"[{task_id}] Stage B: page {i+1}/16 complete")

        # === Stage C: Consistency Review ===
        notify_progress(
            task_id=task_id,
            step="AIInsightGeneration",
            status="in_progress",
            progress=65,
            message="正在進行一致性審核...",
        )

        slides_json = json.dumps(
            [s.model_dump() for s in slides], ensure_ascii=False, default=str
        )
        review_prompt = REVIEW_PROMPT_TEMPLATE.format(slides_json=slides_json[:12000])

        review = bedrock.converse_structured(
            system_prompt=SYSTEM_PROMPT,
            user_message=review_prompt,
            output_model=ConsistencyReview,
            max_tokens=2048,
            temperature=0.2,
        )

        logger.info(
            f"[{task_id}] Stage C complete: score={review.overall_quality_score}, "
            f"consistent={review.is_consistent}"
        )

        # Build final presentation plan
        plan = PresentationPlan(
            executive_summary=outline.executive_summary,
            theme=outline.theme,
            slides=slides,
        )

        # Save presentation plan
        plan_key = get_artifact_key(task_id, "presentation_plan.json")
        upload_json(plan.model_dump(), plan_key)

        # Save review
        review_key = get_artifact_key(task_id, "consistency_review.json")
        upload_json(review.model_dump(), review_key)

        notify_progress(
            task_id=task_id,
            step="AIInsightGeneration",
            status="completed",
            progress=70,
            message="AI 洞察分析完成",
        )

        return {
            "task_id": task_id,
            "presentation_plan_key": plan_key,
            "quality_score": review.overall_quality_score,
            "is_consistent": review.is_consistent,
            "slide_count": len(slides),
            # Pass through fields for downstream steps
            "template_name": event.get("template_name", "default"),
            "recipients": event.get("recipients", []),
            "options": event.get("options", {}),
            "retryCount": event.get("retryCount", 0),
        }

    except BedrockClientError as e:
        logger.error(f"[{task_id}] Bedrock error: {e}")
        notify_progress(
            task_id=task_id,
            step="AIInsightGeneration",
            status="failed",
            progress=0,
            message=f"AI 分析失敗：{str(e)}",
        )
        raise

    except Exception as e:
        logger.error(f"[{task_id}] Unexpected error: {traceback.format_exc()}")
        notify_progress(
            task_id=task_id,
            step="AIInsightGeneration",
            status="failed",
            progress=0,
            message=f"系統錯誤：{str(e)}",
        )
        raise


def _build_data_summary(parsed_data: dict) -> str:
    """Build a concise data summary for the outline prompt."""
    parts = []

    metadata = parsed_data.get("metadata", {})
    parts.append(f"資料涵蓋 {metadata.get('total_sheets', 0)} 張工作表")
    parts.append(f"工作表名稱：{', '.join(metadata.get('sheet_names', []))}")

    aggregates = parsed_data.get("aggregates", {})
    if "簽帳金額_總計" in aggregates:
        parts.append(f"簽帳金額總計：{aggregates['簽帳金額_總計']:,.0f}")
    if "流通卡數_總計" in aggregates:
        parts.append(f"流通卡數總計：{aggregates['流通卡數_總計']:,}")

    top_banks = parsed_data.get("top_banks", [])
    if top_banks:
        parts.append(f"前 10 大銀行：{', '.join(top_banks[:10])}")

    # Include market share top 5
    if "簽帳金額_市占率" in aggregates:
        market_share = aggregates["簽帳金額_市占率"]
        sorted_share = sorted(market_share.items(), key=lambda x: x[1], reverse=True)[:5]
        share_str = ", ".join([f"{bank}({pct}%)" for bank, pct in sorted_share])
        parts.append(f"簽帳金額市佔率前5：{share_str}")

    return "\n".join(parts)
