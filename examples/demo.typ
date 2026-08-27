#set document(
  title: "typx demonstration",
  description: "Common Typst constructs converted to DOCX",
)
#set page(
  paper: "a4",
  margin: (top: 22mm, right: 22mm, bottom: 22mm, left: 22mm),
)
#set text(size: 10.5pt, lang: "en")
#set par(justify: true, leading: 0.65em)

= Typst to DOCX demonstration <top>

This paragraph contains *bold*, _italic_, #underline[underlined],
#strike[struck], #highlight(fill: rgb("#FFF2CC"))[highlighted], and
#link("https://typst.app")[linked] text. It also contains inline math
$frac(1, 2) + sqrt(x)$ and a footnote#footnote[Footnote content survives as a Word footnote.].

== Lists

- First bullet
- Second bullet
  - Nested bullet

+ Numbered item
+ Another numbered item

/ Term: Definition-list content is represented with definition-style paragraphs.

== Quote and code

#quote(block: true, attribution: [Source])[A quotation converted to Word's Quote style.]

```python
values = [1, 2, 3]
print(sum(values))
```

== Equation

$ sum_(i=1)^n i = frac(n dot.op (n + 1), 2) $

== Table

#table(
  columns: (1fr, 1fr, 1fr),
  table.header([Feature], [Typst], [DOCX]),
  [Heading], [`= syntax`], [Heading style],
  [Equation], [$frac(a, b)$], [OMML],
  [Table], [`#table(...)`], [`w:tbl`],
)

#pagebreak()

== Second page

Go back to @top. The default `auto` round-trip mode embeds this source in the generated DOCX so an untouched package can recover it exactly.
