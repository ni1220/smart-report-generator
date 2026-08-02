"""
Native PowerPoint generation engine with smart layout selection.

Supports TS Holdings template with:
- Cover pages (red gradient arc + large logo)
- Chapter divider pages (section headers)
- Content pages (clean white with bottom red line + small logo)
- Blank pages (for full-size charts)
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

PPTX_CHART_TYPE_MAP = {
    "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "stacked_bar": XL_CHART_TYPE.COLUMN_STACKED,
    "line": XL_CHART_TYPE.LINE,
    "pie": XL_CHART_TYPE.PIE,
    "scatter": XL_CHART_TYPE.XY_SCATTER,
    "waterfall": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "heatmap": XL_CHART_TYPE.COLUMN_CLUSTERED,
}


class PptxGenerator:
    """Generates PowerPoint presentations with native editable charts and smart layout selection."""

    def __init__(self, plan: PresentationPlan, template_bytes: bytes | None = None):
        self._plan = plan
        if template_bytes:
            self._prs = Presentation(BytesIO(template_bytes))
            # Remove existing slides from template (keep slide layouts/masters only)
            while len(self._prs.slides) > 0:
                rId = self._prs.slides._sldIdLst[0].rId
                self._prs.part.drop_rel(rId)
                del self._prs.slides._sldIdLst[0]
            logger.info("Template loaded, existing slides cleared, layouts preserved")
        else:
            self._prs = Presentation()
            self._prs.slide_width = Inches(13.333)  # 16:9 widescreen
            self._prs.slide_height = Inches(7.5)

        self._layout_map = self._analyze_layouts()
        logger.info(f"Layout mapping result: {self._layout_map}")

    def _analyze_layouts(self) -> dict[str, int]:
        """
        Analyze template slide layouts and map them to content types.

        Standard PowerPoint template layout indices (Traditional Chinese):
        0: 標題投影片 (Title Slide) → Cover/Closing
        1: 標題及內容 (Title and Content) → Main content pages
        2: 區段標頭 (Section Header) → Chapter dividers
        3: 兩個內容 (Two Content) → Two-column layouts
        4: 比較 (Comparison) → Side-by-side comparison
        5: 僅標題 (Title Only) → Chart-heavy pages
        6: 空白 (Blank) → Full chart pages
        """
        layout_map = {}
        layouts = self._prs.slide_layouts

        logger.info(f"Template has {len(layouts)} slide layouts:")
        for idx, layout in enumerate(layouts):
            name = layout.name if layout.name else f"Layout_{idx}"
            ph_count = len(layout.placeholders)
            logger.info(f"  [{idx}] '{name}' ({ph_count} placeholders)")

            name_lower = name.lower()

            # Match by Chinese or English layout names
            if any(kw in name_lower for kw in ["標題投影片", "title slide"]):
                if "title_cover" not in layout_map:
                    layout_map["title_cover"] = idx
            elif any(kw in name_lower for kw in ["區段標頭", "section header", "section"]):
                if "section" not in layout_map:
                    layout_map["section"] = idx
            elif any(kw in name_lower for kw in ["兩個內容", "two content", "比較", "comparison"]):
                if "two_column" not in layout_map:
                    layout_map["two_column"] = idx
            elif any(kw in name_lower for kw in ["僅標題", "title only"]):
                if "title_only" not in layout_map:
                    layout_map["title_only"] = idx
            elif any(kw in name_lower for kw in ["空白", "blank"]):
                if "blank" not in layout_map:
                    layout_map["blank"] = idx
            elif any(kw in name_lower for kw in ["標題及內容", "title and content", "內容"]):
                if "title_content" not in layout_map:
                    layout_map["title_content"] = idx

        # Fallbacks based on standard PowerPoint template order
        if "title_cover" not in layout_map:
            layout_map["title_cover"] = 0
        if "title_content" not in layout_map:
            layout_map["title_content"] = min(1, len(layouts) - 1)
        if "section" not in layout_map:
            layout_map["section"] = min(2, len(layouts) - 1)
        if "two_column" not in layout_map:
            layout_map["two_column"] = layout_map["title_content"]
        if "title_only" not in layout_map:
            layout_map["title_only"] = layout_map["title_content"]
        if "blank" not in layout_map:
            layout_map["blank"] = min(len(layouts) - 1, 6)

        return layout_map

    def _get_smart_layout(self, content: SlideContent):
        """
        Choose the best slide layout based on content type.

        TS Holdings template mapping:
        - Cover (P.1) and Closing (P.19) → title_cover (layout 0): red arc + big logo
        - Chapter dividers (P.4,9,12,15,17) → section (layout 2): red arc + CHAPTER XX
        - Content with charts → title_only or blank: maximum chart space
        - Bullet point content → title_content (layout 1): title + body area
        - Two-column → two_column (layout 3): side-by-side
        """
        layout_type = content.layout_type
        has_chart = content.chart and content.chart.categories and content.chart.data_series
        is_first = content.page_number == 1
        is_last = content.page_number == len(self._plan.slides)

        # Detect chapter divider: title_slide type but NOT first page
        is_chapter_divider = (
            layout_type == "title_slide" and not is_first
        )

        if is_first:
            # First page: Cover with big branding
            idx = self._layout_map["title_cover"]
        elif is_last:
            # Last page: Same as cover (Thank you page)
            idx = self._layout_map["title_cover"]
        elif is_chapter_divider:
            # Chapter divider pages
            idx = self._layout_map["section"]
        elif layout_type == "full_chart" and has_chart:
            # Full-page chart: use title_only or blank for max space
            idx = self._layout_map.get("title_only", self._layout_map.get("blank", 1))
        elif layout_type == "content_with_chart" and has_chart:
            # Content + chart: title_only gives title + blank area
            idx = self._layout_map.get("title_only", self._layout_map["title_content"])
        elif layout_type == "two_column":
            idx = self._layout_map["two_column"]
        else:
            # Default: standard content page with title + content area
            idx = self._layout_map["title_content"]

        layouts = self._prs.slide_layouts
        return layouts[idx] if idx < len(layouts) else layouts[0]

    def generate(self) -> bytes:
        """Generate complete PPTX presentation."""
        for slide_content in self._plan.slides:
            self._add_slide(slide_content)
        buffer = BytesIO()
        self._prs.save(buffer)
        buffer.seek(0)
        return buffer.read()

    def _add_slide(self, content: SlideContent):
        """Route slide creation based on content type."""
        layout_type = content.layout_type
        is_last = content.page_number == len(self._plan.slides)

        # Force last page to use title/closing layout regardless of AI decision
        if is_last:
            self._add_closing_slide(content)
        elif layout_type == "title_slide":
            if content.page_number == 1:
                self._add_title_slide(content)
            else:
                self._add_chapter_divider(content)
        elif layout_type == "full_chart":
            self._add_full_chart_slide(content)
        elif layout_type == "content_with_chart":
            self._add_content_with_chart_slide(content)
        elif layout_type == "two_column":
            self._add_two_column_slide(content)
        else:
            self._add_content_only_slide(content)

    def _add_title_slide(self, content: SlideContent):
        """Add cover slide (first page)."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        if slide.shapes.title:
            slide.shapes.title.text = content.title
        else:
            self._add_text_box(slide, content.title,
                               Inches(2), Inches(2), Inches(9), Inches(1.5), Pt(32), bold=True)

        if content.subtitle:
            self._add_text_box(slide, content.subtitle,
                               Inches(2), Inches(3.8), Inches(9), Inches(1), Pt(16))

    def _add_closing_slide(self, content: SlideContent):
        """Add closing/thank-you slide (last page) — uses cover layout."""
        layouts = self._prs.slide_layouts
        idx = self._layout_map["title_cover"]
        slide_layout = layouts[idx] if idx < len(layouts) else layouts[0]
        slide = self._prs.slides.add_slide(slide_layout)

        # Use title or fallback
        title = content.title if content.title else "感謝聆聽"
        if slide.shapes.title:
            slide.shapes.title.text = title
        else:
            self._add_text_box(slide, title,
                               Inches(3), Inches(2.5), Inches(7), Inches(1.5), Pt(32), bold=True)

        if content.subtitle:
            self._add_text_box(slide, content.subtitle,
                               Inches(3), Inches(4.2), Inches(7), Inches(1), Pt(14))

    def _add_chapter_divider(self, content: SlideContent):
        """Add chapter/section divider page."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        if slide.shapes.title:
            slide.shapes.title.text = content.title
        else:
            self._add_text_box(slide, content.title,
                               Inches(3), Inches(3), Inches(7), Inches(1.5), Pt(28), bold=True)

    def _add_content_with_chart_slide(self, content: SlideContent):
        """Add slide with bullet points (left) and chart (right)."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        self._set_slide_title(slide, content.title)

        # Bullet points (left side)
        if content.bullet_points:
            bullets = "\n".join(f"• {bp}" for bp in content.bullet_points)
            self._add_text_box(slide, bullets,
                               Inches(0.5), Inches(1.6), Inches(5.5), Inches(4.5), Pt(20))

        # Chart (right side)
        if content.chart:
            self._add_native_chart(slide, content.chart,
                                   Inches(6.2), Inches(1.6), Inches(6.5), Inches(4.5))

    def _add_full_chart_slide(self, content: SlideContent):
        """Add slide with full-width chart."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        self._set_slide_title(slide, content.title)

        # Full-width chart
        if content.chart:
            self._add_native_chart(slide, content.chart,
                                   Inches(0.5), Inches(1.5), Inches(12.3), Inches(5.0))

        # Insight at bottom
        if content.insight_driver:
            self._add_text_box(slide, f"◆ {content.insight_driver}",
                               Inches(0.5), Inches(6.6), Inches(12.0), Inches(0.5), Pt(9), italic=True)

    def _add_two_column_slide(self, content: SlideContent):
        """Add two-column layout slide."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        self._set_slide_title(slide, content.title)

        # Left column: bullets
        if content.bullet_points:
            bullets = "\n".join(f"• {bp}" for bp in content.bullet_points)
            self._add_text_box(slide, bullets,
                               Inches(0.5), Inches(1.6), Inches(6.0), Inches(4.5), Pt(20))

        # Right column: chart or table
        if content.chart:
            self._add_native_chart(slide, content.chart,
                                   Inches(6.8), Inches(1.6), Inches(6.0), Inches(4.5))
        elif content.table:
            self._add_table(slide, content.table.headers, content.table.rows,
                           left=Inches(6.8), top=Inches(1.6),
                           width=Inches(6.0), height=Inches(4.5))

    def _add_content_only_slide(self, content: SlideContent):
        """Add text-only content slide."""
        slide_layout = self._get_smart_layout(content)
        slide = self._prs.slides.add_slide(slide_layout)

        self._set_slide_title(slide, content.title)

        # Full-width bullet points
        if content.bullet_points:
            bullets = "\n\n".join(f"• {bp}" for bp in content.bullet_points)
            self._add_text_box(slide, bullets,
                               Inches(0.8), Inches(1.6), Inches(11.5), Inches(4.5), Pt(20))

        # Insight driver
        if content.insight_driver:
            self._add_text_box(slide, f"◆ 驅動因素：{content.insight_driver}",
                               Inches(0.8), Inches(6.2), Inches(11.5), Inches(0.6), Pt(10), italic=True)

    # === Chart & Table Helpers ===

    def _add_native_chart(self, slide, chart_spec: ChartSpec, left, top, width, height):
        """Add a native editable chart with optimized readability."""
        if not chart_spec.categories or not chart_spec.data_series:
            return
        try:
            chart_type = PPTX_CHART_TYPE_MAP.get(chart_spec.chart_type, XL_CHART_TYPE.COLUMN_CLUSTERED)
            chart_data = CategoryChartData()

            # Limit categories for readability (max 12)
            categories = chart_spec.categories[:12]
            chart_data.categories = categories

            for series in chart_spec.data_series:
                values = series.values[:len(categories)]
                while len(values) < len(categories):
                    values.append(0)
                chart_data.add_series(series.name, tuple(values))

            chart_frame = slide.shapes.add_chart(chart_type, left, top, width, height, chart_data)
            chart = chart_frame.chart

            # Legend: always show for pie charts and multi-series
            is_pie = chart_spec.chart_type == "pie"
            if is_pie or len(chart_spec.data_series) > 1:
                chart.has_legend = True
                from pptx.enum.chart import XL_LEGEND_POSITION
                chart.legend.position = XL_LEGEND_POSITION.BOTTOM
                chart.legend.include_in_layout = False
                chart.legend.font.size = Pt(8)
            else:
                chart.has_legend = False

            # Chart title
            if chart_spec.title:
                chart.has_title = True
                chart.chart_title.text_frame.text = chart_spec.title[:50]
                chart.chart_title.text_frame.paragraphs[0].font.size = Pt(10)
                chart.chart_title.text_frame.paragraphs[0].font.bold = True

            # Axis formatting (not for pie charts)
            if not is_pie:
                try:
                    if hasattr(chart, 'category_axis'):
                        chart.category_axis.tick_labels.font.size = Pt(8)
                    if hasattr(chart, 'value_axis'):
                        chart.value_axis.tick_labels.font.size = Pt(8)
                        chart.value_axis.has_major_gridlines = True
                except Exception:
                    pass

            logger.info(f"Added native {chart_spec.chart_type} chart: '{chart_spec.title}'")
        except Exception as e:
            logger.warning(f"Failed to add chart '{chart_spec.title}': {e}")

    def _add_table(self, slide, headers, rows, **pos):
        """Add a native table to the slide."""
        row_count = len(rows) + 1
        col_count = len(headers)
        tbl = slide.shapes.add_table(
            row_count, col_count, pos["left"], pos["top"], pos["width"], pos["height"]
        ).table
        for i, h in enumerate(headers):
            tbl.cell(0, i).text = h
            tbl.cell(0, i).text_frame.paragraphs[0].font.bold = True
            tbl.cell(0, i).text_frame.paragraphs[0].font.size = Pt(9)
        for ri, row in enumerate(rows, 1):
            for ci, val in enumerate(row):
                if ci < col_count:
                    tbl.cell(ri, ci).text = str(val)
                    tbl.cell(ri, ci).text_frame.paragraphs[0].font.size = Pt(8)

    # === Utility Helpers ===

    def _set_slide_title(self, slide, title: str):
        """Set slide title using placeholder or text box."""
        if slide.shapes.title:
            slide.shapes.title.text = title
        else:
            self._add_text_box(slide, title,
                               Inches(0.5), Inches(0.3), Inches(12.0), Inches(0.9), Pt(22), bold=True)

    def _add_text_box(self, slide, text, left, top, width, height,
                      font_size=Pt(12), bold=False, italic=False):
        """Add a formatted text box with proper multi-line support."""
        txBox = slide.shapes.add_textbox(left, top, width, height)
        tf = txBox.text_frame
        tf.word_wrap = True

        # Split text into paragraphs for proper formatting
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if i == 0:
                p = tf.paragraphs[0]
            else:
                p = tf.add_paragraph()
            p.text = line
            p.font.size = font_size
            p.font.bold = bold
            p.font.italic = italic
            p.font.name = "Microsoft JhengHei"  # 微軟正黑體
            p.space_after = Pt(4)

    def _get_layout(self, index: int):
        """Get slide layout by index (legacy fallback)."""
        layouts = self._prs.slide_layouts
        return layouts[index] if index < len(layouts) else layouts[0]
