import React from "react";
import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { Frame } from "../Frame";
import { RecapProps, money } from "../data";
import { color } from "../theme";

export const Result: React.FC<RecapProps> = (data) => {
  const frame = useCurrentFrame();
  const metrics = data.metrics ?? {};
  const realized = Number(metrics.realized_inr ?? 0);
  const shown = interpolate(frame, [10, 70], [0, realized], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const tone =
    realized > 0 ? color.green : realized < 0 ? color.red : color.ink;
  const facts: [string, string][] = [
    ["Virtual equity", money(metrics.equity_inr)],
    ["Paper fills", String(metrics.fills ?? 0)],
    ["Entries proposed", String(metrics.proposals ?? 0)],
    ["Blocked by a check", String(metrics.blocked ?? 0)],
  ];
  const limits = data.limits ?? {};
  return (
    <Frame data={data}>
      <AbsoluteFill
        style={{ justifyContent: "center", paddingLeft: 96, paddingRight: 96 }}
      >
        <Interactive.Div
          name="Label"
          style={{
            fontSize: 44,
            color: color.muted,
            opacity: interpolate(frame, [0, 14], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          Realized paper result, after charges and slippage
        </Interactive.Div>
        <Interactive.Div
          name="Result"
          style={{
            fontSize: 200,
            fontWeight: 650,
            letterSpacing: -8,
            color: tone,
            fontVariantNumeric: "tabular-nums",
            marginTop: 10,
          }}
        >
          {money(shown)}
        </Interactive.Div>
        <div style={{ display: "flex", gap: 30, marginTop: 56 }}>
          {facts.map(([label, value], index) => (
            <div
              key={label}
              style={{
                flex: 1,
                padding: "30px 34px",
                borderRadius: 26,
                background: "white",
                border: `2px solid ${color.line}`,
                opacity: interpolate(
                  frame,
                  [30 + index * 6, 48 + index * 6],
                  [0, 1],
                  {
                    extrapolateLeft: "clamp",
                    extrapolateRight: "clamp",
                  },
                ),
                translate: interpolate(
                  frame,
                  [30 + index * 6, 56 + index * 6],
                  ["0px 40px", "0px 0px"],
                  {
                    extrapolateLeft: "clamp",
                    extrapolateRight: "clamp",
                    easing: Easing.bezier(0.16, 1, 0.3, 1),
                  },
                ),
              }}
            >
              <div style={{ fontSize: 28, color: color.muted }}>{label}</div>
              <div
                style={{
                  fontSize: 54,
                  fontWeight: 600,
                  marginTop: 10,
                  letterSpacing: -1.5,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {value}
              </div>
            </div>
          ))}
        </div>
        <Interactive.Div
          name="Limits"
          style={{
            marginTop: 44,
            fontSize: 34,
            color: color.purple,
            opacity: interpolate(frame, [70, 90], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          {data.halt_reason
            ? `Entries were halted: ${data.halt_reason}`
            : `Risk capped at ${money(limits.risk, 0)} per trade and ${money(limits.daily_loss, 0)} of planned loss per day.`}
        </Interactive.Div>
      </AbsoluteFill>
    </Frame>
  );
};
