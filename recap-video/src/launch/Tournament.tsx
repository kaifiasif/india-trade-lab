import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bot, Card, Headline, Kicker, L, Pill, Stage, Sub, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const Strategy: React.FC<{ name: string; factor: number; start: number; pass: boolean }> = ({
  name,
  factor,
  start,
  pass,
}) => {
  const frame = useCurrentFrame();
  const enter = useIn(start, 16);
  const grow = interpolate(frame, [start + 14, start + 60], [0, factor], { ...clamp, easing: ease });
  const verdict = useIn(start + 62, 12);
  const scale = 1.6; // Bar runs from 0 to a profit factor of 1.6.
  return (
    <Card style={{ width: 860, opacity: enter, translate: `0px ${(1 - enter) * 40}px` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 44, fontWeight: 700, letterSpacing: -1 }}>{name}</div>
        <div style={{ opacity: verdict }}>
          {pass ? <Pill tone="green" size={32}>✓ May trade</Pill> : <Pill tone="red" size={32}>✕ Sits out</Pill>}
        </div>
      </div>
      <div style={{ fontSize: 28, color: L.muted, marginTop: 14 }}>Profit factor at double costs</div>
      <div style={{ position: "relative", height: 44, marginTop: 14, borderRadius: 14, background: "#efedf6" }}>
        <div
          style={{
            height: "100%",
            width: `${(grow / scale) * 100}%`,
            borderRadius: 14,
            background: pass ? L.green : L.red,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: -10,
            bottom: -10,
            left: `${(1.15 / scale) * 100}%`,
            width: 4,
            background: L.ink,
            borderRadius: 2,
          }}
        />
        <div style={{ position: "absolute", right: 18, top: 2, fontSize: 32, fontWeight: 700 }}>{grow.toFixed(2)}</div>
      </div>
      <div style={{ fontSize: 24, color: L.muted, marginTop: 14 }}>Line marks the 1.15 bar it must clear</div>
    </Card>
  );
};

export const Tournament: React.FC = () => (
  <Stage>
    <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 110px", gap: 70 }}>
      <div style={{ width: 760 }}>
        <Bot name="ref" size={190} start={0} />
        <Kicker start={6}>16:10 · Every evening</Kicker>
        <Headline size={88} start={10}>Only proven strategies may trade.</Headline>
        <Sub start={22}>Each one is replayed on your own history with pessimistic fills and double costs.</Sub>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 34 }}>
        <Strategy name="Opening-range breakout" factor={1.32} start={20} pass />
        <Strategy name="VWAP pullback" factor={0.94} start={34} pass={false} />
      </div>
    </AbsoluteFill>
  </Stage>
);
