import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { color, font } from "../theme";

export const L = {
  ...color,
  night: "#16142a",
  nightSoft: "#232040",
  amber: "#c9862b",
  amberSoft: "#fbf1df",
  greenSoft: "#e3f2ee",
  redSoft: "#f7e6e8",
};

export const ease = Easing.bezier(0.16, 1, 0.3, 1);
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** 0 → 1 over [start, start + length] frames with a soft ease-out. */
export const useIn = (start: number, length = 18) => {
  const frame = useCurrentFrame();
  return interpolate(frame, [start, start + length], [0, 1], { ...clamp, easing: ease });
};

export const usePop = (start: number) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - start, fps, config: { damping: 13, stiffness: 140 } });
};

/** The light stage every scene sits on: lavender floor glow and a dotted grid. */
export const Stage: React.FC<{ children: React.ReactNode; dark?: boolean }> = ({
  children,
  dark,
}) => (
  <AbsoluteFill
    style={{
      backgroundColor: dark ? L.night : L.bg,
      backgroundImage: dark
        ? `radial-gradient(ellipse 60% 50% at 50% 55%, #3b2f7a 0%, transparent 70%), radial-gradient(#ffffff14 1.4px, transparent 1.4px)`
        : `radial-gradient(ellipse 70% 55% at 50% 100%, ${L.lavender} 0%, transparent 70%), radial-gradient(#c2b8d855 1.4px, transparent 1.4px)`,
      backgroundSize: "100% 100%, 34px 34px",
      fontFamily: font,
      color: dark ? "#ffffff" : L.ink,
    }}
  >
    {children}
  </AbsoluteFill>
);

/** A small label above a headline. */
export const Kicker: React.FC<{ children: React.ReactNode; start?: number }> = ({
  children,
  start = 0,
}) => {
  const t = useIn(start, 14);
  return (
    <div
      style={{
        fontSize: 30,
        fontWeight: 650,
        letterSpacing: 4,
        textTransform: "uppercase",
        color: L.purple,
        opacity: t,
        translate: `0px ${(1 - t) * 16}px`,
      }}
    >
      {children}
    </div>
  );
};

export const Headline: React.FC<{
  children: React.ReactNode;
  start?: number;
  size?: number;
  width?: number;
}> = ({ children, start = 4, size = 92, width = 1200 }) => {
  const t = useIn(start, 20);
  return (
    <div
      style={{
        fontSize: size,
        fontWeight: 700,
        letterSpacing: -size * 0.035,
        lineHeight: 1.04,
        maxWidth: width,
        marginTop: 18,
        opacity: t,
        translate: `0px ${(1 - t) * 28}px`,
      }}
    >
      {children}
    </div>
  );
};

export const Sub: React.FC<{ children: React.ReactNode; start?: number; width?: number }> = ({
  children,
  start = 14,
  width = 1100,
}) => {
  const t = useIn(start, 20);
  return (
    <div
      style={{
        fontSize: 44,
        lineHeight: 1.3,
        color: L.muted,
        maxWidth: width,
        marginTop: 28,
        opacity: t,
      }}
    >
      {children}
    </div>
  );
};

/** One of the sixteen desk robots, popping in and gently floating. */
export const Bot: React.FC<{
  name: string;
  size: number;
  start?: number;
  float?: boolean;
  style?: React.CSSProperties;
}> = ({ name, size, start = 0, float = true, style }) => {
  const frame = useCurrentFrame();
  const pop = usePop(start);
  const bob = float ? Math.sin((frame - start) / 11) * size * 0.025 : 0;
  return (
    <Img
      src={staticFile(`mascots/${name}.svg`)}
      style={{
        width: size,
        height: size,
        scale: String(Math.max(0, pop)),
        translate: `0px ${bob}px`,
        ...style,
      }}
    />
  );
};

export const Pill: React.FC<{
  children: React.ReactNode;
  tone?: "purple" | "green" | "red" | "amber" | "ink";
  size?: number;
  style?: React.CSSProperties;
}> = ({ children, tone = "purple", size = 30, style }) => {
  const tones = {
    purple: [L.lavender, L.purple],
    green: [L.greenSoft, L.green],
    red: [L.redSoft, L.red],
    amber: [L.amberSoft, L.amber],
    ink: ["#ececf3", L.ink],
  } as const;
  const [bg, fg] = tones[tone];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 10,
        padding: `${size * 0.28}px ${size * 0.7}px`,
        borderRadius: 999,
        background: bg,
        color: fg,
        fontSize: size,
        fontWeight: 650,
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {children}
    </span>
  );
};

export const Card: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({
  children,
  style,
}) => (
  <div
    style={{
      background: L.paper,
      border: `2px solid ${L.line}`,
      borderRadius: 28,
      boxShadow: "0 24px 60px -30px rgba(60, 40, 120, 0.35)",
      padding: 36,
      ...style,
    }}
  >
    {children}
  </div>
);

export const Logo: React.FC<{ size?: number; dark?: boolean }> = ({ size = 64, dark }) => (
  <div style={{ display: "flex", alignItems: "center", gap: size * 0.32 }}>
    <span
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.28,
        background: L.purple,
        display: "grid",
        placeItems: "center",
      }}
    >
      <svg viewBox="0 0 24 24" width={size * 0.56} height={size * 0.56} fill="none"
        stroke="white" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 17l5-6 4 4 7-9" />
        <path d="M15 6h5v5" />
      </svg>
    </span>
    <span
      style={{
        fontSize: size * 0.62,
        fontWeight: 700,
        letterSpacing: -size * 0.02,
        color: dark ? "white" : L.ink,
      }}
    >
      India Trade Lab
    </span>
  </div>
);
