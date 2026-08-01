"""
Template management for PPTX generation.

Loads templates from S3 and manages template registry.
"""

import json
import logging
from typing import Any

from src.shared.config import get_settings
from src.shared.s3_utils import download_file, download_json

logger = logging.getLogger(__name__)


class TemplateRegistry:
    """Manages PPTX template registration and loading."""

    def __init__(self):
        self._settings = get_settings()
        self._registry: dict[str, Any] | None = None

    def load_registry(self) -> dict[str, Any]:
        """Load template registry from S3."""
        if self._registry:
            return self._registry

        registry_key = f"{self._settings.s3_template_prefix}template_registry.json"
        try:
            self._registry = download_json(registry_key)
            logger.info(f"Loaded template registry with {len(self._registry)} templates")
        except Exception as e:
            logger.warning(f"Failed to load template registry: {e}, using defaults")
            self._registry = self._get_default_registry()

        return self._registry

    def get_template_bytes(self, template_name: str = "default") -> bytes | None:
        """
        Download template PPTX file from S3.

        Args:
            template_name: Template identifier (default: "default")

        Returns:
            Template file bytes, or None if not found
        """
        registry = self.load_registry()

        if template_name not in registry:
            logger.warning(f"Template '{template_name}' not found, using default")
            template_name = "default"

        if template_name not in registry:
            logger.info("No templates available, will use blank presentation")
            return None

        template_info = registry[template_name]
        template_key = f"{self._settings.s3_template_prefix}{template_info['file']}"

        try:
            template_bytes = download_file(template_key)
            logger.info(f"Loaded template '{template_name}': {len(template_bytes)} bytes")
            return template_bytes
        except Exception as e:
            logger.warning(f"Failed to load template file: {e}")
            return None

    def list_templates(self) -> list[dict[str, str]]:
        """List all available templates."""
        registry = self.load_registry()
        return [
            {"name": name, "file": info.get("file", "")}
            for name, info in registry.items()
        ]

    def _get_default_registry(self) -> dict[str, Any]:
        """Return default registry when S3 is unavailable."""
        return {
            "default": {
                "file": "taishin_shinkon_default.pptx",
                "layouts": {
                    "title_slide": {"index": 0},
                    "content_with_chart": {
                        "index": 1,
                        "chart_placeholder": {"x": 1.0, "y": 2.0, "w": 8.0, "h": 4.5},
                    },
                    "two_column": {"index": 2},
                    "full_chart": {
                        "index": 3,
                        "chart_placeholder": {"x": 0.5, "y": 1.5, "w": 9.0, "h": 5.5},
                    },
                },
            }
        }
