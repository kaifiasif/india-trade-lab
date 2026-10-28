import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bot, Card, Headline, Kicker, L, Pill, Stage, Sub, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const SIMPLE = ["scoop", "vibe", "chartly", "atlas", "tide", "ledger", "scout", "blueprint"];

/** A dot that keeps travelling along a horizontal wire. */
const Wire: React.FC<{ y: number; start: number; color: string }> = ({ y, start, color }) => {
  const frame = useCurrentFrame();
  const shown = useIn(start, 12);
  const dots = [0, 0.33, 0.66].map((offset) => ((frame - start) / 40 + offset) % 1);
  return (
    <div style={{ position: "absolute", left: 0, top: y, width: 160, height: 6, opacity: shown }}>
      <div style={{ position: "absolute", inset: 0, borderRadius: 3, background: "#dcd6f0" }} />
      {frame > start &&
        dots.map((at, index) => (
          <div
            key={index}
            style={{
              position: "absolute",
              left: `${at * 100}%`,
              top: -7,
              width: 20,
              height: 20,
              borderRadius: 10,
              background: color,
            }}
          />
        ))}
    </div>
  );
};

export const Route: React.FC = () => {
  const frame = useCurrentFrame();
  const used = Math.round(interpolate(frame, [40, 140], [0, 12], { ...clamp, easing: ease }));
  return (
    <Stage>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 110px", gap: 60 }}>
        <div style={{ width: 600 }}>
          <Kicker>Smart routing</Kicker>
          <Headline size={88}>Free tier first. Your quota lasts.</Headline>
          <Sub start={18}>Simple jobs go to a free model, the judge to a strong one. Reruns come from a cache.</Sub>
        </div>
        <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 0 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
            <Card style={{ width: 400, padding: 28 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 80px)", gap: 8 }}>
                {SIMPLE.map((name, index) => (
                  <Bot key={name} name={name} size={80} start={8 + index * 3} float={false} />
                ))}
              </div>
              <div style={{ fontSize: 28, fontWeight: 650, marginTop: 12 }}>8 simple jobs</div>
            </Card>
            <Card style={{ width: 400, padding: 28, display: "flex", alignItems: "center", gap: 16 }}>
              <Bot name="judge" size={96} start={30} float={false} />
              <div style={{ fontSize: 28, fontWeight: 650 }}>The judge</div>
            </Card>
          </div>
          <div style={{ position: "relative", width: 160, height: 460 }}>
            <Wire y={140} start={36} color={L.green} />
            <Wire y={370} start={50} color={L.purple} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
            <Card style={{ width: 380, padding: 28, opacity: useIn(30, 14) }}>
              <Pill tone="green" size={28}>Free tier</Pill>
              <div style={{ fontSize: 30, marginTop: 16, fontWeight: 650 }}>{used} / 200 calls today</div>
              <div style={{ height: 16, marginTop: 14, borderRadius: 8, background: "#efedf6" }}>
                <div style={{ height: "100%", width: `${(used / 200) * 100}%`, minWidth: 8, borderRadius: 8, background: L.green }} />
              </div>
            </Card>
            <Card style={{ width: 380, padding: 28, opacity: useIn(44, 14) }}>
              <Pill tone="purple" size={28}>Strong tier</Pill>
              <div style={{ fontSize: 30, marginTop: 16, fontWeight: 650 }}>1 call · capped at 30</div>
            </Card>
          </div>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
