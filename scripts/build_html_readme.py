#!/usr/bin/env python3
"""
Generate website/index.html from README.md using a simple template.
- Looks for website/index.html.template with a {{README_HTML}} placeholder.
- If python-markdown is unavailable, falls back to a plaintext <pre> render.
- Auto-scrolls to the most relevant "how to publish / where to put site" section.
"""
from pathlib import Path
import sys

TEMPLATE_PATH = Path("website/index.html.template")
OUTPUT_PATH = Path("website/index.html")
README_PATH = Path("README.md")

def convert_markdown(md_text: str) -> str:
    try:
        import markdown  # type: ignore
        return markdown.markdown(
            md_text,
            extensions=["fenced_code", "tables", "toc", "attr_list", "sane_lists"],
            output_format="xhtml"
        )
    except Exception:
        # Fallback: escape minimally and wrap in <pre>
        import html
        return "<pre>" + html.escape(md_text) + "</pre>"

def main() -> int:
    if not README_PATH.exists():
        print("README.md not found. Nothing to do.", file=sys.stderr)
        return 1

    if not TEMPLATE_PATH.exists():
        print("Template missing at website/index.html.template", file=sys.stderr)
        return 2

    readme_md = README_PATH.read_text(encoding="utf-8")
    readme_html = convert_markdown(readme_md)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    out = template.replace("{{README_HTML}}", readme_html)

    OUTPUT_PATH.write_text(out, encoding="utf-8")
    print(f"✅ Generated {OUTPUT_PATH} from README.md")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
