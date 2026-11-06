import React from "react";
import { AbsoluteFill } from "remotion";
import { Bot, Headline, Kicker, L, Pill, Stage, Sub, useIn } from "./kit";

const MESSAGES = [
  { from: "bot", text: "Today's Kite login is missing. Log in from Setup, or the desk sees no prices.", start: 26 },
  { from: "me", text: "/pause", start: 62 },
  { from: "bot", text: "Paused: no new paper entries. Exits continue. Send /resume to allow entries.", start: 80 },
  { from: "me", text: "/status", start: 112 },
  { from: "bot", text: "10:42 IST. Entries PAUSED. No problems found.", start: 128 },
];

const Message: React.FC<{ from: string; text: string; start: number }> = ({ from, text, start }) => {
  const t = useIn(start, 12);
  const mine = from === "me";
  return (
    <div style={{ display: "flex", justifyContent: mine ? "flex-end" : "flex-start", opacity: t, translate: `0px ${(1 - t) * 20}px` }}>
      <div
        style={{
          maxWidth: 400,
          padding: "16px 20px",
          borderRadius: 22,
          borderBottomRightRadius: mine ? 6 : 22,
          borderBottomLeftRadius: mine ? 22 : 6,
          background: mine ? L.purple : "#ffffff",
          color: mine ? "white" : L.ink,
          fontSize: 26,
          lineHeight: 1.35,
          fontWeight: mine ? 650 : 450,
          boxShadow: "0 8px 20px -14px rgba(40, 30, 90, 0.5)",
        }}
      >
        {text}
      </div>
    </div>
  );
};

export const Watchdog: React.FC = () => {
  const phone = useIn(6, 20);
  return (
    <Stage>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 130px", gap: 120 }}>
        <div style={{ width: 860 }}>
          <Kicker>Runs while you work</Kicker>
          <Headline size={84}>It tells you when something breaks.</Headline>
          <Sub start={18}>
            A watchdog checks every 2 minutes and messages you on Telegram or email. Pause it from your phone.
          </Sub>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginTop: 38, opacity: useIn(40, 16) }}>
            <Pill tone="ink" size={30}>Missed login or scan</Pill>
            <Pill tone="ink" size={30}>Stalled worker</Pill>
            <Pill tone="ink" size={30}>Disk full</Pill>
            <Pill tone="ink" size={30}>Encrypted nightly backups</Pill>
          </div>
        </div>
        <div
          style={{
            width: 500,
            height: 900,
            borderRadius: 64,
            background: L.night,
            padding: 16,
            boxShadow: "0 60px 120px -50px rgba(40, 30, 90, 0.7)",
            opacity: phone,
            translate: `0px ${(1 - phone) * 80}px`,
          }}
        >
          <div style={{ width: "100%", height: "100%", borderRadius: 50, overflow: "hidden", background: "#ece9f5", display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "40px 24px 18px", background: "#ffffff" }}>
              <Bot name="captain" size={64} float={false} />
              <div>
                <div style={{ fontSize: 26, fontWeight: 700 }}>India Trade Lab</div>
                <div style={{ fontSize: 20, color: L.muted }}>bot · only answers you</div>
              </div>
            </div>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 14, padding: 20, justifyContent: "flex-end" }}>
              {MESSAGES.map((message) => (
                <Message key={message.start} {...message} />
              ))}
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </Stage>
  );
};
