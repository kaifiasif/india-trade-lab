import React from "react";
import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { Frame } from "../Frame";
import { RecapProps } from "../data";
import { color } from "../theme";

// Throughput per stage, derived exactly as the dashboard derives its funnel counts.
export const stageCounts = (data: RecapProps) => {
  const calls = data.calls ?? [];
  const metrics = data.metrics ?? {};
  return {
    data: Number(metrics.quotes ?? 0),
    strategy: Number(metrics.proposals ?? 0),
    risk: calls.filter((c) => c.side === "buy").length,
    execution: calls.filter((c) => c.status === "filled").length,
    journal: Number(metrics.fills ?? 0),
  };
};

const STAGES = [
  ["data", "Data sentinel", "candles checked"],
  ["strategy", "Setup scout", "entries proposed"],
  ["risk", "Risk guardian", "passed the gate"],
  ["execution", "Paper executor", "paper fills"],
  ["journal", "Journal keeper", "journal entries"],
] as const;

export const Pipeline: React.FC<RecapProps> = (data) => {
  const frame = useCurrentFrame();
  const counts = stageCounts(data);
  const blocked = new Set(
    (data.agents ?? []).filter((a) => a.status === "blocked").map((a) => a.id),
  );
  return (
    <Frame data={data}>
      <AbsoluteFill style={{ paddingLeft: 96, paddingTop: 190 }}>
        <Interactive.Div
          name="Heading"
          style={{
            fontSize: 84,
            fontWeight: 620,
            letterSpacing: -3,
            opacity: interpolate(frame, [0, 16], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          Every decision, stage by stage
        </Interactive.Div>
      </AbsoluteFill>
      <AbsoluteFill
        style={{
          perspective: 2200,
          justifyContent: "center",
          alignItems: "center",
          paddingTop: 170,
        }}
      >
        <div
          style={{
            display: "flex",
            gap: 34,
            alignItems: "flex-end",
            transformStyle: "preserve-3d",
            transform: `rotateX(14deg) rotateY(${interpolate(frame, [0, 180], [-16, -7])}deg)`,
            position: "relative",
          }}
        >
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: "55%",
              height: 4,
              borderRadius: 2,
              background: color.lilac,
            }}
          />
          {STAGES.map(([id, name, caption], index) => {
            const start = 8 + index * 9;
            const rise = interpolate(frame, [start, start + 26], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.16, 1, 0.3, 1),
            });
            const count = Math.round(
              interpolate(frame, [start + 14, start + 60], [0, counts[id]], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: Easing.out(Easing.cubic),
              }),
            );
            const isBlocked = blocked.has(id);
            const height = 360 - index * 26;
            return (
              <div
                key={id}
                style={{
                  width: 300,
                  height,
                  opacity: rise,
                  translate: `0px ${(1 - rise) * 120}px`,
                  borderRadius: 30,
                  background: "white",
                  border: `3px solid ${isBlocked ? "#f0d3d8" : index === 1 ? "#c5b3ea" : color.line}`,
                  boxShadow: "0 12px 0 #e5dff0, 0 40px 60px #6a52a31a",
                  padding: 34,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  position: "relative",
                }}
              >
                <span
                  style={{
                    width: 58,
                    height: 58,
                    borderRadius: 17,
                    display: "grid",
                    placeItems: "center",
                    fontSize: 28,
                    fontWeight: 600,
                    background: isBlocked ? "#fae9ec" : color.lavender,
                    color: isBlocked ? color.red : color.purple,
                  }}
                >
                  {index + 1}
                </span>
                <div>
                  <div
                    style={{
                      fontSize: 92,
                      fontWeight: 600,
                      letterSpacing: -3,
                      color: isBlocked ? color.red : color.ink,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {count}
                  </div>
                  <div style={{ fontSize: 30, fontWeight: 600, marginTop: 6 }}>
                    {name}
                  </div>
                  <div
                    style={{ fontSize: 26, color: color.muted, marginTop: 4 }}
                  >
                    {isBlocked ? "stopped here" : caption}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </Frame>
  );
};
