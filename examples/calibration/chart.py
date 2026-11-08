"""Draw the language-tax chart for the README from the saved calibration counts.

    python chart.py     # writes ../../assets/language-tax-light.svg and -dark.svg

Each dot is `(official count - framing overhead) / o200k count` for the same text, so the
chart always matches results/counts.json. No API calls.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from calibrate import COUNTS_FILE, overhead

ASSETS = Path(__file__).resolve().parents[2] / "assets"
CLAUDE, GEMINI = "claude-sonnet-5-5", "gemini-3.8-flash"
LANGS = {
    "lang_pa.txt": "Punjabi",
    "lang_th.txt": "Thai",
    "lang_hi.txt": "Hindi",
    "lang_ar.txt": "Arabic",
    "lang_de.txt": "German",
    "lang_he.txt": "Hebrew",
    "lang_ko.txt": "Korean",
    "lang_fr.txt": "French",
    "lang_ru.txt": "Russian",
    "lang_zh.txt": "Chinese",
    "lang_en.txt": "English",
    "lang_ja.txt": "Japanese",
}
THEMES = {
    "light": {
        "bg": "#ffffff",
        "ink": "#1f2328",
        "quiet": "#59636e",
        "grid": "#d1d9e0",
        "accent": "#0969da",
        "muted": "#9aa4ae",
    },
    "dark": {
        "bg": "#0d1117",
        "ink": "#f0f6fc",
        "quiet": "#9198a1",
        "grid": "#3d444d",
        "accent": "#4493f8",
        "muted": "#6e7781",
    },
}


def ratios(counts: dict, model: str) -> dict[str, float]:
    official = counts["models"][model]
    framing = overhead(official)
    return {
        lang: (official[name] - framing) / counts["o200k"][name] for name, lang in LANGS.items()
    }


def svg(counts: dict, theme: dict[str, str]) -> str:
    cl, gm = ratios(counts, CLAUDE), ratios(counts, GEMINI)
    order = sorted(cl, key=lambda lang: -cl[lang])
    x0, scale, y0, step = 150, 137.5, 124, 26
    bottom = y0 + step * (len(order) - 1) + 20
    height = bottom + 64

    def x(v: float) -> float:
        return x0 + v * scale

    t = theme
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{height}" '
        f'viewBox="0 0 760 {height}" '
        f'font-family="{font}" font-size="13" role="img" '
        'aria-label="Claude uses up to 3.9 times the GPT-4o token count for the same text; '
        'Gemini stays near 1">',
        f'<rect width="760" height="{height}" rx="8" fill="{t["bg"]}"/>',
        f'<text x="24" y="32" font-size="16" font-weight="600" fill="{t["ink"]}">'
        f"Same text, different bill: Claude uses up to {max(cl.values()):.1f}× "
        "GPT-4o’s tokens</text>",
        f'<text x="24" y="54" font-size="12" fill="{t["quiet"]}">'
        "Tokens per GPT-4o token, same support-bot prompt in 12 languages, "
        "each provider’s own counter</text>",
        f'<circle cx="30" cy="80" r="5" fill="{t["accent"]}"/>',
        f'<text x="42" y="84" font-size="12" fill="{t["ink"]}">Claude (all 5.x models)</text>',
        f'<circle cx="230" cy="80" r="5" fill="{t["muted"]}"/>',
        f'<text x="242" y="84" font-size="12" fill="{t["ink"]}">Gemini 3.8 Flash</text>',
    ]
    for v in range(5):
        out.append(
            f'<line x1="{x(v)}" x2="{x(v)}" y1="{y0 - 16}" y2="{bottom}" stroke="{t["grid"]}"/>'
            f'<text x="{x(v)}" y="{bottom + 16}" text-anchor="middle" font-size="12" '
            f'fill="{t["quiet"]}">{v}×</text>'
        )
    out.append(
        f'<line x1="{x(1)}" x2="{x(1)}" y1="{y0 - 16}" y2="{bottom}" stroke="{t["quiet"]}" '
        f'stroke-dasharray="4 4"/><text x="{x(1) + 6}" y="{bottom - 4}" font-size="12" '
        f'fill="{t["quiet"]}">same as GPT-4o</text>'
    )
    for i, lang in enumerate(order):
        y = y0 + step * i
        c, g = cl[lang], gm[lang]
        out.append(
            f'<text x="24" y="{y + 4}" fill="{t["ink"]}">{escape(lang)}</text>'
            f'<line x1="{x(g):.1f}" x2="{x(c):.1f}" y1="{y}" y2="{y}" stroke="{t["grid"]}" '
            'stroke-width="2"/>'
            f'<circle cx="{x(g):.1f}" cy="{y}" r="5" fill="{t["muted"]}"/>'
            f'<circle cx="{x(c):.1f}" cy="{y}" r="5.5" fill="{t["accent"]}"/>'
        )
        if i == 0:  # the extreme: label both values
            out.append(
                f'<text x="{x(c) + 12:.1f}" y="{y + 4}" font-size="12" font-weight="600" '
                f'fill="{t["ink"]}">{c:.2f}×</text>'
                f'<text x="{x(g) + 10:.1f}" y="{y - 9}" font-size="12" '
                f'fill="{t["quiet"]}">{g:.2f}×</text>'
            )
    out.append(
        f'<text x="{x(2)}" y="{bottom + 40}" text-anchor="middle" font-size="12" '
        f'fill="{t["quiet"]}">Tokens per GPT-4o token (higher costs more)</text>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    counts = json.loads(COUNTS_FILE.read_text(encoding="utf-8"))
    for name, theme in THEMES.items():
        path = ASSETS / f"language-tax-{name}.svg"
        path.write_bytes(svg(counts, theme).encode("utf-8"))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
