// The observatory's light purple brand, reused so the recap and dashboard match.
export const color = {
  bg: "#f6f6f9",
  paper: "#ffffff",
  ink: "#252532",
  muted: "#858592",
  line: "#eaeaf0",
  purple: "#7760ce",
  violet: "#9a80cd",
  lavender: "#f0ecfb",
  lilac: "#d9cff3",
  green: "#358977",
  red: "#bb5a65",
};
export const font = `Inter, -apple-system, "Segoe UI", sans-serif`;
export const FPS = 30;
export const SCENES = {
  opening: 90,
  tape: 240,
  pipeline: 180,
  result: 165,
  closing: 105,
};
export const TRANSITION = 15;
export const TOTAL =
  Object.values(SCENES).reduce((sum, value) => sum + value, 0) -
  TRANSITION * (Object.keys(SCENES).length - 1);
