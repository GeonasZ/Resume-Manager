"""Build a page-targeted Chinese resume PDF from resume.md."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import yaml
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]

# Accent A is used by existing emphasized content and section headings.
ACCENT_COLOR = "#3F6F82"
STRONG_COLOR = ACCENT_COLOR
# Accent B is a muted complementary orange reserved for work/project titles.
TITLE_COLOR = "#B56F3A"


@dataclass(frozen=True)
class ColorTheme:
    emphasis: str = STRONG_COLOR
    section_title: str = ACCENT_COLOR
    separator: str = ACCENT_COLOR
    work_title: str = TITLE_COLOR
    project_title: str = TITLE_COLOR
    education_title: str = "#111111"


DEFAULT_THEME = ColorTheme()


@dataclass(frozen=True)
class Generation:
    name: str
    template: Path
    output: Path
    theme: ColorTheme
    font: str


@dataclass
class ContentSection:
    title: str
    items: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class Entry:
    title: str = ""
    metadata: list[tuple[str, str]] = field(default_factory=list)
    sections: list[ContentSection] = field(default_factory=list)
    loose_items: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    version: str = ""

    def value(self, key: str) -> str:
        return next((value for name, value in self.metadata if name == key), "")


class CountingCanvas(pdf_canvas.Canvas):
    def __init__(self, *args, page_counter: list[int], **kwargs):
        super().__init__(*args, **kwargs)
        self.page_counter = page_counter

    def showPage(self) -> None:
        self.page_counter[0] += 1
        super().showPage()


def available_fonts() -> list[str]:
    names = {"Arial", "SimHei", "Microsoft YaHei", "SimSun"}
    for directory in (Path(r"C:\Windows\Fonts"), Path("/usr/share/fonts"), Path("/Library/Fonts")):
        if directory.exists():
            for path in directory.rglob("*"):
                if path.suffix.lower() in {".ttf", ".ttc", ".otf"}:
                    names.add(path.stem)
    return sorted(names, key=str.casefold)


def register_font(font_name: str) -> str:
    requested = font_name.strip()
    candidates = []
    aliases = {
        "SimHei": [r"C:\Windows\Fonts\simhei.ttf"],
        "Microsoft YaHei": [r"C:\Windows\Fonts\msyh.ttf", r"C:\Windows\Fonts\msyh.ttc"],
        "SimSun": [r"C:\Windows\Fonts\simsun.ttf"],
        "Arial": [r"C:\Windows\Fonts\arial.ttf"],
    }
    candidates.extend(aliases.get(requested, []))
    for directory in (Path(r"C:\Windows\Fonts"), Path("/usr/share/fonts"), Path("/Library/Fonts")):
        if directory.exists():
            candidates.extend(str(path) for path in directory.rglob("*") if path.suffix.lower() in {".ttf", ".ttc", ".otf"} and path.stem.casefold() == requested.casefold())
    candidates.extend(FONT_CANDIDATES if requested in {"SimHei", "Microsoft YaHei", "SimSun"} else [])
    for filename in candidates:
        path = Path(filename)
        if not path.exists():
            continue
        try:
            kwargs = {"subfontIndex": 0} if path.suffix.lower() == ".ttc" else {}
            pdfmetrics.registerFont(TTFont("ResumeFont", str(path), **kwargs))
            return "ResumeFont"
        except Exception:
            continue
    print(f"Warning: font '{requested}' not found; falling back to Helvetica.", file=sys.stderr)
    return "Helvetica"


def split_front_matter(manifest: Path) -> tuple[dict, list[str]]:
    lines = manifest.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise ValueError(f"Unclosed YAML front matter in {manifest}") from exc
    metadata = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"YAML front matter in {manifest} must be a mapping")
    return metadata, lines[end + 1 :]


def expected_pages(metadata: dict, manifest: Path) -> int:
    value = metadata.get("expected_pages", 1)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
        raise ValueError(f"expected_pages in {manifest} must be an integer from 1 to 10")
    return value


def manifest_sections(
    lines: list[str], manifest: Path, project_root: Path | None = None
) -> list[tuple[str, list[tuple[Path, str | None]]]]:
    sections: list[tuple[str, list[tuple[Path, str | None]]]] = []
    current_title = ""
    current_files: list[tuple[Path, str | None]] = []

    for line in lines:
        if line.startswith("## "):
            if current_files:
                sections.append((current_title, current_files))
            current_title = line[3:].strip()
            current_files = []
            continue
        match = re.match(r"^\s*-\s+(?:include:\s*)?`?([^`\s]+\.md)`?(?:\s+\[([^\]]+)\])?\s*$", line)
        if not match:
            continue
        path = ((project_root or manifest.parent) / match.group(1)).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Manifest entry does not exist: {match.group(1)}")
        selector = match.group(2).strip() if match.group(2) else None
        current_files.append((path, selector))

    if current_files:
        sections.append((current_title, current_files))
    if not sections:
        raise ValueError(f"No Markdown entries found in {manifest}")
    return sections


def parse_entry(path: Path, selector: str | None = None) -> Entry:
    lines = path.read_text(encoding="utf-8").splitlines()
    version_starts = [(index, line[3:].strip()) for index, line in enumerate(lines) if line.startswith("## ")]
    if not version_starts:
        raise ValueError(f"No level-2 version headings found in {path}")
    names = [name for _, name in version_starts]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate level-2 version headings in {path}: {names}")
    selected = selector or names[0]
    if selected not in names:
        raise ValueError(f"Version '{selected}' not found in {path}. Available versions: {', '.join(names)}")

    selected_index = names.index(selected)
    start = version_starts[selected_index][0] + 1
    end = version_starts[selected_index + 1][0] if selected_index + 1 < len(version_starts) else len(lines)
    entry = Entry(version=selected)
    current: ContentSection | None = None

    # Shared metadata is used only when the selected content itself contains
    # CJK text. A template/version is therefore self-describing by content;
    # Parsing is driven by semantic aliases and selected content.
    selected_lines = lines[start:end]
    selected_has_cjk = any(re.search(r"[\u4e00-\u9fff]", line) for line in selected_lines)
    preamble = lines[1 : version_starts[0][0]] if selected_has_cjk else []
    for raw in preamble + selected_lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            continue
        elif line.startswith("#### "):
            current = ContentSection(line[5:].strip())
            entry.sections.append(current)
        elif line.startswith("### "):
            heading = line[4:].strip()
            field_match = re.match(r"^([^：:]+)\s*[：:]\s*(.+)$", heading)
            if field_match:
                field_name = field_match.group(1).strip()
                field_value = field_match.group(2).strip()
                if field_name.casefold() in {"title", "标题", "项目名称", "project name"}:
                    entry.title = field_value
                else:
                    entry.metadata.append((field_name, field_value))
                current = None
            elif heading.casefold() in {"content", "body", "内容", "正文"}:
                current = ContentSection(heading)
                entry.sections.append(current)
            else:
                raise ValueError(
                    f"Unsupported level-3 heading '{heading}' in {path}; use a functional field or Content/Body"
                )
        elif re.match(r"^\d+\.\s+", line):
            text = re.sub(r"^\d+\.\s+", "", line)
            (current.items if current else entry.loose_items).append(text)
        elif line.startswith("- "):
            text = line[2:].strip()
            match = re.match(r"^([^：:]+)[：:]\s*(.*)$", text)
            if current:
                current.items.append(text)
            elif match:
                entry.metadata.append((match.group(1).strip(), match.group(2).strip()))
            else:
                entry.loose_items.append(text)
        elif current:
            current.paragraphs.append(line)
        else:
            entry.paragraphs.append(line)
    title_keys = ("标题", "Title", "项目名称", "Project Name")
    structured_title = next((entry.value(key) for key in title_keys if entry.value(key)), "")
    if structured_title:
        entry.title = structured_title
    if not entry.title:
        raise ValueError(f"Selected version '{selected}' in {path} must define a title with '### Title: ...'")
    return entry


def validate_entry_render(entry: Entry, theme: ColorTheme) -> None:
    """Parse every renderable field once so errors can be attributed to an entry."""
    style = ParagraphStyle("entry_preflight", fontName="Helvetica")
    texts = [entry.title, *(value for _, value in entry.metadata), *entry.paragraphs, *entry.loose_items]
    for section in entry.sections:
        texts.extend(section.paragraphs)
        texts.extend(section.items)
    for text in texts:
        Paragraph(format_inline(text, theme.emphasis), style)


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_math(text: str) -> str:
    """Convert a small, safe subset of Markdown math into ReportLab markup."""
    def replace_expression(match: re.Match[str]) -> str:
        expression = match.group(1)
        expression = re.sub(
            r"\^(\{[^{}]+\}|[A-Za-z0-9+\-]+)",
            lambda item: f'<super>{item.group(1).strip("{}")}</super>',
            expression,
        )
        expression = re.sub(
            r"_(\{[^{}]+\}|[A-Za-z0-9+\-]+)",
            lambda item: f'<sub>{item.group(1).strip("{}")}</sub>',
            expression,
        )
        return expression

    return re.sub(r"\$(.+?)\$", replace_expression, text)


def format_inline(text: str, emphasis_color: str = STRONG_COLOR) -> str:
    escaped = escape(text)
    formatted = re.sub(r"\*\*(.+?)\*\*", rf'<b><font color="{emphasis_color}">\1</font></b>', escaped)
    return format_math(formatted)


def scaled_styles(font: str, scale: float, theme: ColorTheme) -> dict[str, ParagraphStyle]:
    def style(name: str, size: float, leading: float, **kwargs) -> ParagraphStyle:
        return ParagraphStyle(name, fontName=font, fontSize=size * scale, leading=leading * scale, **kwargs)

    return {
        "name": style("name", 21, 24, alignment=TA_CENTER, textColor=colors.HexColor("#111111"), spaceAfter=3 * scale),
        "contact": style("contact", 8.2, 10, alignment=TA_CENTER, textColor=colors.HexColor("#444444"), spaceAfter=6 * scale),
        "section": style("section", 11.5, 13.5, textColor=colors.HexColor(theme.section_title)),
        "entry_title": style("entry_title", 8.5, 10, textColor=colors.HexColor("#111111")),
        # Dates are short metadata and should stay on one line when the
        # page-fit scale increases.  The column width is also widened
        # dynamically in entry_header based on the measured date width.
        "entry_meta": style(
            "entry_meta", 7.2, 9, alignment=TA_RIGHT,
            textColor=colors.HexColor("#555555"), wordWrap=None, splitLongWords=0,
        ),
        "subheading": style("subheading", 7.5, 8.8, textColor=colors.HexColor("#555555"), spaceBefore=0.6 * scale, spaceAfter=0, keepWithNext=True),
        "body": style("body", 7.2, 8.8, alignment=TA_LEFT, wordWrap="CJK", textColor=colors.HexColor("#222222"), spaceAfter=0.8 * scale),
        "item": style("item", 7.05, 8.55, leftIndent=7 * scale, firstLineIndent=-5 * scale, wordWrap="CJK", textColor=colors.HexColor("#222222"), spaceAfter=0.25 * scale),
        "education_detail": style("education_detail", 7.05, 8.55, wordWrap="CJK", textColor=colors.HexColor("#333333"), spaceAfter=1.5 * scale),
    }


def section_heading(title: str, styles: dict, width: float, scale: float, theme: ColorTheme) -> Table:
    display = {"个人信息": "个人总结", "教育经历": "教育背景", "实习经历": "工作经历"}.get(title, title)
    table = Table([[Paragraph(escape(display), styles["section"])]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1.2 * scale),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8 * scale),
                ("LINEBELOW", (0, 0), (-1, -1), 0.7, colors.HexColor(theme.separator)),
            ]
        )
    )
    table.spaceBefore = 2.5 * scale
    table.spaceAfter = 2.5 * scale
    table.keepWithNext = True
    return table


def entry_header(
    entry: Entry,
    styles: dict,
    width: float,
    scale: float,
    education: bool = False,
    title_color: str | None = None,
    emphasis_color: str = STRONG_COLOR,
) -> Table:
    if education:
        title = escape(entry.title)
        if title_color:
            title = f'<font color="{title_color}">{title}</font>'
        left_parts = [f"<b>{title}</b>"]
        degree_values = [entry.value(key) for key in ("专业", "Major", "学位", "Degree") if entry.value(key)]
        degree_separator = "，" if any(re.search(r"[\u4e00-\u9fff]", value) for value in degree_values) else ", "
        degree = degree_separator.join(degree_values)
        if degree:
            left_parts.append(format_inline(degree, emphasis_color))
        right = entry.value("时间") or entry.value("Time")
    else:
        role = entry.value("职位") or entry.value("角色") or entry.value("类型") or entry.value("Position") or entry.value("Role") or entry.value("Type")
        title = escape(entry.title)
        if title_color:
            title = f'<font color="{title_color}">{title}</font>'
        left_parts = [f"<b>{title}</b>"]
        if role:
            left_parts.append(format_inline(role, emphasis_color))
        right = entry.value("时间") or entry.value("Time")
    # Reserve enough horizontal room for the complete date instead of
    # letting ReportLab break it into two lines at larger font scales.
    meta_width = width * 0.23
    if right:
        measured = pdfmetrics.stringWidth(str(right), styles["entry_meta"].fontName, styles["entry_meta"].fontSize)
        meta_width = max(meta_width, min(width * 0.36, measured + 4 * scale))
    meta_width = min(meta_width, width * 0.42)
    table = Table(
        [[Paragraph(" | ".join(left_parts), styles["entry_title"]), Paragraph(format_inline(right, emphasis_color), styles["entry_meta"])]],
        colWidths=[width - meta_width, meta_width],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5 * scale),
            ]
        )
    )
    table.keepWithNext = True
    return table


def entry_content(entry: Entry, styles: dict, scale: float, emphasis_color: str) -> list:
    result = []
    for paragraph in entry.paragraphs:
        result.append(Paragraph(format_inline(paragraph, emphasis_color), styles["body"]))
    for item in entry.loose_items:
        result.append(Paragraph("- " + format_inline(item, emphasis_color), styles["item"]))
    for section in entry.sections:
        result.append(Paragraph(escape(section.title), styles["subheading"]))
        for paragraph in section.paragraphs:
            result.append(Paragraph(format_inline(paragraph, emphasis_color), styles["body"]))
        for item in section.items:
            result.append(Paragraph("- " + format_inline(item, emphasis_color), styles["item"]))
    result.append(Spacer(1, 1.6 * scale))
    return result


def make_story(groups: list[tuple[str, list[Entry]]], font: str, scale: float, width: float, theme: ColorTheme) -> list:
    aliases = {
        "个人信息": ("个人信息", "Personal Information", "Profile", "About"),
        "教育经历": ("教育经历", "教育背景", "Education", "Academic Experience"),
        "实习经历": ("实习经历", "工作经历", "Work Experience", "Experience"),
        "项目经历": ("项目经历", "Projects", "Project Experience"),
        "技能": ("技能", "Skills", "Technical Skills"),
    }
    by_group = {title: entries for title, entries in groups}
    def group(name: str) -> list[Entry]:
        return next(by_group[key] for key in aliases[name] if key in by_group)
    personal = group("个人信息")
    profile = next(entry for entry in personal if entry.title in ("个人概况", "Profile", "About"))
    skills = next(entry for entry in personal if entry.title in ("技能", "Skills", "Technical Skills"))
    label = {
        "姓名": ("姓名", "Name"), "电话": ("电话", "Phone"), "邮箱": ("邮箱", "Email"),
        "求职方向": ("求职方向", "Target Role"), "期望城市": ("期望城市", "Preferred Locations"),
        "期望薪资": ("期望薪资", "Salary Expectation"),
    }
    def value(entry: Entry, key: str) -> str:
        return next((entry.value(candidate) for candidate in label.get(key, (key,)) if entry.value(candidate)), "")
    heading = {
        "个人信息": "个人总结", "教育经历": "教育背景", "实习经历": "工作经历", "项目经历": "项目经历", "技能": "技能",
        "Personal Information": "Personal Summary", "Education": "Education", "Work Experience": "Work Experience", "Projects": "Projects", "Skills": "Skills",
    }
    styles = scaled_styles(font, scale, theme)

    contact = " | ".join(
        [
            value(profile, "电话"), value(profile, "邮箱"), value(profile, "求职方向"),
            value(profile, "期望城市"), f"{'Salary' if not value(profile, '期望薪资') and value(profile, 'Salary Expectation') else '期望薪资'} {value(profile, '期望薪资') or value(profile, 'Salary Expectation')}",
        ]
    )
    story = [Paragraph(format_inline(value(profile, "姓名"), theme.emphasis), styles["name"]), Paragraph(format_inline(contact, theme.emphasis), styles["contact"])]

    personal_group_title = next(key for key in aliases["个人信息"] if key in by_group)
    story.append(section_heading(heading.get(personal_group_title, personal_group_title), styles, width, scale, theme))
    for paragraph in profile.paragraphs:
        story.append(Paragraph(format_inline(paragraph, theme.emphasis), styles["body"]))
    for section in profile.sections:
        for paragraph in section.paragraphs:
            story.append(Paragraph(format_inline(paragraph, theme.emphasis), styles["body"]))

    education_group_title = next(key for key in aliases["教育经历"] if key in by_group)
    story.append(section_heading(heading.get(education_group_title, education_group_title), styles, width, scale, theme))
    for entry in group("教育经历"):
        story.append(entry_header(entry, styles, width, scale, education=True, title_color=theme.education_title, emphasis_color=theme.emphasis))
        details = []
        education_keys = (("专业排名", "Ranking"), ("主修课程", "Relevant Coursework"))
        for chinese_key, english_key in education_keys:
            detail_value = entry.value(chinese_key) or entry.value(english_key)
            if detail_value:
                details.append(f"{english_key}: {detail_value}" if entry.value(english_key) else f"{chinese_key}：{detail_value}")
        if details:
            story.append(Paragraph(" | ".join(format_inline(value, theme.emphasis) for value in details), styles["education_detail"]))
        story.extend(entry_content(entry, styles, scale, theme.emphasis))

    english_template = any(key in by_group for key in ("Personal Information", "Education", "Work Experience", "Projects"))
    story.append(section_heading("Skills" if english_template else "技能", styles, width, scale, theme))
    story.extend(entry_content(skills, styles, scale, theme.emphasis))
    if skills.metadata:
        for key, value in skills.metadata:
            story.append(Paragraph(f"- <b>{escape(key)}：</b>{format_inline(value, theme.emphasis)}", styles["item"]))

    work_group_title = next(key for key in aliases["实习经历"] if key in by_group)
    story.append(section_heading(heading.get(work_group_title, work_group_title), styles, width, scale, theme))
    for entry in group("实习经历"):
        story.append(entry_header(entry, styles, width, scale, title_color=theme.work_title, emphasis_color=theme.emphasis))
        story.extend(entry_content(entry, styles, scale, theme.emphasis))

    project_group_title = next(key for key in aliases["项目经历"] if key in by_group)
    story.append(section_heading(heading.get(project_group_title, project_group_title), styles, width, scale, theme))
    for entry in group("项目经历"):
        story.append(entry_header(entry, styles, width, scale, title_color=theme.project_title, emphasis_color=theme.emphasis))
        story.extend(entry_content(entry, styles, scale, theme.emphasis))
    return story


def render_document(target, groups: list[tuple[str, list[Entry]]], font: str, scale: float, theme: ColorTheme) -> int:
    margins = 15 * mm
    width = A4[0] - 2 * margins
    counter = [0]
    doc = SimpleDocTemplate(
        target,
        pagesize=A4,
        leftMargin=margins,
        rightMargin=margins,
        topMargin=11 * mm,
        bottomMargin=9 * mm,
        title="Resume",
        author="Resume Generation",
        allowSplitting=True,
    )
    doc.build(
        make_story(groups, font, scale, width, theme),
        canvasmaker=lambda *args, **kwargs: CountingCanvas(*args, page_counter=counter, **kwargs),
    )
    return counter[0]


def choose_scale(groups: list[tuple[str, list[Entry]]], font: str, target_pages: int, theme: ColorTheme) -> tuple[float, int]:
    low = 0.5
    low_pages = render_document(BytesIO(), groups, font, low, theme)
    if low_pages > target_pages:
        raise RuntimeError(f"Content needs {low_pages} pages even at the minimum font scale; expected_pages is {target_pages}")

    best_scale = low
    best_pages = low_pages
    high = 1.0
    while high <= 3.0:
        pages = render_document(BytesIO(), groups, font, high, theme)
        if pages > target_pages:
            break
        best_scale, best_pages = high, pages
        high *= 1.25
    else:
        return best_scale, best_pages

    low = best_scale
    for _ in range(14):
        middle = (low + high) / 2
        pages = render_document(BytesIO(), groups, font, middle, theme)
        if pages <= target_pages:
            best_scale, best_pages = middle, pages
            low = middle
        else:
            high = middle
    return best_scale * 0.995, best_pages


COLOR_KEYS = {
    "emphasis": "emphasis",
    "section_title": "section_title",
    "separator": "separator",
    "work_title": "work_title",
    "project_title": "project_title",
    "education_title": "education_title",
}


def validated_color(value: object, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise ValueError(f"{field} must be a #RRGGBB color")
    return value.upper()


def color_theme(values: object, base: ColorTheme = DEFAULT_THEME) -> ColorTheme:
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise ValueError("colors must be a mapping")
    resolved = {field: getattr(base, field) for field in COLOR_KEYS.values()}
    for key, value in values.items():
        if key not in COLOR_KEYS:
            raise ValueError(f"unsupported color key: {key}")
        field = COLOR_KEYS[key]
        resolved[field] = validated_color(value, f"colors.{key}")
    return ColorTheme(**resolved)


def relative_path(root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must stay within the project root")
    return (root / path).resolve()


def load_generations(config_path: Path) -> list[Generation]:
    root = config_path.parent.resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config.yaml must contain a mapping")
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("defaults must be a mapping")
    base_theme = color_theme(defaults.get("colors"))
    raw_generations = raw.get("generations")
    if not isinstance(raw_generations, list) or not raw_generations:
        raise ValueError("generations must be a non-empty list")

    generations = []
    names = set()
    outputs = set()
    for index, item in enumerate(raw_generations, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"generations[{index}] must be a mapping")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"generations[{index}].name must be a non-empty string")
        if name in names:
            raise ValueError(f"duplicate generation name: {name}")
        template = relative_path(root, item.get("template"), f"generations[{index}].template")
        if not template.is_file():
            raise FileNotFoundError(f"template does not exist: {template}")
        output_value = item.get("output")
        output_relative = Path(output_value) if isinstance(output_value, str) else None
        if output_relative is None or output_relative.is_absolute() or ".." in output_relative.parts:
            raise ValueError(f"generations[{index}].output must be a relative path")
        if output_relative.parts[:1] != ("resumes_output",):
            output_relative = Path("resumes_output") / output_relative
        output = (root / output_relative).resolve()
        output_root = (root / "resumes_output").resolve()
        if output_root not in output.parents:
            raise ValueError(f"generations[{index}].output must be inside resumes_output")
        if output in outputs:
            raise ValueError(f"duplicate generation output: {output_relative}")
        names.add(name)
        outputs.add(output)
        font = item.get("font")
        if not isinstance(font, str) or not font.strip():
            raise ValueError(f"generations[{index}].font must be a non-empty installed font name")
        generations.append(Generation(name, template, output, color_theme(item.get("colors"), base_theme), font.strip()))
    return generations


def build(manifest: Path, output: Path, theme: ColorTheme = DEFAULT_THEME, project_root: Path | None = None, font_name: str = "SimHei") -> None:
    project_root = (project_root or manifest.parent).resolve()
    metadata, lines = split_front_matter(manifest)
    target_pages = expected_pages(metadata, manifest)
    groups = []
    failures = []
    for title, items in manifest_sections(lines, manifest, project_root):
        entries = []
        for path, selector in items:
            label = str(path.relative_to(project_root))
            try:
                entry = parse_entry(path, selector)
                validate_entry_render(entry, theme)
            except Exception as exc:
                print(f"[FAIL] {label}: {exc}", file=sys.stderr)
                failures.append(label)
                continue
            entries.append(entry)
            print(f"[OK]   {label} [{entry.version}] ready for rendering")
        groups.append((title, entries))
    if failures:
        raise RuntimeError(f"{len(failures)} file(s) failed preflight; PDF was not written")
    font = register_font(font_name)
    scale, _ = choose_scale(groups, font, target_pages, theme)
    output.parent.mkdir(parents=True, exist_ok=True)
    pages = render_document(str(output), groups, font, scale, theme)
    if pages != target_pages:
        print(f"Warning: generated {pages} pages for expected_pages={target_pages} at maximum scale {scale:.3f}", file=sys.stderr)
    print(f"[OK]   PDF rendered: {output} ({pages} pages, font scale {scale:.3f})")


def build_config(config_path: Path) -> None:
    generations = load_generations(config_path)
    root = config_path.parent.resolve()
    failures = 0
    for generation in generations:
        print(f"[GEN]  {generation.name}: {generation.template.relative_to(root)} -> {generation.output.relative_to(root)}")
        try:
            build(generation.template, generation.output, generation.theme, root, generation.font)
        except Exception as exc:
            failures += 1
            print(f"[FAIL] Generation {generation.name}: {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError(f"{failures} generation(s) failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, help="build one template directly; omit to use config.yaml")
    parser.add_argument("-o", "--output", type=Path, default=Path("resume.pdf"))
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()
    try:
        if args.manifest:
            build(args.manifest.resolve(), args.output.resolve(), project_root=Path.cwd().resolve())
        else:
            build_config(args.config.resolve())
    except Exception as exc:
        print(f"[FAIL] Build failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
