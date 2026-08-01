"""
Native PowerPoint generation engine using python-pptx.

Creates editable PPTX with native vector chart objects.
ABSOLUTELY NO image-based charts — all charts use pptx.chart native API.
"""

import logging
from io import BytesIO
from typing import Any

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor

from src.modules.ai_insight.models import PresentationPlan, SlideContent, ChartSpec

logger = logging.getLogger(__name__)

# Chart type mapping to python-pptx enum
PPTX_CHART_TYPE_MAP = {
    "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "stacked_bar": XL_CHART_TYPE.COLUMN_STACKED,
    "line": XL_CHART_TYPE.LINE,
    "pie": XL_CHART_TYPE.PIE,
    "scatter": XL_CHART_TYPE.XY_SCATTER,
    "waterfall": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "heatmap": XL_CHART_TYPE.COLUMN_CLUSTERED,
}

# Default chart position on slide
DEFAULT_CHART_POSITION = {
    "content_with_chart": {"x": 0.8, "y": 2.2, "w": 8.5, "h": 4.3},
    "full_chart": {"x": 0.5, "y": 1.5, "w": 9.0, "h": 5.5},
    "two_column": {"x": 5.0, "y": 2.0, "w": 4.5, "h": 4.5},
}


class PptxGenerator:
    """
    Generates PowerPoint presentations with native editable charts.

    Features:
    - Native vector chart objects (not images)
    - Template support (loads .pptx template if available)
    - Professional formatting with corporate styling
    - 16-slide structure as per competition requirements
    """

    def __init__(self, plan: PresentationPlan, template_bytes: bytes | None = None):
        """
        Initialize PPTX generator.

        Args:
            plan: Complete presentation plan from AI insight engine
            template_bytes: Optional .pptx template file bytes
        """
        self._plan = plan
        if template_bytes:
            self._prs = Presentation(BytesIO(template_bytes))
            # Remove existing slides from template (keep layouts only)
            while len(self._prs.slides) > 0:
                rId = self._prs.slides._sldIdLst[0].rId
                self._prs.part.drop_rel(rId)
                del self._prs.slides._sldIdLst[0]
        else:
            self._prs = Presentation()
            # Set slide dimensions to widescreen 16:9
            self._prs.slide_width = Inches(10)
            self._prs.slide_height = Inches(5.625)

        # Analyze available layouts for smart selection
        self._layout_map = self._analyze_layouts()
        logger.info(f"Available layouts: {list(self._layout_map.keys())}")

    def _analyze_layouts(self) -> dict[str, int]:
        """
        Analyze template slide layouts and map them to content types.

        Heuristic:
        - Layout with fewest placeholders or "title" in name → title/cover
        - Layout with large blank area → chart-heavy pages
        - Layout with content placeholder → bullet point pages
        - Layout with two content areas → two-column
        """
        layout_map = {}
        layouts = self._prs.slide_layouts

        for idx, layout in enumerate(layouts):
            name = layout.name.lower() if layout.name else ""
            ph_count = len(layout.placeholders)

            # Classify by name keywords
            if any(kw in name for kw in ["標題", "title", "封面", "cover"]):
                if "title_cover" not in layout_map:
                    layout_map["title_cover"] = idx
            elif any(kw in name for kw in ["空白", "blank", "留白"]):
                if "blank" not in layout_map:
                    layout_map["blank"] = idx
            elif any(kw in name for kw in ["內容", "content", "兩欄", "two", "比較", "comparison"]):
                if "two_column" not in layout_map:
                    layout_map["two_column"] = idx
            elif any(kw in name for kw in ["節", "section", "區段"]):
                if "section" not in layout_map:
                    layout_map["section"] = idx

            # Classify by placeholder count
            if ph_count <= 1 and "blank" not in layout_map:
                layout_map["blank"] = idx
            elif ph_count == 2 and "title_content" not in layout_map:
                layout_map["title_content"] = idx

        # Fallbacks
        if "title_cover" not in layout_map:
            layout_map["title_cover"] = 0
        if "blank" not in layout_map:
            # Prefer layout with fewest placeholders for charts
            min_ph = 99
            min_idx = 0
            for idx, layout in enumerate(layouts):
                if len(layout.placeholders) < min_ph:
                    min_ph = len(layout.placeholders)
                    min_idx = idx
            layout_map["blank"] = min_idx
        if "title_content" not in layout_map:
            layout_map["title_content"] = min(1, len(layouts) - 1)
        if "two_column" not in layout_map:
            layout_map["two_column"] = layout_map.get("title_content", 1)
        if "section" not in layout_map:
            layout_map["section"] = layout_map["title_cover"]

        return layout_map

    def _get_smart_layout(self, content: SlideContent):
        """
        Choose the best slide layout based on content type.

        Rules:
        - Title/cover page → title_cover layout (usually has company branding)
        - Chart-heavy slides → blank layout (maximum space for chart)
        - Bullet-point slides → title_content layout
        - Two-column → two_column layout
        - Section dividers → section layout
        """
        layout_type = content.layout_type
        has_chart = content.chart and content.chart.categories and content.chart.data_series
        is_first_page = content.page_number == 1
        is_last_page = content.page_number == len(self._plan.slides)

        if is_first_page or layout_type == "title_slide":
            idx = self._layout_map.get("title_cover", 0)
        elif layout_type == "full_chart" or (has_chart and not content.bullet_points):
            # Charts need maximum blank space
            idx = self._layout_map.get("blank", 1)
        elif layout_type == "two_column":
            idx = self._layout_map.get("two_column", 1)
        elif layout_type == "content_with_chart" and has_chart:
            # Content + chart: use blank for flexibility
            idx = self._layout_map.get("blank", 1)
        elif is_last_page:
            # Last page (summary/thank you) → section or title
            idx = self._layout_map.get("section", self._layout_map.get("title_cover", 0))
        else:
            # Default: title + content
            idx = self._layout_map.get("title_content", 1)

        layouts = self._prs.slide_layouts
        if idx < len(layouts):
            return layouts[idx]
        return layouts[0]

    def generate(self) -> bytes:
        """
        Generate complete PPTX presentation.

        Returns:
            PPTX file content as bytes
        """
        for slide_content in self._plan.slides:
            self._add_slide(slide_content)

        buffer = BytesIO()
        self._prs.save(buffer)
        buffer.seek(0)
        return buffer.read()

    def _add_slide(self, content: SlideContent):
        """Add a single slide based on its content specification."""
        layout_type = content.layout_type

        if layout_type == "title_slide":
            self._add_title_slide(content)
        elif layout_type == "full_chart":
            self._add_full_chart_slide(content)
        elif layout_type == "content_with_chart":
            self._add_content_with_chart_slide(content)
        elif layout_type == "two_column":
            self._add_two_column_slide(content)
        else:
            self._add_content_only_slide(content)

    def _add_title_slide(self, content: SlideContent):
        """Add a title/cover slide using the template's cover layout."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        # Title
        if slide.shapes.title:
            slide.shapes.title.text = content.title
        else:
            self._add_text_box(
                slide, content.title,
                left=Inches(1), top=Inches(2),
                width=Inches(8), height=Inches(1.5),
                font_size=Pt(28), bold=True,
            )

        # Subtitle
        if content.subtitle:
            self._add_text_box(
                slide, content.subtitle,
                left=Inches(1), top=Inches(3.5),
                width=Inches(8), height=Inches(1),
                font_size=Pt(16), bold=False,
            )

    def _add_content_with_chart_slide(self, content: SlideContent):
        """Add slide with bullet points and a chart — uses blank layout for space."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        # Title
        self._set_slide_title(slide, content.title)

        # Bullet points (left side)
        bullets_text = "\n".join(f"• {bp}" for bp in content.bullet_points)
        self._add_text_box(
            slide, bullets_text,
            left=Inches(0.5), top=Inches(1.8),
            width=Inches(4.2), height=Inches(3.5),
            font_size=Pt(11),
        )

        # Chart (right side) - NATIVE VECTOR CHART
        if content.chart:
            self._add_native_chart(
                slide, content.chart,
                left=Inches(4.8), top=Inches(1.8),
                width=Inches(4.8), height=Inches(3.5),
            )

    def _add_full_chart_slide(self, content: SlideContent):
        """Add slide dominated by a large chart — uses blank layout for maximum space."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        # Title
        self._set_slide_title(slide, content.title)

        # Full-width chart - NATIVE VECTOR CHART
        if content.chart:
            self._add_native_chart(
                slide, content.chart,
                left=Inches(0.5), top=Inches(1.5),
                width=Inches(9.0), height=Inches(3.8),
            )

        # Insight driver at bottom
        self._add_text_box(
            slide, f"💡 {content.insight_driver}",
            left=Inches(0.5), top=Inches(5.0),
            width=Inches(9.0), height=Inches(0.5),
            font_size=Pt(9), italic=True,
        )

    def _add_two_column_slide(self, content: SlideContent):
        """Add two-column layout slide."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        # Title
        self._set_slide_title(slide, content.title)

        # Left column: bullet points
        bullets_text = "\n".join(f"• {bp}" for bp in content.bullet_points)
        self._add_text_box(
            slide, bullets_text,
            left=Inches(0.5), top=Inches(1.8),
            width=Inches(4.5), height=Inches(3.5),
            font_size=Pt(11),
        )

        # Right column: chart or table
        if content.chart:
            self._add_native_chart(
                slide, content.chart,
                left=Inches(5.2), top=Inches(1.8),
                width=Inches(4.3), height=Inches(3.5),
            )
        elif content.table:
            self._add_table(
                slide, content.table.headers, content.table.rows,
                left=Inches(5.2), top=Inches(1.8),
                width=Inches(4.3), height=Inches(3.5),
            )

    def _add_content_only_slide(self, content: SlideContent):
        """Add text-only content slide — uses title+content layout."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        # Title
        self._set_slide_title(slide, content.title)

        # Full-width bullet points
        bullets_text = "\n\n".join(f"• {bp}" for bp in content.bullet_points)
        self._add_text_box(
            slide, bullets_text,
            left=Inches(0.8), top=Inches(1.8),
            width=Inches(8.4), height=Inches(3.5),
            font_size=Pt(13),
        )

        # Insight driver
        self._add_text_box(
            slide, f"驅動因素：{content.insight_driver}",
            left=Inches(0.8), top=Inches(4.8),
            width=Inches(8.4), height=Inches(0.6),
            font_size=Pt(10), italic=True,
        )

    def _add_native_chart(
        self,
        slide,
        chart_spec: ChartSpec,
        left: Emu,
        top: Emu,
        width: Emu,
        height: Emu,
    ):
        """
        Add a NATIVE VECTOR chart to the slide using python-pptx chart API.

        This is the core differentiator: charts are editable objects,
        NOT pasted images.
        """
        # Defensive: skip if no data
        if not chart_spec.categories or not chart_spec.data_series:
            logger.warning(f"Skipping chart '{chart_spec.title}': empty categories or data_series")
            return

        try:
            chart_type = PPTX_CHART_TYPE_MAP.get(
                chart_spec.chart_type, XL_CHART_TYPE.COLUMN_CLUSTERED
            )

            # Build chart data
            chart_data = CategoryChartData()
            chart_data.categories = chart_spec.categories

            for series in chart_spec.data_series:
                # Ensure values length matches categories
                values = series.values[: len(chart_spec.categories)]
                # Pad with 0 if shorter
                while len(values) < len(chart_spec.categories):
                    values.append(0)
                chart_data.add_series(series.name, tuple(values))

            # Add chart shape to slide - THIS IS NATIVE, NOT AN IMAGE
            chart_frame = slide.shapes.add_chart(
                chart_type, left, top, width, height, chart_data
            )

            # Style the chart
            chart = chart_frame.chart
            chart.has_legend = len(chart_spec.data_series) > 1

            # Set chart title
            if chart_spec.title:
                chart.has_title = True
                chart.chart_title.text_frame.text = chart_spec.title
                chart.chart_title.text_frame.paragraphs[0].font.size = Pt(10)

            logger.info(
                f"Added native {chart_spec.chart_type} chart: '{chart_spec.title}'"
            )

        except Exception as e:
            logger.warning(f"Failed to add chart '{chart_spec.title}': {e}. Skipping chart.")

    def _add_table(self, slide, headers: list[str], rows: list[list[str]], **position):
        """Add a native table to the slide."""
        row_count = len(rows) + 1  # +1 for header
        col_count = len(headers)

        table_shape = slide.shapes.add_table(
            row_count, col_count,
            position["left"], position["top"],
            position["width"], position["height"],
        )
        table = table_shape.table

        # Headers
        for i, header in enumerate(headers):
            cell = table.cell(0, i)
            cell.text = header
            cell.text_frame.paragraphs[0].font.bold = True
            cell.text_frame.paragraphs[0].font.size = Pt(9)

        # Data rows
        for row_idx, row_data in enumerate(rows, 1):
            for col_idx, value in enumerate(row_data):
                if col_idx < col_count:
                    cell = table.cell(row_idx, col_idx)
                    cell.text = str(value)
                    cell.text_frame.paragraphs[0].font.size = Pt(8)

    def _set_slide_title(self, slide, title: str):
        """Set the slide title, using placeholder or creating text box."""
        if slide.shapes.title:
            slide.shapes.title.text = title
        else:
            self._add_text_box(
                slide, title,
                left=Inches(0.5), top=Inches(0.3),
                width=Inches(9.0), height=Inches(0.8),
                font_size=Pt(20), bold=True,
            )

    def _add_text_box(
        self,
        slide,
        text: str,
        left: Emu,
        top: Emu,
        width: Emu,
        height: Emu,
        font_size: Pt = Pt(12),
        bold: bool = False,
        italic: bool = False,
    ):
        """Add a formatted text box to the slide."""
        txBox = slide.shapes.add_textbox(left, top, width, height)
        tf = txBox.text_frame
        tf.word_wrap = True

        p = tf.paragraphs[0]
        p.text = text
        p.font.size = font_size
        p.font.bold = bold
        p.font.italic = italic

    def _get_layout(self, index: int):
        """Get slide layout by index, with fallback."""
        layouts = self._prs.slide_layouts
        if index < len(layouts):
            return layouts[index]
        return layouts[0]
