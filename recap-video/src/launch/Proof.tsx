import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bot, Card, Headline, Kicker, L, Pill, Stage, Sub, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
// How 200 random-entry twins finished, bucketed (a made-up, bell-shaped spread).
const TWINS = [2, 4, 7, 12, 18, 24, 28, 27, 23, 18, 13, 9, 6, 4, 3, 1, 1];
const STRATEGY_AT = 15.2; // Bucket position of the real strategy: beyond 97% of twins.
const W = 820;
const H = 380;
const barW = W / TWINS.length;

const Check: React.FC<{ label: string; value: string; start: number }> = ({ label, value, start }) => {
  const t = useIn(start, 14);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14, opacity: t, translate: `0px ${(1 - t) * 16}px` }}>
      <Pill tone="green" size={28}>✓</Pill>
      <span style={{ fontSize: 30, fontWeight: 600 }}>{label}</span>
      <span style={{ fontSize: 30, color: L.muted }}>{value}</span>
    </div>
  );
};

export const Proof: React.FC = () => {
  const frame = useCurrentFrame();
  const grow = interpolate(frame, [18, 70], [0, 1], { ...clamp, easing: ease });
  const marker = useIn(74, 18);
  const most = Math.max(...TWINS);
  return (
    <Stage>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 110px", gap: 70 }}>
        <div style={{ width: 700 }}>
          <Bot name="ref" size={180} start={0} />
          <Kicker start={6}>16:10 · The tournament</Kicker>
          <Headline size={82} start={10}>Better than luck, or it sits out.</Headline>
          <Sub start={22}>
            Every strategy is replayed at double charges and raced against 200 copies that enter at random.
          </Sub>
        </div>
        <Card style={{ padding: 34 }}>
          <div style={{ fontSize: 30, fontWeight: 650 }}>Opening-range breakout vs 200 random twins</div>
          <svg width={W} height={H + 70} style={{ marginTop: 18 }}>
            {TWINS.map((count, index) => {
              const h = (count / most) * H * grow;
              return <rect key={index} x={index * barW + 4} width={barW - 8} y={H - h} height={h} rx={6} fill="#d8d2ec" />;
            })}
            <g opacity={marker}>
              <line x1={STRATEGY_AT * barW} x2={STRATEGY_AT * barW} y1={40 - (1 - marker) * 30} y2={H} stroke={L.green} strokeWidth={6} strokeLinecap="round" />
              <text x={STRATEGY_AT * barW - 14} y={34} textAnchor="end" fontSize={28} fontWeight={700} fill={L.green}>
                Beat 97% of them
              </text>
            </g>
            <text x={0} y={H + 46} fontSize={24} fill={L.muted}>Net result after double charges →</text>
          </svg>
          <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 10 }}>
            <Check label="Profit factor" value="1.32 (needs 1.15)" start={100} />
            <Check label="Deflated Sharpe" value="0.97 after 14 variants tried" start={112} />
            <Check label="Today's regime" value="up/calm: proven here" start={124} />
          </div>
        </Card>
      </AbsoluteFill>
    </Stage>
  );
};
