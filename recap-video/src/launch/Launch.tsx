import React from "react";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { Cta } from "./Cta";
import { DayMap } from "./DayMap";
import { Debate } from "./Debate";
import { Desk } from "./Desk";
import { Evidence } from "./Evidence";
import { Gates } from "./Gates";
import { Hook } from "./Hook";
import { Judge } from "./Judge";
import { Learn } from "./Learn";
import { Product } from "./Product";
import { Proof } from "./Proof";
import { Route } from "./Route";
import { Swing } from "./Swing";
import { Trade } from "./Trade";
import { Watchdog } from "./Watchdog";

// Scene lengths in frames at 30 fps. Each fade overlaps the next scene by FADE frames.
export const LAUNCH_SCENES = {
  hook: 135,
  daymap: 210,
  desk: 165,
  evidence: 195,
  judge: 180,
  debate: 210,
  gates: 210,
  trade: 180,
  swing: 225,
  proof: 195,
  learn: 195,
  watchdog: 195,
  route: 165,
  product: 240,
  cta: 180,
};
export const FADE = 12;
export const LAUNCH_TOTAL =
  Object.values(LAUNCH_SCENES).reduce((sum, value) => sum + value, 0) -
  FADE * (Object.keys(LAUNCH_SCENES).length - 1);

const timing = linearTiming({ durationInFrames: FADE });
const scenes: [string, number, React.FC][] = [
  ["Hook", LAUNCH_SCENES.hook, Hook],
  ["DayMap", LAUNCH_SCENES.daymap, DayMap],
  ["Desk", LAUNCH_SCENES.desk, Desk],
  ["Evidence", LAUNCH_SCENES.evidence, Evidence],
  ["Judge", LAUNCH_SCENES.judge, Judge],
  ["Debate", LAUNCH_SCENES.debate, Debate],
  ["Gates", LAUNCH_SCENES.gates, Gates],
  ["Trade", LAUNCH_SCENES.trade, Trade],
  ["Swing", LAUNCH_SCENES.swing, Swing],
  ["Proof", LAUNCH_SCENES.proof, Proof],
  ["Learn", LAUNCH_SCENES.learn, Learn],
  ["Watchdog", LAUNCH_SCENES.watchdog, Watchdog],
  ["Route", LAUNCH_SCENES.route, Route],
  ["Product", LAUNCH_SCENES.product, Product],
  ["Cta", LAUNCH_SCENES.cta, Cta],
];

export const Launch: React.FC = () => (
  <TransitionSeries>
    {scenes.flatMap(([name, duration, Scene], index) => [
      ...(index ? [<TransitionSeries.Transition key={`${name}-fade`} presentation={fade()} timing={timing} />] : []),
      <TransitionSeries.Sequence key={name} name={name} durationInFrames={duration}>
        <Scene />
      </TransitionSeries.Sequence>,
    ])}
  </TransitionSeries>
);

export const LAUNCH_PARTS = scenes;
