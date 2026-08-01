"""
Amazon SES email client for report delivery.

Sends generated PPTX and Excel as attachments to specified recipients.
"""

import base64
import logging
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import boto3
from botocore.exceptions import ClientError

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class SesClient:
    """
    Amazon SES client for sending report emails with attachments.

    Features:
    - HTML email body with report summary
    - PPTX and Excel file attachments
    - Error handling with clear error messages
    """

    def __init__(self):
        settings = get_settings()
        self._client = boto3.client("ses", region_name=settings.aws_region)
        self._sender = settings.ses_sender_email

    def send_report_email(
        self,
        recipients: list[str],
        subject: str,
        html_body: str,
        attachments: list[dict],
    ) -> dict:
        """
        Send email with report attachments via SES.

        Args:
            recipients: List of email addresses
            subject: Email subject line
            html_body: HTML email body
            attachments: List of dicts with keys: filename, content_bytes, content_type

        Returns:
            SES response dict with MessageId
        """
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = self._sender
        msg["To"] = ", ".join(recipients)

        # HTML body
        body_part = MIMEMultipart("alternative")
        html_part = MIMEText(html_body, "html", "utf-8")
        body_part.attach(html_part)
        msg.attach(body_part)

        # Attachments
        for attachment in attachments:
            att = MIMEApplication(attachment["content_bytes"])
            att.add_header(
                "Content-Disposition",
                "attachment",
                filename=attachment["filename"],
            )
            att.add_header("Content-Type", attachment["content_type"])
            msg.attach(att)

        try:
            response = self._client.send_raw_email(
                Source=self._sender,
                Destinations=recipients,
                RawMessage={"Data": msg.as_string()},
            )
            message_id = response["MessageId"]
            logger.info(f"Email sent successfully. MessageId: {message_id}")
            return {"message_id": message_id, "recipients": recipients}

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_msg = e.response["Error"]["Message"]
            logger.error(f"SES send failed: {error_code} - {error_msg}")
            raise


def build_report_email_html(
    executive_summary: str,
    slide_count: int,
    quality_passed: bool,
    download_links: dict[str, str] | None = None,
) -> str:
    """
    Build HTML email body for report delivery.

    Args:
        executive_summary: Brief report summary
        slide_count: Number of slides in the presentation
        quality_passed: Whether QA checks passed
        download_links: Optional dict of presigned download URLs

    Returns:
        HTML string for email body
    """
    status_badge = (
        '<span style="color: green; font-weight: bold;">✓ 通過</span>'
        if quality_passed
        else '<span style="color: red; font-weight: bold;">✗ 未通過</span>'
    )

    links_section = ""
    if download_links:
        links_section = "<h3>下載連結（有效期 24 小時）</h3><ul>"
        for name, url in download_links.items():
            links_section += f'<li><a href="{url}">{name}</a></li>'
        links_section += "</ul>"

    html = f"""
    <html>
    <body style="font-family: 'Microsoft JhengHei', Arial, sans-serif; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto;">
            <h1 style="color: #1a3a5c;">智匯數據簡報神器</h1>
            <h2>您的信用卡業務分析報告已生成</h2>

            <div style="background: #f5f7fa; padding: 16px; border-radius: 8px; margin: 16px 0;">
                <p><strong>執行摘要：</strong></p>
                <p>{executive_summary}</p>
            </div>

            <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">簡報頁數</td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">{slide_count} 頁</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">品質檢驗</td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">{status_badge}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">附件格式</td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">PPTX（原生可編輯圖表）+ Excel</td>
                </tr>
            </table>

            {links_section}

            <p style="color: #666; font-size: 12px; margin-top: 24px;">
                此報告由 AI 自動生成，圖表為原生可編輯向量物件。<br>
                如需修改，請直接在 PowerPoint 或 Excel 中編輯。
            </p>

            <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
            <p style="color: #999; font-size: 11px;">
                智匯數據簡報神器 — 台新新光金控 × 2026 雲湧智生黑客松
            </p>
        </div>
    </body>
    </html>
    """
    return html
