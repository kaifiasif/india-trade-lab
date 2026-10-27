"""Original mascots for the India Trade Lab agents: one robot family, one prop each.

Every mascot shares the observatory robot's body (white shell, dark visor, glowing
eyes) and gets its own accent colour and accessory, so a role is recognisable at a
glance. Run this file to write one SVG per agent into docs/guide/mascots/.
"""

from __future__ import annotations

from pathlib import Path

# key: (display name, role id, accent, eye glow)
MASCOTS = {
    "scoop": ("Scoop", "news-analyst", "#4f7fd8", "#b9d0ff"),
    "vibe": ("Vibe", "sentiment-analyst", "#d0679a", "#ffc2de"),
    "chartly": ("Chartly", "technical-analyst", "#2f9c8e", "#b3f0e6"),
    "atlas": ("Atlas", "sector-analyst", "#d98a3a", "#ffd9ad"),
    "tide": ("Tide", "liquidity-analyst", "#2aa3c4", "#b5ecfa"),
    "ledger": ("Ledger", "brokerage-analyst", "#5a6b8c", "#cfd8ea"),
    "scout": ("Scout", "risk-scout", "#c9573f", "#ffc9bb"),
    "blueprint": ("Blueprint", "setup-planner", "#4b56c4", "#c3c8ff"),
    "judge": ("Justice", "selection-judge", "#7760ce", "#dcd1ff"),
    "bullu": ("Bullu", "bull-researcher", "#358977", "#bdf0dc"),
    "bruno": ("Bruno", "bear-researcher", "#8a5a44", "#f2d2c2"),
    "shield": ("Shield", "risk team", "#bb5a65", "#ffc8cf"),
    "captain": ("Captain", "portfolio-manager", "#2e3f73", "#c9d4ff"),
    "echo": ("Echo", "reflector", "#9b84ef", "#e3dbff"),
    "ref": ("Ref", "tournament (code)", "#3a3a48", "#e8e8f2"),
    "pilot": ("Pilot", "autopilot (code)", "#3d8fd1", "#c7e5ff"),
}


def _accessory(key: str, a: str) -> tuple[str, str]:
    """(behind the body, in front of the body) SVG fragments for one mascot."""
    gold = "#e2b84a"
    if key == "scoop":
        return "", (
            f'<path d="M64 74C70 46 182 46 186 74Z" fill="{a}"/>'
            f'<rect x="58" y="70" width="134" height="10" rx="5" fill="{a}"/>'
            f'<rect x="132" y="56" width="26" height="12" rx="3" fill="#fff" opacity=".9"/>'
            f'<text x="145" y="65" font-size="8" font-family="Inter" font-weight="800" '
            f'fill="{a}" text-anchor="middle">NEWS</text>'
            '<g transform="rotate(-12 196 160)"><rect x="176" y="136" width="44" height="52" '
            'rx="4" fill="#fff" stroke="#c9cbe0" stroke-width="2"/>'
            f'<rect x="182" y="143" width="32" height="7" rx="2" fill="{a}"/>'
            '<path d="M182 157H214M182 165H214M182 173H204" stroke="#b8bad0" '
            'stroke-width="3" stroke-linecap="round"/></g>'
        )
    if key == "vibe":
        return "", (
            f'<path d="M126 205C110 194 106 186 112 180C117 175 124 178 126 183C128 178 135 175 '
            f'140 180C146 186 142 194 126 205Z" fill="{a}"/>'
            '<path d="M116 182C118 180 121 180 122 182" stroke="#fff" stroke-width="2" '
            'stroke-linecap="round" opacity=".7"/>'
            '<path d="M126 64V44" stroke="#dedcf5" stroke-width="7" stroke-linecap="round"/>'
            f'<path d="M126 48C116 41 113 35 117 31C120 28 124 29 126 33C128 29 132 28 135 31C139 '
            f'35 136 41 126 48Z" fill="{a}"/>'
        )
    if key == "chartly":
        return "", (
            f'<circle cx="99" cy="118" r="17" stroke="{a}" stroke-width="5"/>'
            f'<circle cx="150" cy="118" r="17" stroke="{a}" stroke-width="5"/>'
            f'<path d="M116 116H133" stroke="{a}" stroke-width="5"/>'
            '<rect x="176" y="128" width="56" height="50" rx="8" fill="#fff" '
            'stroke="#c9cbe0" stroke-width="2"/>'
            '<path d="M188 142V166M202 136V160M216 132V152" stroke="#9aa0b8" stroke-width="2"/>'
            f'<rect x="184" y="148" width="8" height="12" rx="2" fill="{a}"/>'
            f'<rect x="198" y="141" width="8" height="13" rx="2" fill="{a}"/>'
            '<rect x="212" y="136" width="8" height="10" rx="2" fill="#bb5a65"/>'
        )
    if key == "atlas":
        return "", (
            '<circle cx="126" cy="192" r="15" fill="#fff" stroke="#e1def0" stroke-width="2"/>'
            f'<path d="M126 192V177A15 15 0 0 1 140 197Z" fill="{a}"/>'
            '<path d="M126 192L140 197A15 15 0 0 1 113 200Z" fill="#7760ce" opacity=".75"/>'
            '<circle cx="204" cy="140" r="20" fill="#e9f4ff" stroke="#9fc3e6" stroke-width="3"/>'
            '<path d="M186 136C196 130 210 146 222 138M190 150C200 146 210 152 220 148" '
            f'stroke="{a}" stroke-width="3" stroke-linecap="round"/>'
        )
    if key == "tide":
        return "", (
            f'<path d="M126 18C120 28 115 33 115 39A11 11 0 0 0 137 39C137 33 132 28 126 18Z" '
            f'fill="{a}"/>'
            f'<path d="M106 192C112 186 118 186 124 192S136 198 142 192S152 186 156 190" '
            f'stroke="{a}" stroke-width="5" stroke-linecap="round"/>'
            '<path d="M110 203C116 197 122 197 128 203S140 209 146 203" stroke="#9fd7e8" '
            'stroke-width="4" stroke-linecap="round"/>'
        )
    if key == "ledger":
        return "", (
            f'<path d="M126 168L118 176L124 206L126 210L128 206L134 176Z" fill="{a}"/>'
            '<path d="M118 168H134L126 177Z" fill="#3f4b66"/>'
            '<rect x="40" y="178" width="46" height="34" rx="6" fill="#7b5b45"/>'
            '<rect x="53" y="170" width="20" height="10" rx="4" stroke="#7b5b45" '
            'stroke-width="4"/><rect x="40" y="190" width="46" height="4" fill="#5d4433"/>'
            f'<rect x="58" y="187" width="10" height="10" rx="2" fill="{gold}"/>'
        )
    if key == "scout":
        return "", (
            f'<path d="M50 74C70 66 182 66 200 74C190 84 60 84 50 74Z" fill="#8a6a3e"/>'
            f'<path d="M84 72C86 44 166 44 168 72Z" fill="#a8824c"/>'
            f'<rect x="84" y="62" width="84" height="8" fill="{a}"/>'
            '<g transform="translate(150 150)"><rect x="0" y="0" width="22" height="30" rx="9" '
            'fill="#3b3a4a"/><rect x="26" y="0" width="22" height="30" rx="9" fill="#3b3a4a"/>'
            '<rect x="18" y="8" width="12" height="10" fill="#3b3a4a"/>'
            '<circle cx="11" cy="24" r="6" fill="#9fc3e6"/><circle cx="37" cy="24" r="6" '
            'fill="#9fc3e6"/></g>'
        )
    if key == "blueprint":
        return "", (
            f'<path d="M66 76C66 40 184 40 184 76Z" fill="{gold}"/>'
            '<rect x="58" y="72" width="134" height="10" rx="5" fill="#d1a539"/>'
            '<rect x="116" y="42" width="18" height="34" rx="6" fill="#d1a539"/>'
            '<g transform="rotate(-20 200 160)"><rect x="178" y="128" width="20" height="64" '
            f'rx="10" fill="{a}"/><rect x="194" y="132" width="40" height="56" fill="#dfe3ff" '
            f'stroke="{a}" stroke-width="2"/><path d="M200 144H228M200 156H222M200 168H228" '
            f'stroke="{a}" stroke-width="2"/></g>'
        )
    if key == "judge":
        return "", (
            f'<path d="M96 168C106 182 146 182 156 168L160 176C148 194 104 194 92 176Z" '
            f'fill="{a}"/>'
            f'<circle cx="126" cy="186" r="6" fill="{gold}"/>'
            f'<path d="M96 66L104 38L126 54L148 38L156 66Z" fill="{gold}"/>'
            '<circle cx="104" cy="38" r="5" fill="#fff4c9"/><circle cx="148" cy="38" r="5" '
            'fill="#fff4c9"/><circle cx="126" cy="54" r="4" fill="#fff4c9"/>'
            '<g transform="rotate(30 196 150)"><rect x="190" y="146" width="10" height="44" '
            'rx="5" fill="#8a5a44"/><rect x="176" y="126" width="38" height="24" rx="7" '
            f'fill="#6e4636"/><rect x="176" y="134" width="38" height="6" fill="{gold}"/></g>'
        )
    if key == "bullu":
        return (
            '<path d="M70 82C52 76 42 58 46 40C56 54 66 60 80 64Z" fill="#efe6cf"/>'
            '<path d="M178 82C196 76 206 58 202 40C192 54 182 60 168 64Z" fill="#efe6cf"/>',
            f'<path d="M126 178L140 194H132V206H120V194H112Z" fill="{a}"/>',
        )
    if key == "bruno":
        return (
            f'<circle cx="78" cy="62" r="18" fill="{a}"/><circle cx="174" cy="62" r="18" '
            f'fill="{a}"/><circle cx="78" cy="62" r="9" fill="#d9b4a2"/>'
            '<circle cx="174" cy="62" r="9" fill="#d9b4a2"/>',
            f'<path d="M126 206L140 190H132V178H120V190H112Z" fill="{a}"/>',
        )
    if key == "shield":
        return "", (
            f'<path d="M126 170L150 178V194C150 206 140 214 126 220C112 214 102 206 102 194V178Z" '
            f'fill="{a}"/><path d="M126 178L142 184V194C142 202 136 207 126 211Z" fill="#fff" '
            'opacity=".35"/><path d="M116 194L123 201L137 186" stroke="#fff" stroke-width="4" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
    if key == "captain":
        return "", (
            f'<path d="M70 64C80 40 172 40 182 64Z" fill="#fff" stroke="#d7d9e8" stroke-width="2"/>'
            f'<rect x="64" y="60" width="122" height="14" rx="5" fill="{a}"/>'
            '<path d="M60 74C80 84 170 84 190 74L186 70C160 78 90 78 64 70Z" fill="#1c2747"/>'
            f'<path d="M126 46L129 54H137L131 59L133 67L126 62L119 67L121 59L115 54H123Z" '
            f'fill="{gold}"/>'
        )
    if key == "echo":
        return "", (
            '<circle cx="126" cy="30" r="11" fill="#fff4c9" stroke="#e2b84a" stroke-width="3"/>'
            '<path d="M121 42H131" stroke="#e2b84a" stroke-width="3"/>'
            '<path d="M112 22L106 16M140 22L146 16M126 14V7" stroke="#e2b84a" stroke-width="3" '
            'stroke-linecap="round"/>'
            '<g transform="rotate(10 196 160)"><rect x="176" y="134" width="42" height="54" '
            f'rx="5" fill="{a}"/><rect x="182" y="140" width="32" height="42" rx="3" '
            'fill="#fff"/><path d="M187 150H209M187 158H209M187 166H201" stroke="#b8bad0" '
            'stroke-width="3" stroke-linecap="round"/></g>'
        )
    if key == "ref":
        return "", (
            '<clipPath id="ref-clip"><path d="M96 166H157L169 201C173 216 161 225 151 220L126 '
            '209 102 220C90 225 79 215 84 201L96 166Z"/></clipPath>'
            '<g clip-path="url(#ref-clip)">'
            + "".join(
                f'<rect x="{80 + i * 16}" y="160" width="8" height="70" fill="#3a3a48"/>'
                for i in range(6)
            )
            + "</g>"
            '<path d="M150 150L172 168" stroke="#e2b84a" stroke-width="3"/>'
            '<rect x="168" y="162" width="22" height="12" rx="6" fill="#c9cbe0"/>'
            '<circle cx="54" cy="150" r="16" fill="#fff" stroke="#3a3a48" stroke-width="4"/>'
            '<path d="M54 140V150L61 155" stroke="#bb5a65" stroke-width="3" '
            'stroke-linecap="round"/><rect x="50" y="128" width="8" height="6" rx="2" '
            'fill="#3a3a48"/>'
        )
    if key == "pilot":
        return "", (
            '<path d="M64 80C66 46 184 46 186 80L178 82C172 60 78 60 72 82Z" fill="#8a5a44"/>'
            '<rect x="82" y="58" width="36" height="22" rx="11" fill="#2b2a3a" '
            f'stroke="{a}" stroke-width="4"/>'
            '<rect x="132" y="58" width="36" height="22" rx="11" fill="#2b2a3a" '
            f'stroke="{a}" stroke-width="4"/><path d="M118 68H132" stroke="{a}" '
            'stroke-width="4"/><path d="M90 64L98 72M140 64L148 72" stroke="#9fd0ff" '
            'stroke-width="3" stroke-linecap="round"/>'
            '<path d="M100 168C116 178 140 178 154 168L158 176C150 184 140 186 134 186L150 '
            '210L138 212L126 188C112 188 100 184 96 176Z" fill="#f0f4ff" stroke="#c7d3f0" '
            'stroke-width="2"/>'
        )
    return "", ""


def svg(key: str, size: int = 250) -> str:
    """One mascot as a self-contained SVG; gradient ids are prefixed so many can share a page."""
    name, role, accent, eye = MASCOTS[key]
    behind, front = _accessory(key, accent)
    p = f"m-{key}"
    antenna = (
        ""
        if key in ("tide", "echo")
        else f'<path d="M126 64V40" stroke="#dedcf5" stroke-width="7" stroke-linecap="round"/>'
        f'<circle cx="126" cy="35" r="9" fill="{accent}"/>'
        '<circle cx="123" cy="32" r="3" fill="#fff" opacity=".7"/>'
    )
    if key in ("scoop", "scout", "blueprint", "captain", "pilot", "vibe", "judge"):
        antenna = ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 250 250" fill="none" role="img" aria-label="{name}, the {role} mascot">
<defs>
<linearGradient id="{p}-body" x1="70" y1="65" x2="180" y2="218" gradientUnits="userSpaceOnUse"><stop stop-color="#fff"/><stop offset="1" stop-color="#d9d8ee"/></linearGradient>
<linearGradient id="{p}-face" x1="76" y1="86" x2="167" y2="156" gradientUnits="userSpaceOnUse"><stop stop-color="#302d4b"/><stop offset="1" stop-color="#141326"/></linearGradient>
<linearGradient id="{p}-ear" x1="45" y1="95" x2="75" y2="141" gradientUnits="userSpaceOnUse"><stop stop-color="#fff"/><stop offset="1" stop-color="{accent}"/></linearGradient>
</defs>
<ellipse cx="129" cy="228" rx="55" ry="9" fill="{accent}" opacity=".16"/>
{antenna}
{behind}
<rect x="46" y="99" width="26" height="43" rx="13" fill="url(#{p}-ear)"/>
<rect x="180" y="98" width="22" height="43" rx="11" fill="url(#{p}-ear)"/>
<path d="M96 166H157L169 201C173 216 161 225 151 220L126 209 102 220C90 225 79 215 84 201L96 166Z" fill="url(#{p}-body)"/>
<path d="M96 176L80 188" stroke="#e7e6f7" stroke-width="17" stroke-linecap="round"/>
<path d="M157 175L178 161" stroke="#e7e6f7" stroke-width="17" stroke-linecap="round"/>
<rect x="62" y="61" width="124" height="118" rx="39" fill="url(#{p}-body)"/>
<rect x="75" y="80" width="99" height="77" rx="28" fill="url(#{p}-face)"/>
<path d="M93 101C96 97 103 97 106 101" stroke="{eye}" stroke-width="3" stroke-linecap="round" opacity=".5"/>
<rect x="92" y="107" width="14" height="23" rx="7" fill="{eye}"/>
<rect x="143" y="107" width="14" height="23" rx="7" fill="{eye}"/>
<path d="M119 136C123 140 129 140 133 136" stroke="{eye}" stroke-width="3" stroke-linecap="round"/>
<circle cx="86" cy="140" r="5" fill="{accent}" opacity=".45"/>
<circle cx="163" cy="140" r="5" fill="{accent}" opacity=".45"/>
{front}
</svg>"""


def main() -> None:
    folder = Path(__file__).parent / "mascots"
    folder.mkdir(exist_ok=True)
    for key in MASCOTS:
        (folder / f"{key}.svg").write_text(svg(key) + "\n", encoding="utf-8")
    print(f"Wrote {len(MASCOTS)} mascots to {folder}")


if __name__ == "__main__":
    main()
