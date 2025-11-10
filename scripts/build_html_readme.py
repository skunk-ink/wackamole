#!/usr/bin/env python3

# Generate README.html from README.md using a clean HTML template.
# - Converts README.md → HTML (headings, lists, code, tables, etc.)
# - Injects into examples/index.html.template
# - Writes README.html into --out-dir (default: website/)

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
import argparse
import html
import sys

README_MD = Path("README.md")

def convert_markdown(md_text: str) -> str:
    """Convert Markdown to HTML using python-markdown if available, else <pre> fallback."""
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
                "codehilite",
            ],
            output_format="html5",
        )
    except ImportError:
        print("⚠️  python-markdown not installed; using plain text fallback.")
        return f"<pre>{html.escape(md_text)}</pre>"

HTML_SCAFFOLD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <link rel="stylesheet" href="{css_path}" />
  <script defer src="{js_path}"></script>
  <style>
    /* Optional: small tweaks so README renders nicely inside the card */
    .markdown :is(h1,h2,h3,h4,h5){{margin-top:1.25rem}}
    .markdown pre{{background:rgba(148,163,184,.15);padding:1rem;border-radius:.6rem;overflow:auto}}
    .markdown code:not(pre code){{background:rgba(148,163,184,.15);padding:.15rem .35rem;border-radius:.35rem}}
    .markdown table{{border-collapse:collapse;width:100%}}
    .markdown th,.markdown td{{border:1px solid var(--surface);padding:.5rem;text-align:left}}
    .readme.card{{padding:1.25rem}}
  </style>
</head>
<body>
  <header>
    <img class="logo" src="{logo_path}" alt="Wack-A-Mole logo" />
    <h1>{title}</h1>
    <p class="tagline">Decentralized Static-Site Publisher &amp; Gateway (Sia + Indexd)</p>
    <nav class="doc-cta" aria-label="Navigation">
      <a class="btn btn-docs" href="{home_href}">{home_btn_text}</a>
    </nav>
  </header>

  <main>
    <section class="card readme">
      <div class="markdown">
        {readme_html}
      </div>
    </section>
  </main>

  <footer>
    <small>Wack-A-Mole • Docs • <a href="{home_href}">Back to Demo</a></small>
  </footer>
</body>
</html>
"""

def main() -> int:
    parser = argparse.ArgumentParser(description="Build README.html with site header.")
    parser.add_argument("--out-dir", default="website", help="Output directory (default: website)")
    parser.add_argument("--title", default="Wack-A-Mole Documentation", help="Page title")
    parser.add_argument("--css-path", default="css/styles.css", help="Path to the site CSS (relative from README.html)")
    parser.add_argument("--js-path", default="js/app.js", help="Path to the site JS (relative from README.html)")
    parser.add_argument("--logo-path", default="assets/wackamole-demo.svg", help="Path to the logo (relative from README.html)")
    parser.add_argument("--home-href", default="index.html", help="Where the header button points to")
    parser.add_argument("--home-btn-text", default="Back to Demo", help="Header button text")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "README.html"

    if not README_MD.exists():
        print("❌ README.md not found.", file=sys.stderr)
        return 1

    md_text = README_MD.read_text(encoding="utf-8")
    readme_html = convert_markdown(md_text)

    html_out = HTML_SCAFFOLD.format(
        title=args.title,
        css_path=args.css_path,
        js_path=args.js_path,
        logo_path=args.logo_path,
        home_href=args.home_href,
        home_btn_text=args.home_btn_text,
        readme_html=readme_html,
    )

    out_path.write_text(html_out, encoding="utf-8")
    print(f"✅ Generated {out_path} from README.md")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())