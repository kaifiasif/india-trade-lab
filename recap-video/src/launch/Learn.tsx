import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Bot, Card, Headline, Kicker, L, Pill, Stage, Sub, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const LESSON =
  "You said positive on RELIANCE, but it fell 0.8% open to close. Note which piece of your evidence misled you.";

export const Learn: React.FC = () => {
  const frame = useCurrentFrame();
  const typed = Math.floor(interpolate(frame, [30, 105], [0, LESSON.length], clamp));
  const accuracy = interpolate(frame, [110, 160], [45, 58], { ...clamp, easing: ease });
  const card = useIn(18, 16);
  const record = useIn(104, 16);
  const cool = useIn(150, 14);
  return (
    <Stage>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 110px", gap: 70 }}>
        <div style={{ width: 740 }}>
          <Bot name="echo" size={190} start={0} />
          <Kicker start={6}>Every evening</Kicker>
          <Headline size={88} start={10}>Every agent learns from its mistakes.</Headline>
          <Sub start={22}>Calls are graded on what the stock really did. Lessons are read the next morning.</Sub>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 30, width: 860 }}>
          <Card style={{ opacity: card, translate: `0px ${(1 - card) * 40}px` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <Bot name="chartly" size={84} float={false} />
              <div style={{ fontSize: 38, fontWeight: 700 }}>Technicals</div>
              <Pill tone="red" size={26}>wrong</Pill>
            </div>
            <div style={{ fontSize: 34, lineHeight: 1.4, marginTop: 18, minHeight: 145 }}>
              {LESSON.slice(0, typed)}
              <span style={{ opacity: frame % 20 < 10 && typed < LESSON.length ? 1 : 0, color: L.purple }}>|</span>
            </div>
          </Card>
          <Card style={{ opacity: record, translate: `0px ${(1 - record) * 40}px` }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 34, fontWeight: 650 }}>
              <span>Technicals accuracy</span>
              <span>{Math.round(accuracy)}%</span>
            </div>
            <div style={{ height: 22, marginTop: 18, borderRadius: 11, background: "#efedf6" }}>
              <div style={{ height: "100%", width: `${accuracy}%`, borderRadius: 11, background: L.purple }} />
            </div>
          </Card>
          <div style={{ opacity: cool, translate: `0px ${(1 - cool) * 20}px` }}>
            <Pill tone="amber" size={34}>❄ TCS sits out 7 days after two stop-outs</Pill>
          </div>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
