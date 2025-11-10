#!/usr/bin/env python3

# Generate website/index.html from README.md using a clean HTML template.

# - Converts README.md → HTML (headings, lists, code, tables, etc.)
# - Injects into website/index.html.template
# - Auto-scrolls to the section describing where to put your website files

"""                      _..._ ___
                       .:::::::.  `"-._.-''.
                  ,   /:::::::::\     ':    \                     _._
                  \:-::::::::::::\     :.    |     /|.-'         /:::\ 
                   \::::::::\:::::|    ':     |   |  /           |:::|
                    `:::::::|:::::\     ':    |   `\ |    __     |\::/\ 
                       -:::-|::::::|    ':    |  .`\ .\_.'  `.__/      |
                            |::::::\    ':.   |   \ ';:: /.-._   ,    /
                            |:::::::|    :.   /   ,`\;:: \'./0)  |_.-/
                            ;:::::::|    ':  |    \.`;::.   ``   |  |
                             \::::::/    :'  /     _\::::'      /  /
                              \::::|   :'   /    ,=:;::/           |
                               \:::|   :'  |    (='` //        /   |
                                \::\   `:  /     '--' |       /\   |
  GITHUB.COM/SKUNK-INK           \:::.  `:_|.-"`"-.    \__.-'/::\  |
░▒█▀▀▀█░▒█░▄▀░▒█░▒█░▒█▄░▒█░▒█░▄▀  '::::.:::...:::. '.       /:::|  |
░░▀▀▀▄▄░▒█▀▄░░▒█░▒█░▒█▒█▒█░▒█▀▄░   '::/::::::::::::. '-.__.:::::|  |
░▒█▄▄▄█░▒█░▒█░░▀▄▄▀░▒█░░▀█░▒█░▒█     |::::::::::::\::..../::::::| /
                                     |:::::::::::::|::::/::::::://
              ░▒▀█▀░▒█▄░▒█░▒█░▄▀     \:::::::::::::|'::/::::::::/
              ░░▒█░░▒█▒█▒█░▒█▀▄░     /\::::::::::::/  /:::::::/:|
              ░▒▄█▄░▒█░░▀█░▒█░▒█    |::';:::::::::/   |::::::/::;
            build_html_readme.py    |:::/`-:::::;;-._ |:::::/::/
                                    |:::|  `-::::\   `|::::/::/
                                    |:::|     \:::\   \:::/::/
                                   /:::/       \:::\   \:/\:/
                                  (_::/         \:::;__ \\_\\___
                                  (_:/           \::):):)\:::):):)
                                   `"             `""""`  `""""""`      
"""

from pathlib import Path
import sys
import html

TEMPLATE_PATH = Path("examples/index.html.template")
OUTPUT_PATH = Path("website/index.html")
README_PATH = Path("README.md")

def convert_markdown(md_text: str) -> str:
    """Convert Markdown to HTML using the markdown package or fallback."""
    try:
        import markdown  # type: ignore
        return markdown.markdown(
            md_text,
            extensions=[
                "fenced_code",
                "tables",
                "toc",
                "attr_list",
                "sane_lists",
                "codehilite"
            ],
            output_format="html5",
        )
    except ImportError:
        print("⚠️  python-markdown not installed; using plain text fallback.")
        return f"<pre>{html.escape(md_text)}</pre>"

def main() -> int:
    if not README_PATH.exists():
        print("❌ README.md not found.", file=sys.stderr)
        return 1
    if not TEMPLATE_PATH.exists():
        print("❌ Template missing at website/index.html.template", file=sys.stderr)
        return 2

    # Convert README.md → HTML
    md_text = README_PATH.read_text(encoding="utf-8")
    readme_html = convert_markdown(md_text)

    # Inject into template
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html_out = template.replace("{{README_HTML}}", readme_html)
    OUTPUT_PATH.write_text(html_out, encoding="utf-8")

    print(f"✅ Generated {OUTPUT_PATH} from README.md")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
