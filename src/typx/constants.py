from __future__ import annotations

APP_NAME = "typx"
VERSION = "0.1.0"
TYPST_BASELINE = "0.15.1"
OOXML_BASELINE = "ECMA-376 5th ed. / ISO/IEC 29500:2016+2021 OPC / MS-DOCX 23.0"
ROUNDTRIP_FORMAT = 1
TYPX_NAMESPACE = "urn:typx:roundtrip:1"
TYPX_RELATIONSHIP_TYPE = "urn:typx:relationships:source"
TYPX_RELATIONSHIP_PREFIXES = ("urn:typx:",)

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
    "w16": "http://schemas.microsoft.com/office/word/2018/wordml",
    "w16cid": "http://schemas.microsoft.com/office/word/2016/wordml/cid",
    "w16cex": "http://schemas.microsoft.com/office/word/2018/wordml/cex",
    "w16du": "http://schemas.microsoft.com/office/word/2023/wordml/word16du",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "wp14": "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcmitype": "http://purl.org/dc/dcmitype/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
    "cust": "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties",
    "ds": "http://schemas.openxmlformats.org/officeDocument/2006/customXml",
    "xml": "http://www.w3.org/XML/1998/namespace",
    "typx": TYPX_NAMESPACE,
}

# ISO/IEC 29500 Strict namespace URIs are normalized to the Transitional
# namespace vocabulary at parse time. The writer intentionally emits the
# broadly interoperable Transitional profile.
STRICT_TO_TRANSITIONAL_NS = {
    "http://purl.oclc.org/ooxml/wordprocessingml/main": NS["w"],
    "http://purl.oclc.org/ooxml/officeDocument/relationships": NS["r"],
    "http://purl.oclc.org/ooxml/package/relationships": NS["rel"],
    "http://purl.oclc.org/ooxml/package/content-types": NS["ct"],
    "http://purl.oclc.org/ooxml/drawingml/main": NS["a"],
    "http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing": NS["wp"],
    "http://purl.oclc.org/ooxml/drawingml/picture": NS["pic"],
    "http://purl.oclc.org/ooxml/officeDocument/math": NS["m"],
    "http://purl.oclc.org/ooxml/package/metadata/core-properties": NS["cp"],
    "http://purl.oclc.org/ooxml/officeDocument/extended-properties": NS["ep"],
    "http://purl.oclc.org/ooxml/officeDocument/custom-properties": NS["cust"],
    "http://purl.oclc.org/ooxml/officeDocument/docPropsVTypes": NS["vt"],
}

STRICT_RELATIONSHIP_PREFIXES = {
    "http://purl.oclc.org/ooxml/officeDocument/relationships/":
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/",
    "http://purl.oclc.org/ooxml/package/relationships/metadata/":
        "http://schemas.openxmlformats.org/package/2006/relationships/metadata/",
}

REL_TYPES = {
    "office_document": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
    "core_properties": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
    "extended_properties": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties",
    "custom_properties": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties",
    "styles": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
    "settings": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
    "numbering": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering",
    "font_table": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable",
    "theme": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
    "image": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    "hyperlink": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
    "footnotes": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes",
    "endnotes": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes",
    "comments": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments",
    "header": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header",
    "footer": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer",
    "custom_xml": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml",
    "chart": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart",
    "ole_object": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject",
    "alt_chunk": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk",
}

CONTENT_TYPES = {
    "document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "styles": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
    "settings": "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
    "numbering": "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml",
    "font_table": "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml",
    "theme": "application/vnd.openxmlformats-officedocument.theme+xml",
    "footnotes": "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
    "endnotes": "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml",
    "comments": "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
    "header": "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
    "footer": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
    "core": "application/vnd.openxmlformats-package.core-properties+xml",
    "extended": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
    "custom": "application/vnd.openxmlformats-officedocument.custom-properties+xml",
    "custom_xml": "application/xml",
}

MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".svg": "image/svg+xml",
    ".emf": "image/x-emf",
    ".wmf": "image/x-wmf",
    ".webp": "image/webp",
}

EXT_BY_MIME = {
    value: key for key, value in MIME_BY_EXT.items()
}
EXT_BY_MIME["image/jpeg"] = ".jpg"

EMU_PER_INCH = 914400
TWIPS_PER_INCH = 1440
POINTS_PER_INCH = 72.0

for _prefix, _uri in NS.items():
    try:
        import xml.etree.ElementTree as _ET
        _ET.register_namespace(_prefix if _prefix != "rel" else "", _uri)
    except ValueError:
        pass
