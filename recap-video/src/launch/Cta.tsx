import React from "react";
import { AbsoluteFill } from "remotion";
import { Bot, Logo, Pill, Stage, useIn } from "./kit";

const CREW = ["scoop", "vibe", "chartly", "atlas", "tide", "ledger", "judge", "scout", "blueprint", "ref", "echo", "pilot"];

export const Cta: React.FC = () => {
  const a = useIn(4, 18);
  const b = useIn(20, 18);
  const c = useIn(34, 18);
  return (
    <Stage dark>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", textAlign: "center" }}>
        <div style={{ opacity: a, translate: `0px ${(1 - a) * 30}px`, marginTop: -140 }}>
          <Logo size={120} dark />
        </div>
        <div style={{ fontSize: 58, fontWeight: 650, marginTop: 44, letterSpacing: -1.5, opacity: b }}>
          Open source. Paper only. Free to run.
        </div>
        <div style={{ display: "flex", gap: 20, marginTop: 40, opacity: b }}>
          <Pill tone="purple" size={32}>₹0 hosting on Oracle Cloud</Pill>
          <Pill tone="purple" size={32}>₹0 AI on free tiers</Pill>
        </div>
        <div style={{ fontSize: 46, fontWeight: 700, marginTop: 56, color: "#c9bcff", opacity: c }}>
          github.com/kaifiasif/india-trade-lab
        </div>
      </AbsoluteFill>
      <div style={{ position: "absolute", bottom: 90, width: "100%", display: "flex", justifyContent: "center", gap: 18 }}>
        {CREW.map((name, index) => (
          <Bot key={name} name={name} size={104} start={30 + index * 3} />
        ))}
      </div>
      <div style={{ position: "absolute", bottom: 38, width: "100%", textAlign: "center", fontSize: 24, color: "#9a95bd" }}>
        Not investment advice. No real orders are placed. Kite Connect data costs ₹500 a month.
      </div>
    </Stage>
  );
};
