"""
Template management API routes.

Endpoints:
- GET /api/v1/templates — List available presentation templates
"""

import logging

from fastapi import APIRouter, Depends

from src.api.middleware.auth import get_current_user
from src.modules.report_generator.template_loader import TemplateRegistry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


@router.get("")
async def list_templates(user: dict = Depends(get_current_user)):
    """List all available presentation templates."""
    registry = TemplateRegistry()
    templates = registry.list_templates()
    return {"templates": templates}
