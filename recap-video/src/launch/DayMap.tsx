import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bot, Headline, Kicker, L, Stage, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const STOPS = [
  { time: "08:40", bot: "scoop", title: "Scan", note: "Every F&O stock, news, NSE lists" },
  { time: "09:09", bot: "judge", title: "Pick", note: "Specialists report, the judge picks" },
  { time: "09:15", bot: "bullu", title: "Debate", note: "Bull, bear and risk team argue" },
  { time: "09:20", bot: "pilot", title: "Paper trade", note: "Code checks, then records" },
  { time: "15:05", bot: "shield", title: "Square off", note: "Every intraday trade closed" },
  { time: "16:10", bot: "echo", title: "Learn", note: "Graded, tested, lessons saved" },
];

export const DayMap: React.FC = () => {
  const frame = useCurrentFrame();
  const line = interpolate(frame, [24, 150], [0, 1], { ...clamp, easing: ease });
  return (
    <Stage>
      <AbsoluteFill style={{ padding: "130px 110px 0" }}>
        <Kicker>How the agents work</Kicker>
        <Headline size={84} width={1700}>
          One trading day, start to finish. On its own.
        </Headline>
        <div style={{ position: "relative", marginTop: 150, height: 560 }}>
          <div style={{ position: "absolute", left: 120, right: 120, top: 175, height: 8, borderRadius: 4, background: "#e2ddf2" }} />
          <div
            style={{
              position: "absolute",
              left: 120,
              top: 175,
              height: 8,
              borderRadius: 4,
              width: `calc((100% - 240px) * ${line})`,
              background: L.purple,
            }}
          />
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            {STOPS.map((stop, index) => {
              const start = 24 + index * 21;
              const t = useIn(start + 8, 16);
              const reached = line >= index / (STOPS.length - 1) - 0.01;
              return (
                <div key={stop.time} style={{ width: 240, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
                  <Bot name={stop.bot} size={160} start={start} float={false} />
                  <div
                    style={{
                      width: 30,
                      height: 30,
                      marginTop: 4,
                      borderRadius: 15,
                      background: reached ? L.purple : "#ffffff",
                      border: `5px solid ${reached ? L.purple : "#d6cfee"}`,
                    }}
                  />
                  <div style={{ fontSize: 34, fontWeight: 700, marginTop: 24, color: L.purple, opacity: t }}>{stop.time}</div>
                  <div style={{ fontSize: 42, fontWeight: 700, marginTop: 4, letterSpacing: -1, opacity: t }}>{stop.title}</div>
                  <div style={{ fontSize: 28, lineHeight: 1.3, color: L.muted, marginTop: 8, opacity: t }}>{stop.note}</div>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
