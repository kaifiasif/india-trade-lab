// Generated from docs/guide/mascots.py: the mascot family's colours and props.
// Regenerate rather than edit by hand.
export type MascotKey = "scoop" | "vibe" | "chartly" | "atlas" | "tide" | "ledger" | "scout" | "blueprint" | "judge" | "bullu" | "bruno" | "shield" | "captain" | "echo" | "ref" | "pilot";
export interface MascotSpec { name: string; role: string; accent: string; eye: string; behind: string; front: string; antenna: boolean }
export const MASCOTS: Record<MascotKey, MascotSpec> = {
  "scoop": {
    "name": "Scoop",
    "role": "news-analyst",
    "accent": "#4f7fd8",
    "eye": "#b9d0ff",
    "behind": "",
    "front": "<path d=\"M64 74C70 46 182 46 186 74Z\" fill=\"#4f7fd8\"/><rect x=\"58\" y=\"70\" width=\"134\" height=\"10\" rx=\"5\" fill=\"#4f7fd8\"/><rect x=\"132\" y=\"56\" width=\"26\" height=\"12\" rx=\"3\" fill=\"#fff\" opacity=\".9\"/><text x=\"145\" y=\"65\" font-size=\"8\" font-family=\"Inter\" font-weight=\"800\" fill=\"#4f7fd8\" text-anchor=\"middle\">NEWS</text><g transform=\"rotate(-12 196 160)\"><rect x=\"176\" y=\"136\" width=\"44\" height=\"52\" rx=\"4\" fill=\"#fff\" stroke=\"#c9cbe0\" stroke-width=\"2\"/><rect x=\"182\" y=\"143\" width=\"32\" height=\"7\" rx=\"2\" fill=\"#4f7fd8\"/><path d=\"M182 157H214M182 165H214M182 173H204\" stroke=\"#b8bad0\" stroke-width=\"3\" stroke-linecap=\"round\"/></g>",
    "antenna": false
  },
  "vibe": {
    "name": "Vibe",
    "role": "sentiment-analyst",
    "accent": "#d0679a",
    "eye": "#ffc2de",
    "behind": "",
    "front": "<path d=\"M126 205C110 194 106 186 112 180C117 175 124 178 126 183C128 178 135 175 140 180C146 186 142 194 126 205Z\" fill=\"#d0679a\"/><path d=\"M116 182C118 180 121 180 122 182\" stroke=\"#fff\" stroke-width=\"2\" stroke-linecap=\"round\" opacity=\".7\"/><path d=\"M126 64V44\" stroke=\"#dedcf5\" stroke-width=\"7\" stroke-linecap=\"round\"/><path d=\"M126 48C116 41 113 35 117 31C120 28 124 29 126 33C128 29 132 28 135 31C139 35 136 41 126 48Z\" fill=\"#d0679a\"/>",
    "antenna": false
  },
  "chartly": {
    "name": "Chartly",
    "role": "technical-analyst",
    "accent": "#2f9c8e",
    "eye": "#b3f0e6",
    "behind": "",
    "front": "<circle cx=\"99\" cy=\"118\" r=\"17\" stroke=\"#2f9c8e\" stroke-width=\"5\"/><circle cx=\"150\" cy=\"118\" r=\"17\" stroke=\"#2f9c8e\" stroke-width=\"5\"/><path d=\"M116 116H133\" stroke=\"#2f9c8e\" stroke-width=\"5\"/><rect x=\"176\" y=\"128\" width=\"56\" height=\"50\" rx=\"8\" fill=\"#fff\" stroke=\"#c9cbe0\" stroke-width=\"2\"/><path d=\"M188 142V166M202 136V160M216 132V152\" stroke=\"#9aa0b8\" stroke-width=\"2\"/><rect x=\"184\" y=\"148\" width=\"8\" height=\"12\" rx=\"2\" fill=\"#2f9c8e\"/><rect x=\"198\" y=\"141\" width=\"8\" height=\"13\" rx=\"2\" fill=\"#2f9c8e\"/><rect x=\"212\" y=\"136\" width=\"8\" height=\"10\" rx=\"2\" fill=\"#bb5a65\"/>",
    "antenna": true
  },
  "atlas": {
    "name": "Atlas",
    "role": "sector-analyst",
    "accent": "#d98a3a",
    "eye": "#ffd9ad",
    "behind": "",
    "front": "<circle cx=\"126\" cy=\"192\" r=\"15\" fill=\"#fff\" stroke=\"#e1def0\" stroke-width=\"2\"/><path d=\"M126 192V177A15 15 0 0 1 140 197Z\" fill=\"#d98a3a\"/><path d=\"M126 192L140 197A15 15 0 0 1 113 200Z\" fill=\"#7760ce\" opacity=\".75\"/><circle cx=\"204\" cy=\"140\" r=\"20\" fill=\"#e9f4ff\" stroke=\"#9fc3e6\" stroke-width=\"3\"/><path d=\"M186 136C196 130 210 146 222 138M190 150C200 146 210 152 220 148\" stroke=\"#d98a3a\" stroke-width=\"3\" stroke-linecap=\"round\"/>",
    "antenna": true
  },
  "tide": {
    "name": "Tide",
    "role": "liquidity-analyst",
    "accent": "#2aa3c4",
    "eye": "#b5ecfa",
    "behind": "",
    "front": "<path d=\"M126 18C120 28 115 33 115 39A11 11 0 0 0 137 39C137 33 132 28 126 18Z\" fill=\"#2aa3c4\"/><path d=\"M106 192C112 186 118 186 124 192S136 198 142 192S152 186 156 190\" stroke=\"#2aa3c4\" stroke-width=\"5\" stroke-linecap=\"round\"/><path d=\"M110 203C116 197 122 197 128 203S140 209 146 203\" stroke=\"#9fd7e8\" stroke-width=\"4\" stroke-linecap=\"round\"/>",
    "antenna": false
  },
  "ledger": {
    "name": "Ledger",
    "role": "brokerage-analyst",
    "accent": "#5a6b8c",
    "eye": "#cfd8ea",
    "behind": "",
    "front": "<path d=\"M126 168L118 176L124 206L126 210L128 206L134 176Z\" fill=\"#5a6b8c\"/><path d=\"M118 168H134L126 177Z\" fill=\"#3f4b66\"/><rect x=\"40\" y=\"178\" width=\"46\" height=\"34\" rx=\"6\" fill=\"#7b5b45\"/><rect x=\"53\" y=\"170\" width=\"20\" height=\"10\" rx=\"4\" stroke=\"#7b5b45\" stroke-width=\"4\"/><rect x=\"40\" y=\"190\" width=\"46\" height=\"4\" fill=\"#5d4433\"/><rect x=\"58\" y=\"187\" width=\"10\" height=\"10\" rx=\"2\" fill=\"#e2b84a\"/>",
    "antenna": true
  },
  "scout": {
    "name": "Scout",
    "role": "risk-scout",
    "accent": "#c9573f",
    "eye": "#ffc9bb",
    "behind": "",
    "front": "<path d=\"M50 74C70 66 182 66 200 74C190 84 60 84 50 74Z\" fill=\"#8a6a3e\"/><path d=\"M84 72C86 44 166 44 168 72Z\" fill=\"#a8824c\"/><rect x=\"84\" y=\"62\" width=\"84\" height=\"8\" fill=\"#c9573f\"/><g transform=\"translate(150 150)\"><rect x=\"0\" y=\"0\" width=\"22\" height=\"30\" rx=\"9\" fill=\"#3b3a4a\"/><rect x=\"26\" y=\"0\" width=\"22\" height=\"30\" rx=\"9\" fill=\"#3b3a4a\"/><rect x=\"18\" y=\"8\" width=\"12\" height=\"10\" fill=\"#3b3a4a\"/><circle cx=\"11\" cy=\"24\" r=\"6\" fill=\"#9fc3e6\"/><circle cx=\"37\" cy=\"24\" r=\"6\" fill=\"#9fc3e6\"/></g>",
    "antenna": false
  },
  "blueprint": {
    "name": "Blueprint",
    "role": "setup-planner",
    "accent": "#4b56c4",
    "eye": "#c3c8ff",
    "behind": "",
    "front": "<path d=\"M66 76C66 40 184 40 184 76Z\" fill=\"#e2b84a\"/><rect x=\"58\" y=\"72\" width=\"134\" height=\"10\" rx=\"5\" fill=\"#d1a539\"/><rect x=\"116\" y=\"42\" width=\"18\" height=\"34\" rx=\"6\" fill=\"#d1a539\"/><g transform=\"rotate(-20 200 160)\"><rect x=\"178\" y=\"128\" width=\"20\" height=\"64\" rx=\"10\" fill=\"#4b56c4\"/><rect x=\"194\" y=\"132\" width=\"40\" height=\"56\" fill=\"#dfe3ff\" stroke=\"#4b56c4\" stroke-width=\"2\"/><path d=\"M200 144H228M200 156H222M200 168H228\" stroke=\"#4b56c4\" stroke-width=\"2\"/></g>",
    "antenna": false
  },
  "judge": {
    "name": "Justice",
    "role": "selection-judge",
    "accent": "#7760ce",
    "eye": "#dcd1ff",
    "behind": "",
    "front": "<path d=\"M96 168C106 182 146 182 156 168L160 176C148 194 104 194 92 176Z\" fill=\"#7760ce\"/><circle cx=\"126\" cy=\"186\" r=\"6\" fill=\"#e2b84a\"/><path d=\"M96 66L104 38L126 54L148 38L156 66Z\" fill=\"#e2b84a\"/><circle cx=\"104\" cy=\"38\" r=\"5\" fill=\"#fff4c9\"/><circle cx=\"148\" cy=\"38\" r=\"5\" fill=\"#fff4c9\"/><circle cx=\"126\" cy=\"54\" r=\"4\" fill=\"#fff4c9\"/><g transform=\"rotate(30 196 150)\"><rect x=\"190\" y=\"146\" width=\"10\" height=\"44\" rx=\"5\" fill=\"#8a5a44\"/><rect x=\"176\" y=\"126\" width=\"38\" height=\"24\" rx=\"7\" fill=\"#6e4636\"/><rect x=\"176\" y=\"134\" width=\"38\" height=\"6\" fill=\"#e2b84a\"/></g>",
    "antenna": false
  },
  "bullu": {
    "name": "Bullu",
    "role": "bull-researcher",
    "accent": "#358977",
    "eye": "#bdf0dc",
    "behind": "<path d=\"M70 82C52 76 42 58 46 40C56 54 66 60 80 64Z\" fill=\"#efe6cf\"/><path d=\"M178 82C196 76 206 58 202 40C192 54 182 60 168 64Z\" fill=\"#efe6cf\"/>",
    "front": "<path d=\"M126 178L140 194H132V206H120V194H112Z\" fill=\"#358977\"/>",
    "antenna": true
  },
  "bruno": {
    "name": "Bruno",
    "role": "bear-researcher",
    "accent": "#8a5a44",
    "eye": "#f2d2c2",
    "behind": "<circle cx=\"78\" cy=\"62\" r=\"18\" fill=\"#8a5a44\"/><circle cx=\"174\" cy=\"62\" r=\"18\" fill=\"#8a5a44\"/><circle cx=\"78\" cy=\"62\" r=\"9\" fill=\"#d9b4a2\"/><circle cx=\"174\" cy=\"62\" r=\"9\" fill=\"#d9b4a2\"/>",
    "front": "<path d=\"M126 206L140 190H132V178H120V190H112Z\" fill=\"#8a5a44\"/>",
    "antenna": true
  },
  "shield": {
    "name": "Shield",
    "role": "risk team",
    "accent": "#bb5a65",
    "eye": "#ffc8cf",
    "behind": "",
    "front": "<path d=\"M126 170L150 178V194C150 206 140 214 126 220C112 214 102 206 102 194V178Z\" fill=\"#bb5a65\"/><path d=\"M126 178L142 184V194C142 202 136 207 126 211Z\" fill=\"#fff\" opacity=\".35\"/><path d=\"M116 194L123 201L137 186\" stroke=\"#fff\" stroke-width=\"4\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "antenna": true
  },
  "captain": {
    "name": "Captain",
    "role": "portfolio-manager",
    "accent": "#2e3f73",
    "eye": "#c9d4ff",
    "behind": "",
    "front": "<path d=\"M70 64C80 40 172 40 182 64Z\" fill=\"#fff\" stroke=\"#d7d9e8\" stroke-width=\"2\"/><rect x=\"64\" y=\"60\" width=\"122\" height=\"14\" rx=\"5\" fill=\"#2e3f73\"/><path d=\"M60 74C80 84 170 84 190 74L186 70C160 78 90 78 64 70Z\" fill=\"#1c2747\"/><path d=\"M126 46L129 54H137L131 59L133 67L126 62L119 67L121 59L115 54H123Z\" fill=\"#e2b84a\"/>",
    "antenna": false
  },
  "echo": {
    "name": "Echo",
    "role": "reflector",
    "accent": "#9b84ef",
    "eye": "#e3dbff",
    "behind": "",
    "front": "<circle cx=\"126\" cy=\"30\" r=\"11\" fill=\"#fff4c9\" stroke=\"#e2b84a\" stroke-width=\"3\"/><path d=\"M121 42H131\" stroke=\"#e2b84a\" stroke-width=\"3\"/><path d=\"M112 22L106 16M140 22L146 16M126 14V7\" stroke=\"#e2b84a\" stroke-width=\"3\" stroke-linecap=\"round\"/><g transform=\"rotate(10 196 160)\"><rect x=\"176\" y=\"134\" width=\"42\" height=\"54\" rx=\"5\" fill=\"#9b84ef\"/><rect x=\"182\" y=\"140\" width=\"32\" height=\"42\" rx=\"3\" fill=\"#fff\"/><path d=\"M187 150H209M187 158H209M187 166H201\" stroke=\"#b8bad0\" stroke-width=\"3\" stroke-linecap=\"round\"/></g>",
    "antenna": false
  },
  "ref": {
    "name": "Ref",
    "role": "tournament (code)",
    "accent": "#3a3a48",
    "eye": "#e8e8f2",
    "behind": "",
    "front": "<clipPath id=\"ref-clip\"><path d=\"M96 166H157L169 201C173 216 161 225 151 220L126 209 102 220C90 225 79 215 84 201L96 166Z\"/></clipPath><g clip-path=\"url(#ref-clip)\"><rect x=\"80\" y=\"160\" width=\"8\" height=\"70\" fill=\"#3a3a48\"/><rect x=\"96\" y=\"160\" width=\"8\" height=\"70\" fill=\"#3a3a48\"/><rect x=\"112\" y=\"160\" width=\"8\" height=\"70\" fill=\"#3a3a48\"/><rect x=\"128\" y=\"160\" width=\"8\" height=\"70\" fill=\"#3a3a48\"/><rect x=\"144\" y=\"160\" width=\"8\" height=\"70\" fill=\"#3a3a48\"/><rect x=\"160\" y=\"160\" width=\"8\" height=\"70\" fill=\"#3a3a48\"/></g><path d=\"M150 150L172 168\" stroke=\"#e2b84a\" stroke-width=\"3\"/><rect x=\"168\" y=\"162\" width=\"22\" height=\"12\" rx=\"6\" fill=\"#c9cbe0\"/><circle cx=\"54\" cy=\"150\" r=\"16\" fill=\"#fff\" stroke=\"#3a3a48\" stroke-width=\"4\"/><path d=\"M54 140V150L61 155\" stroke=\"#bb5a65\" stroke-width=\"3\" stroke-linecap=\"round\"/><rect x=\"50\" y=\"128\" width=\"8\" height=\"6\" rx=\"2\" fill=\"#3a3a48\"/>",
    "antenna": true
  },
  "pilot": {
    "name": "Pilot",
    "role": "autopilot (code)",
    "accent": "#3d8fd1",
    "eye": "#c7e5ff",
    "behind": "",
    "front": "<path d=\"M64 80C66 46 184 46 186 80L178 82C172 60 78 60 72 82Z\" fill=\"#8a5a44\"/><rect x=\"82\" y=\"58\" width=\"36\" height=\"22\" rx=\"11\" fill=\"#2b2a3a\" stroke=\"#3d8fd1\" stroke-width=\"4\"/><rect x=\"132\" y=\"58\" width=\"36\" height=\"22\" rx=\"11\" fill=\"#2b2a3a\" stroke=\"#3d8fd1\" stroke-width=\"4\"/><path d=\"M118 68H132\" stroke=\"#3d8fd1\" stroke-width=\"4\"/><path d=\"M90 64L98 72M140 64L148 72\" stroke=\"#9fd0ff\" stroke-width=\"3\" stroke-linecap=\"round\"/><path d=\"M100 168C116 178 140 178 154 168L158 176C150 184 140 186 134 186L150 210L138 212L126 188C112 188 100 184 96 176Z\" fill=\"#f0f4ff\" stroke=\"#c7d3f0\" stroke-width=\"2\"/>",
    "antenna": false
  }
};
