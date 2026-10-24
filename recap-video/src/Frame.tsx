import React from "react";
import { AbsoluteFill } from "remotion";
import { RecapProps, isSynthetic } from "./data";
import { color, font } from "./theme";

// Shared stage for every scene: brand, provenance chip and a quiet dotted floor.
export const Frame: React.FC<{
  data: RecapProps;
  children: React.ReactNode;
}> = ({ data, children }) => (
  <AbsoluteFill
    style={{
      backgroundColor: color.bg,
      backgroundImage: `radial-gradient(ellipse 70% 55% at 50% 100%, ${color.lavender} 0%, transparent 70%), radial-gradient(#c2b8d855 1.4px, transparent 1.4px)`,
      backgroundSize: "100% 100%, 34px 34px",
      fontFamily: font,
      color: color.ink,
    }}
  >
    <div
      style={{
        position: "absolute",
        top: 64,
        left: 96,
        display: "flex",
        alignItems: "center",
        gap: 18,
        fontSize: 30,
        fontWeight: 600,
        letterSpacing: -0.5,
      }}
    >
      <span
        style={{
          width: 52,
          height: 52,
          borderRadius: 15,
          background: color.purple,
          color: "white",
          display: "grid",
          placeItems: "center",
          fontSize: 30,
        }}
      >
        ↗
      </span>
      trade lab
    </div>
    <div
      style={{
        position: "absolute",
        top: 70,
        right: 96,
        padding: "10px 20px",
        borderRadius: 999,
        border: `2px solid ${color.lilac}`,
        background: "white",
        color: color.purple,
        fontSize: 24,
        fontWeight: 600,
      }}
    >
      {isSynthetic(data)
        ? "Synthetic replay, virtual INR"
        : "Paper session, virtual INR"}
    </div>
    {children}
  </AbsoluteFill>
);
