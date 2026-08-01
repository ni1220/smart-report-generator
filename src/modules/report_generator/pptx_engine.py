"""
Native PowerPoint generation engine with smart layout selection.

Optimized for TS Holdings template:
- Safe content area: avoid bottom red gradient + logo zone (below Y=5.8")
- Title area: Y 0.3" to 1.2"
- Content area: Y 1.4" to 5.6"
- Speaker notes: AI analysis reasoning added to every content slide
"""

import logging
from io import BytesIO

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches, Pt, Cm
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

# Safe content zones (avoid template decorations)
# Template is 13.333" x 7.5" (widescreen 16:9)
TITLE_TOP = Inches(0.4)
TITLE_HEIGHT = Inches(0.9)
CONTENT_TOP = Inches(1.5)
CONTENT_BOTTOM = Inches(5.6)  # Stop before bottom decoration
CONTENT_HEIGHT = Inches(4.1)  # 5.6 - 1.5
LEFT_MARGIN = Inches(0.6)
RIGHT_MARGIN = Inches(0.6)
SLIDE_WIDTH = Inches(13.333)
FULL_CONTENT_WIDTH = Inches(12.1)  # 13.333 - 0.6 - 0.6


class PptxGenerator:
    """Generates PPTX with native charts, smart layout selection, and speaker notes."""

    def __init__(self, plan: PresentationPlan, template_bytes: bytes | None = None):
        self._plan = plan
        if template_bytes:
            self._prs = Presentation(BytesIO(template_bytes))
            # Remove existing slides, keep layouts
            while len(self._prs.slides) > 0:
                rId = self._prs.slides._sldIdLst[0].rId
                self._prs.part.drop_rel(rId)
                del self._prs.slides._sldIdLst[0]
            logger.info("Template loaded, slides cleared")
        else:
            self._prs = Presentation()
            self._prs.slide_width = Inches(13.333)
            self._prs.slide_height = Inches(7.5)

        self._layout_map = self._analyze_layouts()
        logger.info(f"Layout mapping: {self._layout_map}")

    def _analyze_layouts(self):
        layout_map = {}
        layouts = self._prs.slide_layouts
        for idx, layout in enumerate(layouts):
            name = (layout.name or "").lower()
            logger.info(f"  [{idx}] '{layout.name}'")
            if any(kw in name for kw in ["標題投影片", "title slide"]):
                if "title_cover" not in layout_map:
                    layout_map["title_cover"] = idx
            elif any(kw in name for kw in ["區段標頭", "section header"]):
                if "section" not in layout_map:
                    layout_map["section"] = idx
            elif any(kw in name for kw in ["僅標題", "title only"]):
                if "title_only" not in layout_map:
                    layout_map["title_only"] = idx
            elif any(kw in name for kw in ["空白", "blank"]):
                if "blank" not in layout_map:
                    layout_map["blank"] = idx
            elif any(kw in name for kw in ["標題及內容", "title and content"]):
                if "title_content" not in layout_map:
                    layout_map["title_content"] = idx
            elif any(kw in name for kw in ["兩個內容", "two content"]):
                if "two_column" not in layout_map:
                    layout_map["two_column"] = idx

        # Fallbacks
        if "title_cover" not in layout_map:
            layout_map["title_cover"] = 0
        if "title_content" not in layout_map:
            layout_map["title_content"] = min(1, len(layouts) - 1)
        if "section" not in layout_map:
            layout_map["section"] = min(2, len(layouts) - 1)
        if "title_only" not in layout_map:
            layout_map["title_only"] = layout_map["title_content"]
        if "blank" not in layout_map:
            layout_map["blank"] = min(len(layouts) - 1, 6)
        if "two_column" not in layout_map:
            layout_map["two_column"] = layout_map["title_content"]
        return layout_map

    def _get_smart_layout(self, content: SlideContent):
        lt = content.layout_type
        has_chart = content.chart and content.chart.categories and content.chart.data_series
        is_first = content.page_number == 1
        is_last = content.page_number == len(self._plan.slides)
        is_divider = (lt == "title_slide" and not is_first)

        if is_first or is_last:
            idx = self._layout_map["title_cover"]
        elif is_divider:
            idx = self._layout_map["section"]
        elif lt == "full_chart" and has_chart:
            idx = self._layout_map.get("title_only", self._layout_map["title_content"])
        elif has_chart:
            idx = self._layout_map.get("title_only", self._layout_map["title_content"])
        else:
            idx = self._layout_map["title_content"]

        layouts = self._prs.slide_layouts
        return layouts[idx] if idx < len(layouts) else layouts[0]

    def generate(self) -> bytes:
        for sc in self._plan.slides:
            self._add_slide(sc)
        buf = BytesIO()
        self._prs.save(buf)
        buf.seek(0)
        return buf.read()

    def _add_slide(self, content: SlideContent):
        lt = content.layout_type
        if lt == "title_slide":
            if content.page_number == 1:
                self._add_title_slide(content)
            else:
                self._add_chapter_divider(content)
        elif lt == "full_chart":
            self._add_full_chart_slide(content)
        elif lt == "content_with_chart":
            self._add_content_with_chart_slide(content)
        elif lt == "two_column":
            self._add_two_column_slide(content)
        else:
            self._add_content_only_slide(content)

    def _add_speaker_notes(self, slide, content: SlideContent):
        """Add AI analysis reasoning to speaker notes."""
        notes_parts = []

        if content.insight_driver:
            notes_parts.append(f"【AI 分析驅動因素】\n{content.insight_driver}")

        if content.bullet_points:
            notes_parts.append(f"【關鍵要點】\n" + "\n".join(f"• {bp}" for bp in content.bullet_points))

        if content.chart and content.chart.title:
            notes_parts.append(f"【圖表說明】\n圖表類型：{content.chart.chart_type}\n圖表標題：{content.chart.title}")
            if content.chart.categories:
                notes_parts.append(f"資料維度：{', '.join(content.chart.categories[:5])}{'...' if len(content.chart.categories) > 5 else ''}")

        notes_parts.append(f"【頁面資訊】\n第 {content.page_number} 頁 | 版面類型：{content.layout_type}")

        notes_text = "\n\n".join(notes_parts)

        # Add notes to slide
        notes_slide = slide.notes_slide
        notes_slide.notes_text_frame.text = notes_text

    # === Slide Type Methods ===

    def _add_title_slide(self, content: SlideContent):
        """Cover page — title centered, avoid bottom area."""
        slide = self._prs.slides.add_slide(self._get_smart_layout(content))
        if slide.shapes.title:
            slide.shapes.title.text = content.title
        else:
            self._add_text_box(slide, content.title,
                               Inches(2), Inches(2.5), Inches(9), Inches(1.5), Pt(32), bold=True)
        if content.subtitle:
            self._add_text_box(slide, content.subtitle,
                               Inches(2), Inches(4.2), Inches(9), Inches(0.8), Pt(16))
        self._add_speaker_notes(slide, content)

    def _add_chapter_divider(self, content: SlideContent):
        """Section divider — centered title on section layout."""
        slide = self._prs.slides.add_slide(self._get_smart_layout(content))
        if slide.shapes.title:
            slide.shapes.title.text = content.title
        else:
            self._add_text_box(slide, content.title,
                               Inches(3), Inches(3), Inches(7), Inches(1.5), Pt(28), bold=True)
        self._add_speaker_notes(slide, content)

    def _add_content_with_chart_slide(self, content: SlideContent):
        """Left: bullet points, Right: chart. Both within safe zone."""
        slide = self._prs.slides.add_slide(self._get_smart_layout(content))
        self._set_slide_title(slide, content.title)

        # Left: bullets (within safe zone)
        if content.bullet_points:
            bullets = "\n\n".join(f"• {bp}" for bp in content.bullet_points[:5])
            self._add_text_box(slide, bullets,
                               LEFT_MARGIN, CONTENT_TOP,
                               Inches(5.0), CONTENT_HEIGHT, Pt(11))

        # Right: chart (within safe zone, enough space for legend)
        if content.chart:
            self._add_native_chart(slide, content.chart,
                                   Inches(6.0), CONTENT_TOP,
                                   Inches(6.7), CONTENT_HEIGHT)

        self._add_speaker_notes(slide, content)

    def _add_full_chart_slide(self, content: SlideContent):
        """Full-width chart within safe content zone."""
        slide = self._prs.slides.add_slide(self._get_smart_layout(content))
        self._set_slide_title(slide, content.title)

        # Chart: full width but within safe vertical zone
        if content.chart:
            self._add_native_chart(slide, content.chart,
                                   LEFT_MARGIN, CONTENT_TOP,
                                   FULL_CONTENT_WIDTH, Inches(3.8))

        # Insight text below chart (still in safe zone)
        if content.insight_driver:
            self._add_text_box(slide, f"◆ {content.insight_driver}",
                               LEFT_MARGIN, Inches(5.4),
                               FULL_CONTENT_WIDTH, Inches(0.4), Pt(9), italic=True)

        self._add_speaker_notes(slide, content)

    def _add_two_column_slide(self, content: SlideContent):
        """Two-column: bullets left, chart/table right."""
        slide = self._prs.slides.add_slide(self._get_smart_layout(content))
        self._set_slide_title(slide, content.title)

        # Left column
        if content.bullet_points:
            bullets = "\n\n".join(f"• {bp}" for bp in content.bullet_points[:5])
            self._add_text_box(slide, bullets,
                               LEFT_MARGIN, CONTENT_TOP,
                               Inches(5.8), CONTENT_HEIGHT, Pt(11))

        # Right column
        if content.chart:
            self._add_native_chart(slide, content.chart,
                                   Inches(6.8), CONTENT_TOP,
                                   Inches(5.9), CONTENT_HEIGHT)
        elif content.table:
            self._add_table(slide, content.table.headers, content.table.rows,
                           left=Inches(6.8), top=CONTENT_TOP,
                           width=Inches(5.9), height=CONTENT_HEIGHT)

        self._add_speaker_notes(slide, content)

    def _add_content_only_slide(self, content: SlideContent):
        """Text-only slide within safe zone."""
        slide = self._prs.slides.add_slide(self._get_smart_layout(content))
        self._set_slide_title(slide, content.title)

        # Bullets in safe zone
        if content.bullet_points:
            bullets = "\n\n".join(f"• {bp}" for bp in content.bullet_points)
            self._add_text_box(slide, bullets,
                               LEFT_MARGIN, CONTENT_TOP,
                               FULL_CONTENT_WIDTH, Inches(3.6), Pt(12))

        # Insight in safe zone
        if content.insight_driver:
            self._add_text_box(slide, f"◆ 驅動因素：{content.insight_driver}",
                               LEFT_MARGIN, Inches(5.2),
                               FULL_CONTENT_WIDTH, Inches(0.5), Pt(10), italic=True)

        self._add_speaker_notes(slide, content)

    # === Chart & Table ===

    def _add_native_chart(self, slide, chart_spec: ChartSpec, left, top, width, height):
        """Add native editable chart with improved readability."""
        if not chart_spec.categories or not chart_spec.data_series:
            return
        try:
            ct = PPTX_CHART_TYPE_MAP.get(chart_spec.chart_type, XL_CHART_TYPE.COLUMN_CLUSTERED)
            cd = CategoryChartData()
            # Limit categories for readability (max 12)
            categories = chart_spec.categories[:12]
            cd.categories = categories

            for s in chart_spec.data_series:
                v = s.values[:len(categories)]
                while len(v) < len(categories):
                    v.append(0)
                cd.add_series(s.name, tuple(v))

            cf = slide.shapes.add_chart(ct, left, top, width, height, cd)
            ch = cf.chart

            # Legend: show if multiple series, position at bottom to save space
            ch.has_legend = len(chart_spec.data_series) > 1
            if ch.has_legend:
                from pptx.enum.chart import XL_LEGEND_POSITION
                ch.legend.position = XL_LEGEND_POSITION.BOTTOM
                ch.legend.include_in_layout = False

            # Chart title: concise
            if chart_spec.title:
                ch.has_title = True
                ch.chart_title.text_frame.text = chart_spec.title[:40]
                ch.chart_title.text_frame.paragraphs[0].font.size = Pt(9)
                ch.chart_title.text_frame.paragraphs[0].font.bold = True

            # Improve axis readability
            try:
                if hasattr(ch, 'category_axis'):
                    ch.category_axis.tick_labels.font.size = Pt(8)
                if hasattr(ch, 'value_axis'):
                    ch.value_axis.tick_labels.font.size = Pt(8)
                    ch.value_axis.has_major_gridlines = True
            except Exception:
                pass

            logger.info(f"Chart added: '{chart_spec.title}' ({chart_spec.chart_type})")
        except Exception as e:
            logger.warning(f"Chart failed '{chart_spec.title}': {e}")

    def _add_table(self, slide, headers, rows, **pos):
        """Add table with clean formatting."""
        rc = min(len(rows) + 1, 12)  # Max 12 rows for readability
        cc = len(headers)
        t = slide.shapes.add_table(rc, cc, pos["left"], pos["top"], pos["width"], pos["height"]).table
        for i, h in enumerate(headers):
            t.cell(0, i).text = h
            t.cell(0, i).text_frame.paragraphs[0].font.bold = True
            t.cell(0, i).text_frame.paragraphs[0].font.size = Pt(9)
        for ri, row in enumerate(rows[:rc - 1], 1):
            for ci, val in enumerate(row):
                if ci < cc:
                    t.cell(ri, ci).text = str(val)
                    t.cell(ri, ci).text_frame.paragraphs[0].font.size = Pt(8)

    # === Utilities ===

    def _set_slide_title(self, slide, title: str):
        """Set title in the safe title area."""
        if slide.shapes.title:
            slide.shapes.title.text = title
            # Ensure title font is readable
            for para in slide.shapes.title.text_frame.paragraphs:
                para.font.size = Pt(22)
                para.font.bold = True
        else:
            self._add_text_box(slide, title,
                               LEFT_MARGIN, TITLE_TOP,
                               FULL_CONTENT_WIDTH, TITLE_HEIGHT, Pt(22), bold=True)

    def _add_text_box(self, slide, text, left, top, width, height,
                      font_size=Pt(12), bold=False, italic=False):
        """Add text box with proper formatting and overflow protection."""
        # Truncate text to prevent overflow (estimate based on area)
        max_chars = int((width / Inches(1)) * (height / Inches(1)) * 25)
        if len(text) > max_chars:
            text = text[:max_chars - 3] + "..."

        tb = slide.shapes.add_textbox(left, top, width, height)
        tf = tb.text_frame
        tf.word_wrap = True

        # Split by newlines and add as separate paragraphs for proper spacing
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
            p.space_after = Pt(4)
