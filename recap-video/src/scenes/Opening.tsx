import React from "react";
import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { Frame } from "../Frame";
import { RecapProps, dateIST, symbolOf } from "../data";
import { color } from "../theme";

export const Opening: React.FC<RecapProps> = (data) => {
  const frame = useCurrentFrame();
  const first = data.prices?.[0]?.at ?? data.calls?.[0]?.at;
  return (
    <Frame data={data}>
      <AbsoluteFill
        style={{ justifyContent: "center", paddingLeft: 96, paddingRight: 96 }}
      >
        <Interactive.Div
          name="Symbol"
          style={{
            fontSize: 150,
            fontWeight: 650,
            letterSpacing: -6,
            lineHeight: 1,
            opacity: interpolate(frame, [4, 26], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            translate: interpolate(frame, [4, 34], ["0px 60px", "0px 0px"], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.16, 1, 0.3, 1),
            }),
          }}
        >
          {symbolOf(data)}
        </Interactive.Div>
        <Interactive.Div
          name="Date"
          style={{
            marginTop: 26,
            fontSize: 64,
            fontWeight: 400,
            color: color.purple,
            letterSpacing: -1.5,
            opacity: interpolate(frame, [16, 38], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            translate: interpolate(frame, [16, 46], ["0px 40px", "0px 0px"], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.16, 1, 0.3, 1),
            }),
          }}
        >
          {first ? dateIST(first) : "Recorded paper session"}
        </Interactive.Div>
        <Interactive.Div
          name="Lede"
          style={{
            marginTop: 44,
            fontSize: 44,
            color: color.muted,
            maxWidth: 1300,
            opacity: interpolate(frame, [30, 52], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          One paper session, from the first candle to the closing bell.
        </Interactive.Div>
      </AbsoluteFill>
    </Frame>
  );
};
