import React from "react";
import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { Frame } from "../Frame";
import { CLOSE, OPEN, RecapProps, clockIST, minutesIST, money } from "../data";
import { color } from "../theme";

const W = 1560;
const H = 560;
const DRAW_START = 12;
const DRAW_END = 168;

// The session's recorded bids drawn left to right on a tilted plane, with the paper
// entry and exit pinned where they happened and the planned stop and target bands.
export const Tape: React.FC<RecapProps> = (data) => {
  const frame = useCurrentFrame();
  const prices = (data.prices ?? []).map((p) => ({
    m: minutesIST(p.at),
    v: Number(p.price),
  }));
  const calls = (data.calls ?? []).filter((c) => c.fill_inr != null);
  const entry = calls.find((c) => c.side === "buy");
  const exit = calls.find((c) => c.side === "sell");
  const values = [
    ...prices.map((p) => p.v),
    ...calls.map((c) => Number(c.fill_inr)),
    ...(entry?.stop ? [Number(entry.stop)] : []),
    ...(entry?.target ? [Number(entry.target)] : []),
  ];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo || 1) * 0.14;
  const x = (m: number) => ((m - OPEN) / (CLOSE - OPEN)) * W;
  const y = (v: number) =>
    H - 30 - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - 60);
  const line = prices
    .map((p, i) => `${i ? "L" : "M"}${x(p.m).toFixed(1)},${y(p.v).toFixed(1)}`)
    .join(" ");
  const area = prices.length
    ? `${line} L${x(prices[prices.length - 1].m)},${H} L${x(prices[0].m)},${H} Z`
    : "";
  const progress = interpolate(frame, [DRAW_START, DRAW_END], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.45, 0, 0.25, 1),
  });
  const reveal = (m: number) =>
    DRAW_START + (x(m) / W) * (DRAW_END - DRAW_START);
  const pop = (m: number) =>
    interpolate(frame, [reveal(m), reveal(m) + 14], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.34, 1.56, 0.64, 1),
    });
  const hours = [10, 11, 12, 13, 14, 15];
  const bandFrom = entry ? x(minutesIST(entry.at)) : 0;
  const bandTo = exit ? x(minutesIST(exit.at)) : W;
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
          How the session moved
        </Interactive.Div>
      </AbsoluteFill>
      <AbsoluteFill
        style={{
          perspective: 2000,
          justifyContent: "flex-end",
          alignItems: "center",
          paddingBottom: 120,
        }}
      >
        <div
          style={{
            width: W,
            height: H,
            position: "relative",
            transformStyle: "preserve-3d",
            transform: `rotateX(${interpolate(frame, [0, 240], [30, 16])}deg) rotateY(${interpolate(frame, [0, 240], [-14, -4])}deg)`,
            background: "#ffffffd9",
            borderRadius: 28,
            border: `2px solid ${color.line}`,
            boxShadow: "0 60px 90px #6a52a31f",
          }}
        >
          <svg
            width={W}
            height={H}
            viewBox={`0 0 ${W} ${H}`}
            style={{ position: "absolute", inset: 0, overflow: "visible" }}
          >
            <defs>
              <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor={color.violet} stopOpacity="0.38" />
                <stop offset="1" stopColor={color.violet} stopOpacity="0" />
              </linearGradient>
              <clipPath id="drawn">
                <rect
                  x={-20}
                  y={-200}
                  width={progress * W + 20}
                  height={H + 400}
                />
              </clipPath>
            </defs>
            {hours.map((h) => (
              <g key={h}>
                <line
                  x1={x(h * 60)}
                  x2={x(h * 60)}
                  y1={20}
                  y2={H}
                  stroke={color.line}
                  strokeWidth={2}
                />
                <text
                  x={x(h * 60)}
                  y={H + 46}
                  fill={color.muted}
                  fontSize={28}
                  textAnchor="middle"
                >
                  {`${h}:00`}
                </text>
              </g>
            ))}
            <g clipPath="url(#drawn)">
              {entry?.target ? (
                <rect
                  x={bandFrom}
                  width={bandTo - bandFrom}
                  y={y(Number(entry.target)) - 4}
                  height={8}
                  rx={4}
                  fill={color.green}
                  opacity={0.35 * pop(minutesIST(entry.at))}
                />
              ) : null}
              {entry?.stop ? (
                <rect
                  x={bandFrom}
                  width={bandTo - bandFrom}
                  y={y(Number(entry.stop)) - 4}
                  height={8}
                  rx={4}
                  fill={color.red}
                  opacity={0.35 * pop(minutesIST(entry.at))}
                />
              ) : null}
              <path d={area} fill="url(#area)" />
              <path
                d={line}
                fill="none"
                stroke={color.purple}
                strokeWidth={6}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            </g>
            {calls.map((call, index) => {
              const m = minutesIST(call.at);
              const s = pop(m);
              const px = x(m);
              const py = y(Number(call.fill_inr));
              const fill = call.side === "buy" ? color.green : color.purple;
              return (
                <g key={index} opacity={s}>
                  <line
                    x1={px}
                    x2={px}
                    y1={py}
                    y2={H}
                    stroke={fill}
                    strokeWidth={3}
                    strokeDasharray="6 8"
                  />
                  <circle
                    cx={px}
                    cy={py}
                    r={16 * s}
                    fill={fill}
                    stroke="white"
                    strokeWidth={5}
                  />
                </g>
              );
            })}
            {entry?.stop ? (
              <text
                x={bandFrom + (bandTo - bandFrom) / 2}
                y={y(Number(entry.stop)) + 46}
                textAnchor="middle"
                fill={color.red}
                fontSize={28}
                fontWeight={600}
                opacity={pop(minutesIST(exit?.at ?? entry.at))}
              >
                {`Stop ${money(entry.stop)}`}
              </text>
            ) : null}
            {entry?.target ? (
              <text
                x={bandFrom + (bandTo - bandFrom) / 2}
                y={y(Number(entry.target)) - 22}
                textAnchor="middle"
                fill={color.green}
                fontSize={28}
                fontWeight={600}
                opacity={pop(minutesIST(exit?.at ?? entry.at))}
              >
                {`Target ${money(entry.target)}`}
              </text>
            ) : null}
          </svg>
          {calls.map((call, index) => {
            const m = minutesIST(call.at);
            const s = pop(m);
            const buy = call.side === "buy";
            return (
              <div
                key={index}
                style={{
                  position: "absolute",
                  left: x(m),
                  top: y(Number(call.fill_inr)) - 34,
                  // Keep pills inside the card near either end of the session.
                  translate:
                    x(m) > W * 0.78
                      ? "calc(-100% + 34px) -100%"
                      : x(m) < W * 0.22
                        ? "-34px -100%"
                        : "-50% -100%",
                  opacity: s,
                  scale: String(0.8 + 0.2 * s),
                  padding: "12px 22px",
                  borderRadius: 14,
                  background: buy ? color.green : color.purple,
                  color: "white",
                  fontSize: 30,
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                  boxShadow: "0 14px 30px #25253222",
                }}
              >
                {`${buy ? "Bought" : "Sold"} ${call.qty ?? ""} at ${money(call.fill_inr)}, ${clockIST(call.at)}`}
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </Frame>
  );
};
