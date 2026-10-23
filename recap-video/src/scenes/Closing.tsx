import React from "react";
import {
  AbsoluteFill,
  Interactive,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { Frame } from "../Frame";
import { RecapProps, isSynthetic } from "../data";
import { color } from "../theme";

export const Closing: React.FC<RecapProps> = (data) => {
  const frame = useCurrentFrame();
  return (
    <Frame data={data}>
      <AbsoluteFill
        style={{ justifyContent: "center", paddingLeft: 96, paddingRight: 96 }}
      >
        <Interactive.Div
          name="Statement"
          style={{
            fontSize: 110,
            fontWeight: 650,
            letterSpacing: -4,
            lineHeight: 1.05,
            maxWidth: 1500,
            opacity: interpolate(frame, [4, 24], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          Paper only. No real orders were placed.
        </Interactive.Div>
        <Interactive.Div
          name="Caveat"
          style={{
            marginTop: 40,
            fontSize: 46,
            color: color.muted,
            maxWidth: 1450,
            opacity: interpolate(frame, [20, 40], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          {isSynthetic(data)
            ? "Built from synthetic candles to test the software. It says nothing about future returns."
            : "Assumed fills under explicit cost settings. A recorded session is not a return guarantee."}
        </Interactive.Div>
      </AbsoluteFill>
    </Frame>
  );
};
