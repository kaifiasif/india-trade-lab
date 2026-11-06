import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bot, Card, Headline, Kicker, L, Pill, Stage, Sub, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const CHECKS = [
  "Quote under 2 minutes old",
  "India VIX and Nifty calm",
  "Not under NSE surveillance",
  "Not held in the other book",
  "Stop and target recorded",
  "Reward ≥ 1.5× risk after charges",
  "Portfolio risk under 5%",
  "Strategy proven in today's regime",
];
const FAIL = 6; // The second stock trips the portfolio cap.

const Row: React.FC<{ label: string; index: number; start: number; failAt?: number }> = ({ label, index, start, failAt }) => {
  const at = start + index * 6;
  const t = useIn(at, 10);
  const failed = failAt === index;
  const skipped = failAt !== undefined && index > failAt;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 28, opacity: skipped ? 0.25 * t : t }}>
      <span
        style={{
          width: 38,
          height: 38,
          borderRadius: 19,
          display: "grid",
          placeItems: "center",
          fontWeight: 800,
          fontSize: 24,
          color: "white",
          background: skipped ? "#cfcbe0" : failed ? L.red : L.green,
          scale: String(0.6 + t * 0.4),
        }}
      >
        {failed ? "✕" : skipped ? "·" : "✓"}
      </span>
      <span style={{ fontWeight: failed ? 700 : 500, color: failed ? L.red : L.ink }}>{label}</span>
    </div>
  );
};

const Ticket: React.FC<{ symbol: string; start: number; failAt?: number; verdict: string }> = ({ symbol, start, failAt, verdict }) => {
  const enter = useIn(start - 10, 16);
  const end = start + (failAt === undefined ? CHECKS.length : failAt + 1) * 6 + 8;
  const done = useIn(end, 14);
  return (
    <Card style={{ width: 575, padding: 28, opacity: enter, translate: `0px ${(1 - enter) * 40}px`, borderColor: done > 0.5 ? (failAt === undefined ? L.green : L.red) : L.line }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 44, fontWeight: 700, letterSpacing: -1 }}>{symbol}</span>
        <span style={{ opacity: done }}>
          <Pill tone={failAt === undefined ? "green" : "red"} size={28}>{verdict}</Pill>
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 20 }}>
        {CHECKS.map((label, index) => (
          <Row key={label} label={label} index={index} start={start} failAt={failAt} />
        ))}
      </div>
    </Card>
  );
};

export const Gates: React.FC = () => {
  const frame = useCurrentFrame();
  const glow = interpolate(frame, [0, 30], [0, 1], { ...clamp, easing: ease });
  return (
    <Stage>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 90px", gap: 40 }}>
        <div style={{ width: 540, opacity: glow }}>
          <Bot name="shield" size={180} start={0} />
          <Kicker start={6}>Before every entry</Kicker>
          <Headline size={80} start={10}>Eight checks. One no is enough.</Headline>
          <Sub start={22}>Written in code, not prompts. An agent cannot talk its way past them.</Sub>
        </div>
        <div style={{ display: "flex", gap: 30 }}>
          <Ticket symbol="INFY" start={30} verdict="Paper buy" />
          <Ticket symbol="TCS" start={86} failAt={FAIL} verdict="Blocked: too much risk" />
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
