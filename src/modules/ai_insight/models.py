"""
Pydantic output schemas for LLM-generated presentation content.

These models define the exact structure expected from Bedrock responses.
Used for validation after each LLM call to ensure output stability.
"""

from pydantic import BaseModel, Field
from typing import Literal


class ChartSpec(BaseModel):
    """Specification for a single chart to be rendered."""

    chart_type: Literal[
        "bar", "line", "pie", "scatter", "heatmap", "stacked_bar", "waterfall"
    ]
    title: str = Field(..., description="Chart title in Traditional Chinese")
    x_label: str = Field("", description="X-axis label")
    y_label: str = Field("", description="Y-axis label")
    categories: list[str] = Field(
        ..., description="Category labels (x-axis values)"
    )
    data_series: list["DataSeries"] = Field(
        ..., description="One or more data series"
    )


class DataSeries(BaseModel):
    """A single data series within a chart."""

    name: str = Field(..., description="Series name for legend")
    values: list[float] = Field(..., description="Numeric values")


class TableSpec(BaseModel):
    """Specification for a data table on a slide."""

    headers: list[str]
    rows: list[list[str]]


class SlideContent(BaseModel):
    """Content specification for a single presentation slide."""

    page_number: int = Field(..., ge=1, le=16, description="Slide number (1-16)")
    title: str = Field(..., description="Slide title")
    subtitle: str | None = Field(None, description="Optional subtitle")
    bullet_points: list[str] = Field(
        ...,
        min_length=2,
        max_length=6,
        description="Key insight bullet points (2-6 items)",
    )
    chart: ChartSpec | None = Field(None, description="Chart specification if this slide has a chart")
    table: TableSpec | None = Field(None, description="Table specification if this slide has a table")
    insight_driver: str = Field(
        ...,
        description="Explanation of the driving factor behind the insight (not a simple restatement of data)",
    )
    layout_type: Literal[
        "title_slide", "content_with_chart", "two_column", "full_chart", "content_only"
    ] = Field("content_with_chart", description="Slide layout type")


class PresentationOutline(BaseModel):
    """Stage A output: high-level outline of all 16 slides."""

    executive_summary: str = Field(
        ..., description="2-3 sentence executive summary of key findings"
    )
    theme: str = Field(
        ..., description="Overarching theme/narrative for the presentation"
    )
    slides: list["SlideOutlineItem"] = Field(
        ..., min_length=16, max_length=16, description="Exactly 16 slide outlines"
    )


class SlideOutlineItem(BaseModel):
    """Outline item for a single slide (used in Stage A)."""

    page_number: int = Field(..., ge=1, le=16)
    title: str
    focus_topic: str = Field(
        ..., description="What data/analysis this slide focuses on"
    )
    chart_type: str | None = Field(
        None, description="Suggested chart type or None for text-only"
    )
    data_source: str = Field(
        ..., description="Which data columns/metrics to use"
    )


class PresentationPlan(BaseModel):
    """Complete presentation plan with all slide content (Stage B aggregate)."""

    executive_summary: str
    theme: str
    slides: list[SlideContent] = Field(
        ..., min_length=16, max_length=16, description="Exactly 16 slides"
    )


class ConsistencyReview(BaseModel):
    """Stage C output: consistency review results."""

    is_consistent: bool = Field(
        ..., description="Whether all slides are logically consistent"
    )
    issues: list[str] = Field(
        default_factory=list, description="List of inconsistency issues found"
    )
    suggestions: list[str] = Field(
        default_factory=list, description="Improvement suggestions"
    )
    overall_quality_score: int = Field(
        ..., ge=1, le=10, description="Quality score from 1-10"
    )


# Update forward references
ChartSpec.model_rebuild()
PresentationOutline.model_rebuild()
