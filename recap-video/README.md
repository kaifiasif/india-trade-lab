# Paper session recap video

Renders a 24-second, 1080p animated recap of one recorded paper session: the
session tape with entry and exit, each engine stage's throughput, the realized
paper result after charges, and the paper-only disclaimer. Built with
[Remotion](https://www.remotion.dev) 4.0.528, pinned in `package.json`.

This folder is an optional Node project. The trading tools and the observatory
stay standard-library Python and do not depend on it.

## Prerequisites

- Node.js 20.19+ or 22.13+, run from this `recap-video/` folder.
- An observatory export. Run a replay in the observatory, then:

```bash
python3 ../scripts/observatory.py --data-dir ../data/observatory \
  --export-preview ../data/observatory/recap.json
```

## Render

```bash
npm install
npm run render -- out/recap.mp4 --props=../data/observatory/recap.json
```

`npm run render:sample` renders the bundled synthetic example in
`sample/synthetic-recap.json`. `npm run studio` opens Remotion Studio to preview
and adjust scenes. On first render Remotion downloads Chrome Headless Shell;
where downloads are blocked, point it at an installed copy with
`REMOTION_BROWSER=/path/to/headless_shell`.

Every figure in the video comes from the export. A synthetic replay is labelled
as one throughout, and the closing frame states that no real orders were placed.
Keep rendered videos and exports of your own sessions out of Git.

## Licence

Remotion is free for individuals and teams of up to three; larger companies need
a [company licence](https://www.remotion.pro/license).
