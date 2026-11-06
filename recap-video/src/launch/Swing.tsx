import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Card, Headline, Kicker, L, Pill, Stage, Sub, ease, useIn } from "./kit";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
// A made-up daily chart: a quiet base, then a breakout on twice the usual volume.
const CANDLES = [
  [100, 101.2, 99.4, 100.6], [100.6, 101.0, 99.8, 100.1], [100.1, 100.9, 99.5, 100.7], [100.7, 101.4, 100.2, 100.4],
  [100.4, 101.1, 99.9, 100.9], [100.9, 101.3, 100.1, 100.3], [100.3, 101.2, 99.8, 101.0], [101.0, 101.5, 100.4, 100.8],
  [100.8, 101.4, 100.3, 101.2], [101.2, 101.6, 100.6, 100.9], [100.9, 101.7, 100.7, 101.4], [101.4, 104.2, 101.3, 103.9],
] as const;
const VOLUME = [52, 47, 55, 49, 50, 44, 53, 48, 51, 46, 58, 118];
const H = 600;
const PRICE_H = 430;
const low = 99;
const high = 108.6;
const y = (price: number) => 20 + (1 - (price - low) / (high - low)) * (PRICE_H - 40);
const step = 46;
const cx = (index: number) => 40 + index * step;
// Simulated five-day paths after the breakout, ending above target, below stop or in between.
const PATHS = [
  [103.9, 104.6, 105.4, 106.1, 107.2, 107.6], [103.9, 103.4, 104.2, 105.3, 106.0, 107.4],
  [103.9, 104.1, 103.2, 102.6, 102.0, 101.6], [103.9, 103.0, 102.4, 101.8, 101.5, 101.2],
  [103.9, 104.4, 104.0, 104.8, 104.5, 105.0], [103.9, 104.8, 105.9, 106.5, 107.3, 107.9],
  [103.9, 103.6, 104.3, 103.9, 104.2, 103.8], [103.9, 102.9, 102.1, 101.4, 101.0, 100.9],
  [103.9, 104.3, 105.1, 104.7, 105.8, 106.6], [103.9, 104.0, 103.5, 104.4, 105.2, 104.9],
];
const STOP = 101.5;
const TARGET = 107;

export const Swing: React.FC = () => {
  const frame = useCurrentFrame();
  const bars = interpolate(frame, [14, 70], [0, CANDLES.length], { ...clamp, easing: ease });
  const spike = useIn(66, 14);
  const fan = interpolate(frame, [92, 150], [0, 1], { ...clamp, easing: ease });
  const odds = useIn(146, 16);
  const fanX = (day: number) => cx(CANDLES.length - 1) + day * 44;
  return (
    <Stage>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 110px", gap: 70 }}>
        <div style={{ width: 690 }}>
          <Kicker>The swing desk</Kicker>
          <Headline size={80}>Volume confirms. Up to five days.</Headline>
          <Sub start={18}>A separate ₹1 lakh book buys breakouts on at least twice normal volume, then replays 2,000 possible futures before entering.</Sub>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginTop: 36, opacity: odds }}>
            <Pill tone="green" size={30}>Target first 48%</Pill>
            <Pill tone="red" size={30}>Stop first 29%</Pill>
            <Pill tone="ink" size={30}>Time exit 23%</Pill>
            <Pill tone="purple" size={30}>Expected +₹410 after charges</Pill>
          </div>
        </div>
        <Card style={{ padding: 30 }}>
          <svg width={880} height={H}>
            <line x1={30} x2={790} y1={y(TARGET)} y2={y(TARGET)} stroke={L.green} strokeWidth={3} strokeDasharray="10 9" opacity={fan} />
            <text x={872} y={y(TARGET) + 8} textAnchor="end" fontSize={24} fontWeight={700} fill={L.green} opacity={fan}>Target</text>
            <line x1={30} x2={790} y1={y(STOP)} y2={y(STOP)} stroke={L.red} strokeWidth={3} strokeDasharray="10 9" opacity={fan} />
            <text x={872} y={y(STOP) + 8} textAnchor="end" fontSize={24} fontWeight={700} fill={L.red} opacity={fan}>Stop</text>
            {CANDLES.map(([open, top, bottom, close], index) => {
              const shown = Math.min(1, Math.max(0, bars - index));
              const up = close >= open;
              const tone = index === CANDLES.length - 1 ? L.purple : up ? L.green : L.red;
              const v = VOLUME[index];
              const big = index === CANDLES.length - 1;
              return (
                <g key={index} opacity={shown}>
                  <line x1={cx(index)} x2={cx(index)} y1={y(top)} y2={y(bottom)} stroke={tone} strokeWidth={3} />
                  <rect x={cx(index) - 12} width={24} y={y(Math.max(open, close))} height={Math.max(4, Math.abs(y(open) - y(close)))} rx={4} fill={tone} />
                  <rect
                    x={cx(index) - 14}
                    width={28}
                    y={H - 10 - v * (big ? 0.5 + spike * 0.5 : 1) * 1.1}
                    height={v * (big ? 0.5 + spike * 0.5 : 1) * 1.1}
                    rx={4}
                    fill={big ? L.purple : "#d8d2ec"}
                  />
                </g>
              );
            })}
            <text x={cx(CANDLES.length - 1) - 24} y={H - 120} textAnchor="end" fontSize={24} fontWeight={700} fill={L.purple} opacity={spike}>
              2.3× volume
            </text>
            {PATHS.map((path, index) => {
              const end = path[path.length - 1];
              const tone = end >= TARGET ? L.green : end <= STOP ? L.red : L.muted;
              const count = Math.max(1, Math.round(fan * (path.length - 1)));
              const points = path.slice(0, count + 1).map((price, day) => `${fanX(day)},${y(price)}`).join(" ");
              return <polyline key={index} points={points} fill="none" stroke={tone} strokeWidth={3} opacity={0.75 * Math.min(1, fan * 3)} strokeLinecap="round" />;
            })}
            <text x={fanX(2.5)} y={y(108.6) + 6} textAnchor="middle" fontSize={24} fontWeight={700} fill={L.ink} opacity={fan}>
              Replayed futures
            </text>
          </svg>
        </Card>
      </AbsoluteFill>
    </Stage>
  );
};
