"""Write a .docx by hand as a zip of OOXML parts.

A resume is paragraphs, runs, and a handful of named styles. That is small
enough to emit directly, which removes the python-docx dependency without
losing anything a resume needs.

Layout is fixed by the ATS rules in lint.py: one column, 0.75in margins,
10.5pt Calibri body, black text, no tables, no images.
"""

import re
import zipfile

BODY_PT = 21          # half-points: 10.5pt
NAME_PT = 32          # half-points: 16pt
HEADING_PT = 23       # half-points: 11.5pt
MARGIN_TWIPS = 1080   # 0.75in
LINE_TWIPS = 260      # 13pt exact line spacing
PAGE_W = 12240        # US Letter, twips
CONTENT_W = PAGE_W - 2 * MARGIN_TWIPS

_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def _esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _run(text, *, bold=False, size=None, italic=False):
    props = []
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if size:
        props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    # xml:space=preserve so leading/trailing spaces survive the round trip.
    return f'<w:r>{rpr}<w:t xml:space="preserve">{_esc(text)}</w:t></w:r>'


def _para(runs, *, style=None, align=None, spacing_after=60, numid=None,
          border_bottom=False, tabs=None, line=LINE_TWIPS):
    props = []
    if style:
        props.append(f'<w:pStyle w:val="{style}"/>')
    if numid:
        props.append(
            f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{numid}"/></w:numPr>'
        )
    if border_bottom:
        props.append(
            '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" '
            'w:color="808080"/></w:pBdr>'
        )
    if tabs:
        stops = "".join(
            f'<w:tab w:val="right" w:pos="{pos}"/>' for pos in tabs
        )
        props.append(f"<w:tabs>{stops}</w:tabs>")
    spacing = f'<w:spacing w:after="{spacing_after}" w:line="{line}" w:lineRule="exact"/>'
    props.append(spacing)
    if align:
        props.append(f'<w:jc w:val="{align}"/>')
    return f"<w:p><w:pPr>{''.join(props)}</w:pPr>{''.join(runs)}</w:p>"


def _split_contact(line):
    """Split a contact line on pipes/commas so each item gets its own run.

    Left as plain text runs rather than hyperlinks: an underlined colored link
    reads as decoration to a parser and the URL text is what matters.
    """
    parts = re.split(r"\s*[|·•]\s*|\s{3,}", line)
    return [p.strip() for p in parts if p.strip()]


def _blocks(markdown):
    """Markdown -> list of block dicts the writer understands."""
    blocks = []
    for raw in (markdown or "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            blocks.append({
                "type": "heading" if level <= 2 else "role",
                "level": level,
                "text": stripped[level:].strip(),
            })
            continue

        if stripped.startswith(("- ", "* ")):
            blocks.append({"type": "bullet", "text": stripped[2:].strip()})
            continue

        if re.match(r"^\s*(---+|===+|\*\*\*+)\s*$", stripped):
            blocks.append({"type": "rule"})
            continue

        blocks.append({"type": "para", "text": stripped})
    return blocks


def _document_xml(blocks):
    body = []

    first_heading = True
    pending_rule = False

    for block in blocks:
        kind = block["type"]

        if kind == "rule":
            pending_rule = True
            continue

        if kind == "heading" and block["level"] == 1:
            body.append(_para(
                [_run(block["text"], bold=True, size=NAME_PT)],
                align="center", spacing_after=40,
            ))
            first_heading = False
            continue

        if kind == "heading":
            body.append(_para(
                [_run(block["text"].upper(), bold=True, size=HEADING_PT)],
                spacing_after=100,
                border_bottom=True,
            ))
            pending_rule = False
            continue

        if kind == "role":
            text = block["text"]
            # A role heading often carries "Title – Company – 2021 – Present".
            # Right-align the trailing dates with a tab stop rather than a table.
            m = re.match(r"^(.*?)[\s|]+((?:19|20)\d{2}\s*[–-]\s*(?:(?:19|20)\d{2}|Present|Current|Now))$",
                         text, re.IGNORECASE)
            if m:
                body.append(_para(
                    [_run(m.group(1).strip(), bold=True),
                     _run("\t" + m.group(2).strip())],
                    spacing_after=40, tabs=[CONTENT_W],
                ))
            else:
                body.append(_para([_run(text, bold=True)], spacing_after=40))
            pending_rule = False
            continue

        if kind == "bullet":
            body.append(_para(
                [_run(block["text"])],
                style="ResumeBullet", numid=1, spacing_after=40,
            ))
            pending_rule = False
            continue

        # Paragraph. The first non-heading line under a role is a company or
        # location line; keep it plain and compact.
        runs = _run(block["text"])
        body.append(_para([runs], spacing_after=60))
        pending_rule = False

    sect = (
        f'<w:sectPr><w:pgSz w:w="{PAGE_W}" w:h="15840"/>'
        f'<w:pgMar w:top="{MARGIN_TWIPS}" w:right="{MARGIN_TWIPS}" '
        f'w:bottom="{MARGIN_TWIPS}" w:left="{MARGIN_TWIPS}" '
        f'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
    )

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document {_NS}><w:body>{"".join(body)}{sect}</w:body></w:document>'
    )


def _styles_xml():
    def style(sid, name, based, props, rpr=""):
        return (
            f'<w:style w:type="paragraph" w:styleId="{sid}">'
            f'<w:name w:val="{name}"/>'
            + (f'<w:basedOn w:val="{based}"/>' if based else "")
            + f"<w:pPr>{props}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>"
        )

    default_rpr = (
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
        f'<w:sz w:val="{BODY_PT}"/><w:szCs w:val="{BODY_PT}"/>'
        '<w:color w:val="000000"/>'
    )
    default_ppr = (
        f'<w:spacing w:after="60" w:line="{LINE_TWIPS}" w:lineRule="exact"/>'
    )

    styles = [
        '<w:docDefaults><w:rPrDefault><w:rPr>' + default_rpr +
        '</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>' + default_ppr +
        '</w:pPr></w:pPrDefault></w:docDefaults>',
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:pPr>' + default_ppr + '</w:pPr>'
        '<w:rPr>' + default_rpr + '</w:rPr></w:style>',
        style(
            "ResumeBullet", "Resume Bullet", "Normal",
            '<w:ind w:left="360" w:hanging="180"/>'
            f'<w:spacing w:after="40" w:line="{LINE_TWIPS}" w:lineRule="exact"/>'
            '<w:contextualSpacing/>',
        ),
    ]

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:styles {_NS}>{"".join(styles)}</w:styles>'
    )


def _numbering_xml():
    levels = []
    for i, (char, font) in enumerate([("•", "Symbol"), ("o", "Courier New"),
                                      ("▪", "Wingdings")]):
        ind = 360 + i * 360
        levels.append(
            f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/>'
            f'<w:numFmt w:val="bullet"/><w:lvlText w:val="{char}"/>'
            f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{ind}" '
            f'w:hanging="180"/></w:pPr><w:rPr><w:rFonts w:ascii="{font}" '
            f'w:hAnsi="{font}" w:hint="default"/></w:rPr></w:lvl>'
        )
    abstract = (
        f'<w:abstractNum w:abstractNumId="0">'
        f'<w:multiLevelType w:val="hybridMultilevel"/>{"".join(levels)}'
        f'</w:abstractNum>'
    )
    num = '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:numbering {_NS}>{abstract}{num}</w:numbering>'
    )


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    "</Types>"
)

_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
    "</Relationships>"
)

_DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
    "</Relationships>"
)


def _core_xml(title):
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{_esc(title)}</dc:title>"
        "<cp:revision>1</cp:revision>"
        "</cp:coreProperties>"
    )


_APP_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
    'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    "<Application>resume-forge</Application></Properties>"
)


def build_docx(markdown, title="Resume"):
    """Return .docx bytes from a markdown resume."""
    blocks = _blocks(markdown)
    parts = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "docProps/core.xml": _core_xml(title),
        "docProps/app.xml": _APP_XML,
        "word/_rels/document.xml.rels": _DOC_RELS,
        "word/document.xml": _document_xml(blocks),
        "word/styles.xml": _styles_xml(),
        "word/numbering.xml": _numbering_xml(),
    }

    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in parts.items():
            zf.writestr(name, content)
    return buf.getvalue()