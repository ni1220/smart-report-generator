"""
FastAPI application entry point.

Serves as the API Gateway Lambda handler (via Mangum)
and local development server.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from src.api.routes import reports, templates, upload
from src.shared.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

# Initialize app
app = FastAPI(
    title="智匯數據簡報神器 API",
    description="AI-powered credit card business analytics report generator",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(reports.router)
app.include_router(templates.router)
app.include_router(upload.router)


@app.get("/", tags=["health"])
async def root():
    """Health check endpoint."""
    settings = get_settings()
    return {
        "service": "smart-report-generator",
        "version": "2.0.0",
        "region": settings.aws_region,
        "status": "healthy",
    }


@app.get("/health", tags=["health"])
async def health_check():
    """Detailed health check."""
    settings = get_settings()
    return {
        "status": "healthy",
        "region": settings.aws_region,
        "features": {
            "voice_agent": settings.enable_voice_agent,
            "rag": settings.enable_rag,
        },
        "bedrock_model": settings.bedrock_model_id,
    }


# Lambda handler (API Gateway integration)
handler = Mangum(app, lifespan="off")
