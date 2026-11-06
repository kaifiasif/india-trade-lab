import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bot, Card, Headline, Kicker, L, Pill, Stage, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const Bubble: React.FC<{
  bot: string;
  name: string;
  text: string;
  start: number;
  side: "left" | "right";
  tone: "green" | "red";
}> = ({ bot, name, text, start, side, tone }) => {
  const t = useIn(start, 16);
  return (
    <div
      style={{
        display: "flex",
        flexDirection: side === "left" ? "row" : "row-reverse",
        alignItems: "center",
        gap: 26,
        opacity: t,
        translate: `${(1 - t) * (side === "left" ? -60 : 60)}px 0px`,
      }}
    >
      <Bot name={bot} size={170} start={start - 4} />
      <Card style={{ width: 560, padding: 28, borderColor: tone === "green" ? L.green : L.red }}>
        <div style={{ fontSize: 28, fontWeight: 700, color: tone === "green" ? L.green : L.red }}>{name}</div>
        <div style={{ fontSize: 33, lineHeight: 1.35, marginTop: 8 }}>{text}</div>
      </Card>
    </div>
  );
};

const STEPS = [
  { bot: "shield", label: "Risk team", note: "Size and stop within limits", start: 104 },
  { bot: "captain", label: "Portfolio manager", note: "Approve one paper entry", start: 122 },
  { bot: "pilot", label: "Autopilot (code)", note: "Records it in the paper book", start: 140 },
];

export const Debate: React.FC = () => {
  const frame = useCurrentFrame();
  const arrow = interpolate(frame, [100, 160], [0, 1], { ...clamp, easing: ease });
  return (
    <Stage>
      <AbsoluteFill style={{ alignItems: "center", paddingTop: 70 }}>
        <Kicker>During the session</Kicker>
        <Headline size={78} width={1700}>
          <span style={{ display: "block", textAlign: "center" }}>A bull and a bear argue. Any role can say no.</span>
        </Headline>
        <div style={{ display: "flex", gap: 90, marginTop: 56 }}>
          <Bubble bot="bullu" name="Bull" text="Clean breakout, volume twice normal, sector leading." start={22} side="left" tone="green" />
          <Bubble bot="bruno" name="Bear" text="Results are priced in. Watch the 1,512 support." start={48} side="right" tone="red" />
        </div>
        <div style={{ position: "relative", display: "flex", gap: 60, marginTop: 64 }}>
          <div
            style={{
              position: "absolute",
              left: 140,
              right: 140,
              top: 58,
              height: 6,
              borderRadius: 3,
              background: `linear-gradient(90deg, ${L.purple} ${arrow * 100}%, #e2ddf2 ${arrow * 100}%)`,
            }}
          />
          {STEPS.map((step) => {
            const t = useIn(step.start, 14);
            return (
              <div key={step.label} style={{ width: 460, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", opacity: t }}>
                <Bot name={step.bot} size={120} start={step.start} float={false} />
                <div style={{ fontSize: 36, fontWeight: 700, marginTop: 12 }}>{step.label}</div>
                <div style={{ fontSize: 28, color: L.muted, marginTop: 6 }}>{step.note}</div>
              </div>
            );
          })}
        </div>
        <div style={{ marginTop: 36, opacity: useIn(160, 14) }}>
          <Pill tone="ink" size={30}>Agents can only narrow. Code holds the limits.</Pill>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
