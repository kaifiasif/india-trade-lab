import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bot, Card, Headline, Kicker, L, Pill, Stage, Sub, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const ITEMS = [
  { tag: "#news", text: "Q2 results beat estimates · 24 Oct" },
  { tag: "#scan", text: "Delivery 62% · open interest rising" },
  { tag: "#market", text: "Regime up/calm · 1,200 stocks up" },
  { tag: "#caution", text: "No NSE surveillance flags" },
];

const Chip: React.FC<{ index: number; tag: string; text: string }> = ({ index, tag, text }) => {
  const frame = useCurrentFrame();
  const start = 16 + index * 9;
  const enter = useIn(start, 16);
  // Each chip slides toward the analyst, then settles beside it.
  const absorb = interpolate(frame, [86 + index * 4, 104 + index * 4], [0, 1], { ...clamp, easing: ease });
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "18px 26px",
        borderRadius: 20,
        background: L.paper,
        border: `2px solid ${L.line}`,
        boxShadow: "0 16px 40px -26px rgba(60, 40, 120, 0.4)",
        opacity: enter * (1 - absorb * 0.55),
        translate: `${(1 - enter) * -80 + absorb * 40}px 0px`,
        scale: String(1 - absorb * 0.06),
      }}
    >
      <Pill tone="purple" size={28}>{tag}</Pill>
      <span style={{ fontSize: 29, fontWeight: 550 }}>{text}</span>
    </div>
  );
};

export const Evidence: React.FC = () => {
  const frame = useCurrentFrame();
  const think = useIn(84, 14);
  const verdict = useIn(118, 16);
  const dots = Math.floor(frame / 8) % 4;
  return (
    <Stage>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 110px", gap: 70 }}>
        <div style={{ width: 660 }}>
          <Kicker>Inside one agent</Kicker>
          <Headline size={74}>Evidence in.<br />Cited verdict out.</Headline>
          <Sub start={18}>Each specialist sees only dated, sourced facts, and must quote them. No evidence, no opinion.</Sub>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 40 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 20, width: 560 }}>
            {ITEMS.map((item, index) => (
              <Chip key={item.tag} index={index} {...item} />
            ))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 22, width: 420 }}>
            <Bot name="chartly" size={210} start={6} />
            <div style={{ fontSize: 30, fontWeight: 650, color: L.muted, opacity: think * (1 - verdict) }}>
              Reading{".".repeat(dots)}
            </div>
            <Card
              style={{
                width: 420,
                padding: 28,
                opacity: verdict,
                translate: `0px ${(1 - verdict) * 30}px`,
                borderColor: L.green,
                marginTop: -60,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <Pill tone="green" size={30}>Positive</Pill>
                <span style={{ fontSize: 30, fontWeight: 650 }}>70% sure</span>
              </div>
              <div style={{ fontSize: 27, lineHeight: 1.35, marginTop: 16, color: L.ink }}>
                "Breakout on rising delivery after a results beat."
              </div>
              <div style={{ fontSize: 24, color: L.muted, marginTop: 12 }}>Cites #scan, #news</div>
            </Card>
          </div>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
