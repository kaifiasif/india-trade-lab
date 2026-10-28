import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { Headline, Kicker, L, Stage } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const SHOTS = [
  { file: "today", label: "Today's picks" },
  { file: "replay", label: "Paper replay" },
  { file: "learning", label: "Learning" },
  { file: "routing", label: "Setup from the browser" },
];
const EACH = 54;

export const Product: React.FC = () => {
  const frame = useCurrentFrame();
  const rise = interpolate(frame, [0, 22], [60, 0], clamp);
  return (
    <Stage>
      <AbsoluteFill style={{ alignItems: "center", paddingTop: 70 }}>
        <Kicker>The dashboard</Kicker>
        <Headline size={72} start={2} width={1600}>
          Set up and watch it all from your browser.
        </Headline>
        <div
          style={{
            marginTop: 40,
            width: 1320,
            height: 720,
            borderRadius: 26,
            overflow: "hidden",
            border: `2px solid ${L.line}`,
            background: L.paper,
            boxShadow: "0 50px 120px -50px rgba(60, 40, 120, 0.55)",
            translate: `0px ${rise}px`,
          }}
        >
          <div style={{ height: 44, display: "flex", alignItems: "center", gap: 10, padding: "0 20px", background: "#f1eff7" }}>
            {["#f26d6d", "#f2c14e", "#5fcf86"].map((dot) => (
              <span key={dot} style={{ width: 14, height: 14, borderRadius: 7, background: dot }} />
            ))}
            <span style={{ marginLeft: 20, fontSize: 20, color: L.muted }}>127.0.0.1:8765</span>
          </div>
          <div style={{ position: "relative", height: 676 }}>
            {SHOTS.map((shot, index) => {
              const start = index * EACH;
              const opacity = interpolate(frame, [start - 10, start + 4, start + EACH, start + EACH + 12], [0, 1, 1, index === SHOTS.length - 1 ? 1 : 0], clamp);
              const zoom = interpolate(frame, [start, start + EACH + 12], [1, 1.06], clamp);
              return (
                <Img
                  key={shot.file}
                  src={staticFile(`launch/${shot.file}.png`)}
                  style={{
                    position: "absolute",
                    inset: 0,
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                    objectPosition: "top left",
                    opacity: index === 0 ? Math.max(opacity, frame < EACH ? 1 : 0) : opacity,
                    scale: String(zoom),
                    transformOrigin: "30% 20%",
                  }}
                />
              );
            })}
            {SHOTS.map((shot, index) => {
              const start = index * EACH;
              const show = interpolate(frame, [start + 4, start + 14, start + EACH - 4, start + EACH + 6], [0, 1, 1, index === SHOTS.length - 1 ? 1 : 0], clamp);
              return (
                <div
                  key={shot.label}
                  style={{
                    position: "absolute",
                    left: 36,
                    bottom: 36,
                    padding: "14px 28px",
                    borderRadius: 999,
                    background: L.night,
                    color: "white",
                    fontSize: 34,
                    fontWeight: 650,
                    opacity: show,
                  }}
                >
                  {shot.label}
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
