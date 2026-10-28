import React from "react";
import { AbsoluteFill } from "remotion";
import { Bot, Card, Headline, Kicker, Stage, Sub, useIn } from "./kit";

const TEAM = [
  ["scoop", "News"],
  ["vibe", "Sentiment"],
  ["chartly", "Charts"],
  ["atlas", "Sector"],
  ["tide", "Liquidity"],
  ["ledger", "Broker calls"],
] as const;

const Member: React.FC<{ name: string; label: string; start: number }> = ({
  name,
  label,
  start,
}) => {
  const t = useIn(start + 6, 14);
  return (
    <Card style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: 28, width: 300 }}>
      <Bot name={name} size={200} start={start} />
      <div style={{ fontSize: 34, fontWeight: 650, marginTop: 6, opacity: t }}>{label}</div>
    </Card>
  );
};

export const Desk: React.FC = () => (
  <Stage>
    <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 110px", gap: 80 }}>
      <div style={{ width: 700 }}>
        <Kicker>08:40 · Before the open</Kicker>
        <Headline size={96}>Six AI specialists read every stock.</Headline>
        <Sub start={18}>
          News, sentiment, charts, sectors, liquidity and broker calls, each from dated, cited evidence.
        </Sub>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 300px)", gap: 30 }}>
        {TEAM.map(([name, label], index) => (
          <Member key={name} name={name} label={label} start={10 + index * 7} />
        ))}
      </div>
    </AbsoluteFill>
  </Stage>
);
