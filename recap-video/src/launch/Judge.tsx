import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bot, Card, Headline, Kicker, L, Pill, Stage, Sub, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const STOCKS = [
  { symbol: "INFY", note: "Results beat · sector up", keep: true },
  { symbol: "TCS", note: "Clean opening range", keep: true },
  { symbol: "HDFCBANK", note: "Board meeting today", keep: false },
];

const StockCard: React.FC<{ index: number; symbol: string; note: string; keep: boolean }> = ({
  index,
  symbol,
  note,
  keep,
}) => {
  const frame = useCurrentFrame();
  const enter = useIn(24 + index * 9, 18);
  const verdict = useIn(96 + index * 6, 14);
  const shake = !keep ? Math.sin(frame * 1.6) * interpolate(frame, [96, 104, 116], [0, 9, 0], clamp) : 0;
  const drop = !keep ? interpolate(frame, [120, 140], [0, 1], { ...clamp, easing: ease }) : 0;
  return (
    <Card
      style={{
        width: 820,
        padding: "26px 34px",
        display: "flex",
        alignItems: "center",
        gap: 28,
        opacity: enter * (1 - drop * 0.55),
        translate: `${(1 - enter) * 120 + shake}px ${drop * 26}px`,
        borderColor: verdict > 0.5 ? (keep ? L.green : L.red) : L.line,
      }}
    >
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 46, fontWeight: 700, letterSpacing: -1 }}>{symbol}</div>
        <div style={{ fontSize: 30, color: L.muted, marginTop: 4 }}>{note}</div>
      </div>
      <div style={{ opacity: verdict, scale: String(0.8 + verdict * 0.2) }}>
        {keep ? (
          <Pill tone="green" size={32}>Watch at the open</Pill>
        ) : (
          <Pill tone="red" size={32}>Risk scout: dropped</Pill>
        )}
      </div>
    </Card>
  );
};

export const Judge: React.FC = () => (
  <Stage>
    <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 110px", gap: 70 }}>
      <div style={{ width: 760 }}>
        <Bot name="judge" size={200} start={0} />
        <Kicker start={6}>The judge</Kicker>
        <Headline size={88} start={10}>
          Picks up to three. Code can only narrow.
        </Headline>
        <Sub start={22}>A risk scout and a setup planner check every finalist first.</Sub>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
        {STOCKS.map((stock, index) => (
          <StockCard key={stock.symbol} index={index} {...stock} />
        ))}
      </div>
    </AbsoluteFill>
  </Stage>
);
