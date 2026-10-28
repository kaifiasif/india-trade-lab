import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Card, Headline, Kicker, L, Pill, Stage, Sub, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
// A made-up intraday path: opening range, breakout, pullback, run to target.
const PATH = [100, 100.4, 99.8, 100.2, 99.9, 100.3, 100.9, 101.1, 100.8, 101.4, 101.2, 101.9, 102.3, 102.1, 102.7, 103.1, 102.9, 103.4, 104.0, 104.1];
const ENTRY_INDEX = 6;
const STOP = 99.4;
const TARGET = 104;
const W = 900;
const H = 520;
const x = (index: number) => 40 + (index / (PATH.length - 1)) * (W - 80);
const y = (price: number) => 30 + (1 - (price - 98.8) / (104.8 - 98.8)) * (H - 60);

export const Trade: React.FC = () => {
  const frame = useCurrentFrame();
  const draw = interpolate(frame, [20, 140], [0, PATH.length - 1], { ...clamp, easing: ease });
  const shown = Math.floor(draw);
  const points = PATH.slice(0, shown + 1).map((price, index) => `${x(index)},${y(price)}`);
  const partial = draw - shown;
  if (shown < PATH.length - 1) {
    const px = x(shown) + (x(shown + 1) - x(shown)) * partial;
    const py = y(PATH[shown] + (PATH[shown + 1] - PATH[shown]) * partial);
    points.push(`${px},${py}`);
  }
  const levels = useIn(46, 14);
  const hit = useIn(140, 14);
  return (
    <Stage>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 110px", gap: 70 }}>
        <div style={{ width: 720 }}>
          <Kicker>09:15 – 15:15</Kicker>
          <Headline size={88}>Paper trades, hard limits.</Headline>
          <Sub start={18}>Code sizes every trade from your limits. No agent can raise them.</Sub>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginTop: 40, opacity: useIn(30, 16) }}>
            <Pill tone="ink" size={30}>₹250 risk a trade</Pill>
            <Pill tone="ink" size={30}>₹750 daily loss stop</Pill>
            <Pill tone="ink" size={30}>Square-off 15:15</Pill>
          </div>
        </div>
        <Card style={{ padding: 30, position: "relative" }}>
          <svg width={W} height={H}>
            <defs>
              <linearGradient id="area" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stopColor={L.purple} stopOpacity="0.22" />
                <stop offset="1" stopColor={L.purple} stopOpacity="0" />
              </linearGradient>
            </defs>
            <g opacity={levels}>
              <line x1={40} x2={W - 40} y1={y(TARGET)} y2={y(TARGET)} stroke={L.green} strokeWidth={3} strokeDasharray="12 10" />
              <text x={W - 40} y={y(TARGET) - 12} textAnchor="end" fontSize={26} fontWeight={700} fill={L.green}>Target</text>
              <line x1={40} x2={W - 40} y1={y(STOP)} y2={y(STOP)} stroke={L.red} strokeWidth={3} strokeDasharray="12 10" />
              <text x={W - 40} y={y(STOP) + 34} textAnchor="end" fontSize={26} fontWeight={700} fill={L.red}>Stop</text>
            </g>
            <polygon points={`${points.join(" ")} ${points.at(-1)?.split(",")[0]},${H - 30} 40,${H - 30}`} fill="url(#area)" />
            <polyline points={points.join(" ")} fill="none" stroke={L.purple} strokeWidth={6} strokeLinejoin="round" strokeLinecap="round" />
            {draw >= ENTRY_INDEX && (
              <g>
                <circle cx={x(ENTRY_INDEX)} cy={y(PATH[ENTRY_INDEX])} r={14} fill={L.green} stroke="white" strokeWidth={4} />
                <text x={x(ENTRY_INDEX) + 24} y={y(PATH[ENTRY_INDEX]) + 64} textAnchor="start" fontSize={28} fontWeight={700} fill={L.ink}>Paper buy</text>
              </g>
            )}
          </svg>
          <div style={{ position: "absolute", left: 80, top: 60, opacity: hit, scale: String(0.7 + hit * 0.3) }}>
            <Pill tone="green" size={40}>Target hit · +2.0R</Pill>
          </div>
        </Card>
      </AbsoluteFill>
    </Stage>
  );
};
