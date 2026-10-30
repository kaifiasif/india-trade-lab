import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bot, L, Logo, Pill, Stage, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

export const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const first = interpolate(frame, [4, 18, 46, 58], [0, 1, 1, 0], { ...clamp, easing: ease });
  const strike = interpolate(frame, [30, 44], [0, 100], { ...clamp, easing: ease });
  const second = useIn(56, 18);
  const brand = useIn(84, 20);
  return (
    <Stage dark>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", textAlign: "center" }}>
        <div
          style={{
            position: "absolute",
            fontSize: 96,
            fontWeight: 700,
            letterSpacing: -3,
            color: "#b9b3d8",
            opacity: first,
          }}
        >
          <span style={{ position: "relative" }}>
            Most trading bots trade every day.
            <span
              style={{
                position: "absolute",
                left: 0,
                top: "54%",
                height: 8,
                borderRadius: 4,
                width: `${strike}%`,
                background: L.red,
              }}
            />
          </span>
        </div>
        <div
          style={{
            opacity: second,
            translate: `0px ${(1 - second) * 30 - brand * 150}px`,
            fontSize: 104,
            fontWeight: 750,
            letterSpacing: -3.5,
            lineHeight: 1.05,
          }}
        >
          This one waits for <span style={{ color: "#b9a6ff" }}>proof</span>.
        </div>
        <div
          style={{
            position: "absolute",
            top: 600,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 30,
            opacity: brand,
            translate: `0px ${(1 - brand) * 30}px`,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
            <Bot name="judge" size={150} start={84} />
            <Logo size={92} dark />
          </div>
          <Pill tone="purple" size={34}>
            An AI research desk for NSE stocks · Paper only
          </Pill>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
