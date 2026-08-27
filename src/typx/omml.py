from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

from .util import attr, child, children, find_balanced, local_name, qn, split_top_level, text_from_inlines


UNICODE_TO_TYPST = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "omicron",
    "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon",
    "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "Gamma", "Δ": "Delta", "Θ": "Theta", "Λ": "Lambda", "Ξ": "Xi",
    "Π": "Pi", "Σ": "Sigma", "Υ": "Upsilon", "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega",
    "∞": "infinity", "∑": "sum", "∏": "product", "∫": "integral",
    "∬": "integral.double", "∭": "integral.triple", "∮": "integral.cont",
    "√": "sqrt", "∂": "diff", "∇": "nabla", "±": "plus.minus", "∓": "minus.plus",
    "×": "times", "÷": "div", "·": "dot.op", "∘": "compose",
    "≤": "lt.eq", "≥": "gt.eq", "≠": "eq.not", "≈": "approx", "≡": "equiv",
    "∈": "in", "∉": "in.not", "∋": "ni", "⊂": "subset", "⊆": "subset.eq",
    "⊃": "supset", "⊇": "supset.eq", "∪": "union", "∩": "inter",
    "∧": "and", "∨": "or", "¬": "not", "⇒": "arrow.r.double", "⇔": "arrow.l.r.double",
    "→": "arrow.r", "←": "arrow.l", "↔": "arrow.l.r", "↦": "arrow.r.bar",
    "∴": "therefore", "∵": "because", "∅": "emptyset", "ℕ": "NN", "ℤ": "ZZ",
    "ℚ": "QQ", "ℝ": "RR", "ℂ": "CC", "ℙ": "PP", "ℓ": "ell",
}

TYPST_TO_UNICODE = {value: key for key, value in UNICODE_TO_TYPST.items()}
TYPST_TO_UNICODE.update({
    "arrow.r.long": "⟶", "arrow.l.long": "⟵", "arrow.l.r.long": "⟷",
    "dots.h": "…", "dots.v": "⋮", "dots.down": "⋱", "dots.up": "⋰",
    "degree": "°", "prime": "′", "prime.double": "″", "aleph": "ℵ",
    "hbar": "ℏ", "planck": "ℎ", "Re": "ℜ", "Im": "ℑ",
})

NARY_CHARS = {
    "sum": "∑", "product": "∏", "integral": "∫", "integral.double": "∬",
    "integral.triple": "∭", "integral.cont": "∮", "union.big": "⋃",
    "inter.big": "⋂", "and.big": "⋀", "or.big": "⋁",
}

DELIM_TYPST = {
    "(": "(", ")": ")", "[": "[", "]": "]", "{": "{", "}": "}",
    "|": "|", "‖": "||", "⌊": "floor.l", "⌋": "floor.r",
    "⌈": "ceil.l", "⌉": "ceil.r", "⟨": "angle.l", "⟩": "angle.r",
}


def _typst_symbol_text(text: str) -> str:
    chunks: list[str] = []
    for char in text:
        mapped = UNICODE_TO_TYPST.get(char)
        if mapped:
            if chunks and not chunks[-1].endswith(" "):
                chunks.append(" ")
            chunks.append(mapped)
            chunks.append(" ")
        else:
            chunks.append(char)
    return "".join(chunks).strip()


def omml_to_typst(element: ET.Element | None) -> str:
    if element is None:
        return ""
    tag = local_name(element.tag)
    if tag in {"oMath", "oMathPara", "e", "num", "den", "sub", "sup", "deg",
               "fName", "lim", "mr", "mc", "box", "borderBox"}:
        return " ".join(filter(None, (omml_to_typst(item) for item in element))).strip()
    if tag in {"r", "t"}:
        text = "".join(element.itertext()) if tag == "r" else (element.text or "")
        return _typst_symbol_text(text)
    if tag == "f":
        numerator = omml_to_typst(child(element, "num", "m"))
        denominator = omml_to_typst(child(element, "den", "m"))
        fpr = child(element, "fPr", "m")
        ftype = attr(child(fpr, "type", "m"), "val", "bar", "m")
        if ftype == "noBar":
            return f"binom({numerator}, {denominator})"
        if ftype == "skw":
            return f"frac({numerator}, {denominator}, style: \"skewed\")"
        return f"frac({numerator}, {denominator})"
    if tag in {"sSup", "sSub", "sSubSup"}:
        base = omml_to_typst(child(element, "e", "m"))
        sub = omml_to_typst(child(element, "sub", "m"))
        sup = omml_to_typst(child(element, "sup", "m"))
        if tag == "sSup":
            return f"{_group_attachment(base)}^({_clean_group(sup)})"
        if tag == "sSub":
            return f"{_group_attachment(base)}_({_clean_group(sub)})"
        return f"{_group_attachment(base)}_({_clean_group(sub)})^({_clean_group(sup)})"
    if tag == "sPre":
        base = omml_to_typst(child(element, "e", "m"))
        sub = omml_to_typst(child(element, "sub", "m"))
        sup = omml_to_typst(child(element, "sup", "m"))
        return f"attach({_group_attachment(base)}, tl: [{sup}], bl: [{sub}])"
    if tag == "rad":
        degree = omml_to_typst(child(element, "deg", "m"))
        base = omml_to_typst(child(element, "e", "m"))
        deg_hide = bool(attr(child(child(element, "radPr", "m"), "degHide", "m"), "val", "0", "m") in {"1", "true"})
        return f"sqrt({base})" if not degree or deg_hide else f"root({degree}, {base})"
    if tag == "nary":
        pr = child(element, "naryPr", "m")
        char = attr(child(pr, "chr", "m"), "val", "∑", "m")
        operator = UNICODE_TO_TYPST.get(char, char)
        base = omml_to_typst(child(element, "e", "m"))
        sub = omml_to_typst(child(element, "sub", "m"))
        sup = omml_to_typst(child(element, "sup", "m"))
        limits = ""
        if sub:
            limits += f"_({_clean_group(sub)})"
        if sup:
            limits += f"^({_clean_group(sup)})"
        return f"{operator}{limits} {base}".strip()
    if tag == "d":
        pr = child(element, "dPr", "m")
        beg = attr(child(pr, "begChr", "m"), "val", "(", "m")
        end = attr(child(pr, "endChr", "m"), "val", ")", "m")
        sep = attr(child(pr, "sepChr", "m"), "val", "|", "m")
        contents = [omml_to_typst(item) for item in children(element, "e", "m")]
        body = f" {DELIM_TYPST.get(sep, sep)} ".join(contents)
        return f"lr({DELIM_TYPST.get(beg, beg)} {body} {DELIM_TYPST.get(end, end)})"
    if tag == "m":
        rows = []
        for row in children(element, "mr", "m"):
            cells = [omml_to_typst(cell) for cell in children(row, "e", "m")]
            rows.append(", ".join(cells))
        return "mat(" + "; ".join(rows) + ")"
    if tag == "eqArr":
        rows = [omml_to_typst(item) for item in children(element, "e", "m")]
        return "cases(" + ", ".join(rows) + ")"
    if tag == "func":
        name = omml_to_typst(child(element, "fName", "m"))
        body = omml_to_typst(child(element, "e", "m"))
        return f"{name}({body})"
    if tag == "acc":
        pr = child(element, "accPr", "m")
        char = attr(child(pr, "chr", "m"), "val", "^", "m")
        base = omml_to_typst(child(element, "e", "m"))
        accents = {
            "^": "hat", "ˆ": "hat", "¯": "macron", "̅": "overline",
            "→": "arrow", "↔": "arrow.l.r", "~": "tilde", "˜": "tilde",
            "˙": "dot", "¨": "dot.double", "ˇ": "caron", "´": "acute",
            "`": "grave", "̆": "breve",
        }
        return f"accent({base}, {accents.get(char, repr(char))})"
    if tag == "bar":
        pr = child(element, "barPr", "m")
        pos = attr(child(pr, "pos", "m"), "val", "top", "m")
        base = omml_to_typst(child(element, "e", "m"))
        return f"{'underline' if pos == 'bot' else 'overline'}({base})"
    if tag == "groupChr":
        pr = child(element, "groupChrPr", "m")
        char = attr(child(pr, "chr", "m"), "val", "⏞", "m")
        pos = attr(child(pr, "pos", "m"), "val", "top", "m")
        base = omml_to_typst(child(element, "e", "m"))
        function = "underbrace" if pos == "bot" else "overbrace"
        if char not in {"⏞", "⏟"}:
            function = "under" if pos == "bot" else "over"
        return f"{function}({base})"
    if tag in {"limLow", "limUpp"}:
        base = omml_to_typst(child(element, "e", "m"))
        limit = omml_to_typst(child(element, "lim", "m"))
        side = "_" if tag == "limLow" else "^"
        return f"{_group_attachment(base)}{side}({_clean_group(limit)})"
    if tag == "phant":
        return f"hide({omml_to_typst(child(element, 'e', 'm'))})"
    if tag == "run":
        return "".join(element.itertext())
    pieces = [omml_to_typst(item) for item in element]
    if pieces:
        return " ".join(filter(None, pieces)).strip()
    return _typst_symbol_text("".join(element.itertext()))


def _group_attachment(text: str) -> str:
    text = text.strip()
    return text if re.fullmatch(r"[\w.]+", text) else f"({text})"


def _clean_group(text: str) -> str:
    return text.strip().strip("()")


def _m(tag: str, attrs: dict[str, str] | None = None, text: str | None = None) -> ET.Element:
    element = ET.Element(qn("m", tag), attrs or {})
    if text is not None:
        element.text = text
    return element


def _mval(parent: ET.Element, tag: str, value: str) -> ET.Element:
    return ET.SubElement(parent, qn("m", tag), {qn("m", "val"): value})


def _run(text: str) -> ET.Element:
    run = _m("r")
    t = ET.SubElement(run, qn("m", "t"))
    if text.startswith(" ") or text.endswith(" "):
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return run


def _container(tag: str, child_tag: str, nodes: Iterable[ET.Element]) -> ET.Element:
    root = _m(tag)
    holder = ET.SubElement(root, qn("m", child_tag))
    holder.extend(nodes)
    return root


def _strip_math_outer(text: str) -> str:
    text = text.strip()
    if text.startswith("$") and text.endswith("$") and len(text) >= 2:
        return text[1:-1].strip()
    return text


def _find_top_level_operator(text: str, operators: tuple[str, ...], right_to_left: bool = False) -> tuple[int, str] | None:
    depth = 0
    quote: str | None = None
    escaped = False
    indices = range(len(text) - 1, -1, -1) if right_to_left else range(len(text))
    pairs = {')': '(', ']': '[', '}': '{'}
    if right_to_left:
        # A forward depth map is less error-prone for reverse search.
        depth_at: list[int] = [0] * (len(text) + 1)
        d = 0
        q: str | None = None
        esc = False
        for i, ch in enumerate(text):
            depth_at[i] = d
            if q:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == q:
                    q = None
            else:
                if ch == '"':
                    q = ch
                elif ch in "([{":
                    d += 1
                elif ch in ")]}" and d:
                    d -= 1
        depth_at[len(text)] = d
        for i in indices:
            if depth_at[i] != 0:
                continue
            for op in operators:
                start = i - len(op) + 1
                if start >= 0 and text.startswith(op, start) and depth_at[start] == 0:
                    return start, op
        return None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        else:
            if ch == '"':
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}" and depth:
                depth -= 1
            elif depth == 0:
                for op in operators:
                    if text.startswith(op, i):
                        return i, op
        i += 1
    return None


def _parse_call(text: str) -> tuple[str, list[str]] | None:
    match = re.match(r"^([A-Za-z_][\w.-]*)\s*\(", text)
    if not match:
        return None
    open_index = text.find("(", match.start())
    close_index = find_balanced(text, open_index, "(", ")")
    if close_index != len(text) - 1:
        return None
    return match.group(1), split_top_level(text[open_index + 1:close_index])


def _parse_attachment(text: str) -> tuple[str, str | None, str | None] | None:
    depth = 0
    quote: str | None = None
    escaped = False
    positions: list[tuple[int, str]] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        else:
            if ch == '"':
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}" and depth:
                depth -= 1
            elif depth == 0 and ch in "_^" and i > 0:
                positions.append((i, ch))
        i += 1
    if not positions:
        return None
    first = positions[0][0]
    base = text[:first].strip()
    if not base:
        return None
    sub = sup = None
    for index, (pos, marker) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        value = text[pos + 1:end].strip()
        if value.startswith("(") and find_balanced(value, 0, "(", ")") == len(value) - 1:
            value = value[1:-1]
        if marker == "_":
            sub = value
        else:
            sup = value
    return base, sub, sup


def typst_math_to_omml(text: str, *, display: bool = False) -> ET.Element:
    expression = _strip_math_outer(text)
    root = _m("oMathPara" if display else "oMath")
    target = ET.SubElement(root, qn("m", "oMath")) if display else root
    target.extend(_math_nodes(expression))
    return root


def _attachment_atom(text: str, index: int) -> tuple[str, int]:
    """Read one Typst attachment operand after `_` or `^`."""
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text):
        return "", index
    if text[index] in "([{":
        pairs = {"(": ")", "[": "]", "{": "}"}
        close = find_balanced(text, index, text[index], pairs[text[index]])
        if close >= 0:
            return text[index + 1:close], close + 1
    start = index
    while index < len(text) and not text[index].isspace() and text[index] not in "_^":
        index += 1
    return text[start:index], index


def _parse_nary_expression(text: str) -> tuple[str, str | None, str | None, str] | None:
    """Parse a leading Typst n-ary operator with limits and operand.

    For example, ``sum_(i=1)^n i`` becomes (``sum``, ``i=1``, ``n``,
    ``i``). This must run before the generic attachment parser because the
    operand after the limits belongs to the n-ary node, not to the superscript.
    """
    stripped = text.strip()
    names = sorted(NARY_CHARS, key=len, reverse=True)
    name = next((candidate for candidate in names
                 if stripped.startswith(candidate)
                 and (len(stripped) == len(candidate)
                      or stripped[len(candidate)] in "_^ \t([{+-=/<>")), None)
    if name is None:
        return None
    index = len(name)
    sub = sup = None
    while index < len(stripped):
        while index < len(stripped) and stripped[index].isspace():
            index += 1
        if index >= len(stripped) or stripped[index] not in "_^":
            break
        marker = stripped[index]
        value, index = _attachment_atom(stripped, index + 1)
        if marker == "_":
            sub = value
        else:
            sup = value
    body = stripped[index:].strip()
    if sub is None and sup is None and not body:
        return None
    return name, sub, sup, body


def _math_nodes(text: str) -> list[ET.Element]:
    text = text.strip()
    if not text:
        return []

    # Alignment marks and explicit line breaks become equation arrays.
    rows = split_top_level(text, "\\") if "\\" in text else [text]
    if len(rows) > 1:
        eq = _m("eqArr")
        for row in rows:
            e = ET.SubElement(eq, qn("m", "e"))
            e.extend(_math_nodes(row.replace("&", "")))
        return [eq]

    relation = _find_top_level_operator(text, ("<=>", "=>", "<=", ">=", "!=", "=", "<", ">"))
    if relation:
        pos, op = relation
        left, right = text[:pos], text[pos + len(op):]
        symbols = {"<=>": "⇔", "=>": "⇒", "<=": "≤", ">=": "≥", "!=": "≠"}
        return _math_nodes(left) + [_run(symbols.get(op, op))] + _math_nodes(right)

    additive = _find_top_level_operator(text, ("+", "-"), right_to_left=True)
    if additive and additive[0] > 0:
        pos, op = additive
        return _math_nodes(text[:pos]) + [_run(op)] + _math_nodes(text[pos + 1:])

    # Typst's slash is a fraction operator in math.
    fraction = _find_top_level_operator(text, ("/",), right_to_left=True)
    if fraction and fraction[0] > 0:
        pos, _ = fraction
        f = _m("f")
        num = ET.SubElement(f, qn("m", "num"))
        num.extend(_math_nodes(text[:pos]))
        den = ET.SubElement(f, qn("m", "den"))
        den.extend(_math_nodes(text[pos + 1:]))
        return [f]

    nary_expression = _parse_nary_expression(text)
    if nary_expression:
        name, sub, sup, body = nary_expression
        nary = _m("nary")
        npr = ET.SubElement(nary, qn("m", "naryPr"))
        _mval(npr, "chr", NARY_CHARS[name])
        _mval(npr, "limLoc", "undOvr")
        sub_holder = ET.SubElement(nary, qn("m", "sub"))
        if sub:
            sub_holder.extend(_math_nodes(sub))
        sup_holder = ET.SubElement(nary, qn("m", "sup"))
        if sup:
            sup_holder.extend(_math_nodes(sup))
        body_holder = ET.SubElement(nary, qn("m", "e"))
        if body:
            body_holder.extend(_math_nodes(body))
        return [nary]

    attachment = _parse_attachment(text)
    if attachment:
        base, sub, sup = attachment
        tag = "sSubSup" if sub is not None and sup is not None else "sSub" if sub is not None else "sSup"
        node = _m(tag)
        e = ET.SubElement(node, qn("m", "e"))
        e.extend(_math_nodes(base))
        if sub is not None:
            holder = ET.SubElement(node, qn("m", "sub"))
            holder.extend(_math_nodes(sub))
        if sup is not None:
            holder = ET.SubElement(node, qn("m", "sup"))
            holder.extend(_math_nodes(sup))
        return [node]

    call = _parse_call(text)
    if call:
        name, args = call
        positional = [arg for arg in args if ":" not in arg or arg.strip().startswith(('"', "[", "("))]
        named = {}
        for arg in args:
            match = re.match(r"^([\w.-]+)\s*:\s*(.*)$", arg, re.DOTALL)
            if match:
                named[match.group(1)] = match.group(2)
        if name in {"frac", "binom"} and len(positional) >= 2:
            f = _m("f")
            if name == "binom":
                fpr = ET.SubElement(f, qn("m", "fPr"))
                _mval(fpr, "type", "noBar")
            num = ET.SubElement(f, qn("m", "num")); num.extend(_math_nodes(positional[0]))
            den = ET.SubElement(f, qn("m", "den")); den.extend(_math_nodes(positional[1]))
            return [f]
        if name in {"sqrt", "root"} and positional:
            rad = _m("rad")
            radpr = ET.SubElement(rad, qn("m", "radPr"))
            degree = ET.SubElement(rad, qn("m", "deg"))
            if name == "sqrt":
                _mval(radpr, "degHide", "1")
                body = positional[0]
            else:
                degree.extend(_math_nodes(positional[0]))
                body = positional[1] if len(positional) > 1 else ""
            e = ET.SubElement(rad, qn("m", "e")); e.extend(_math_nodes(body))
            return [rad]
        if name in {"mat", "matrix", "vec", "cases"}:
            rows = []
            for arg in positional:
                rows.append(split_top_level(arg, ",") if name in {"mat", "matrix", "cases"} else [arg])
            if len(rows) == 1 and ";" in positional[0]:
                rows = [split_top_level(row, ",") for row in split_top_level(positional[0], ";")]
            if name == "cases":
                eq = _m("eqArr")
                for row in rows:
                    e = ET.SubElement(eq, qn("m", "e")); e.extend(_math_nodes(" ".join(row)))
                delim = _m("d")
                dpr = ET.SubElement(delim, qn("m", "dPr")); _mval(dpr, "begChr", "{"); _mval(dpr, "endChr", "")
                e = ET.SubElement(delim, qn("m", "e")); e.append(eq)
                return [delim]
            matrix = _m("m")
            for row in rows:
                mr = ET.SubElement(matrix, qn("m", "mr"))
                for value in row:
                    e = ET.SubElement(mr, qn("m", "e")); e.extend(_math_nodes(value))
            if name == "vec":
                return [matrix]
            delim = _m("d")
            dpr = ET.SubElement(delim, qn("m", "dPr")); _mval(dpr, "begChr", "("); _mval(dpr, "endChr", ")")
            e = ET.SubElement(delim, qn("m", "e")); e.append(matrix)
            return [delim]
        if name in {"abs", "norm", "floor", "ceil", "round", "lr"} and positional:
            begin, end = {
                "abs": ("|", "|"), "norm": ("‖", "‖"), "floor": ("⌊", "⌋"),
                "ceil": ("⌈", "⌉"), "round": ("(", ")"), "lr": ("(", ")"),
            }[name]
            d = _m("d")
            dpr = ET.SubElement(d, qn("m", "dPr")); _mval(dpr, "begChr", begin); _mval(dpr, "endChr", end)
            e = ET.SubElement(d, qn("m", "e")); e.extend(_math_nodes(positional[0]))
            return [d]
        if name in {"overline", "underline"} and positional:
            bar = _m("bar")
            bpr = ET.SubElement(bar, qn("m", "barPr")); _mval(bpr, "pos", "bot" if name == "underline" else "top")
            e = ET.SubElement(bar, qn("m", "e")); e.extend(_math_nodes(positional[0]))
            return [bar]
        if name in {"accent", "hat", "tilde", "dot", "macron", "arrow"} and positional:
            char = {
                "hat": "^", "tilde": "~", "dot": "˙", "macron": "¯", "arrow": "→"
            }.get(name, "^")
            if name == "accent" and len(positional) > 1:
                char = TYPST_TO_UNICODE.get(positional[1].strip(), positional[1].strip().strip('"')[:1] or "^")
            acc = _m("acc")
            apr = ET.SubElement(acc, qn("m", "accPr")); _mval(apr, "chr", char)
            e = ET.SubElement(acc, qn("m", "e")); e.extend(_math_nodes(positional[0]))
            return [acc]
        # Generic function application.
        func = _m("func")
        fname = ET.SubElement(func, qn("m", "fName")); fname.append(_run(TYPST_TO_UNICODE.get(name, name)))
        e = ET.SubElement(func, qn("m", "e")); e.extend(_math_nodes(", ".join(positional)))
        return [func]

    # Parenthesized/grouped expression.
    if len(text) >= 2 and text[0] in "([{\"" and text[-1] in ")]}":
        pairs = {"(": ")", "[": "]", "{": "}"}
        if text[0] in pairs and pairs[text[0]] == text[-1] and find_balanced(text, 0, text[0], text[-1]) == len(text) - 1:
            d = _m("d")
            dpr = ET.SubElement(d, qn("m", "dPr")); _mval(dpr, "begChr", text[0]); _mval(dpr, "endChr", text[-1])
            e = ET.SubElement(d, qn("m", "e")); e.extend(_math_nodes(text[1:-1]))
            return [d]

    # Tokenize a plain sequence, translating Typst symbol names to Unicode.
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[A-Za-z_][\w.]*|\d+(?:\.\d+)?|\S', text)
    output: list[ET.Element] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            output.append(_run("".join(buffer)))
            buffer.clear()

    for token in tokens:
        if token.startswith('"') and token.endswith('"'):
            flush()
            output.append(_run(token[1:-1].replace('\\"', '"')))
        elif token in NARY_CHARS:
            flush()
            output.append(_run(NARY_CHARS[token]))
        else:
            mapped = TYPST_TO_UNICODE.get(token, token)
            if buffer and (mapped[0].isalnum() and buffer[-1][-1:].isalnum()):
                buffer.append(" ")
            buffer.append(mapped)
    flush()
    return output or [_run(text)]
