import React from "react";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { Cta } from "./Cta";
import { Desk } from "./Desk";
import { Hook } from "./Hook";
import { Judge } from "./Judge";
import { Learn } from "./Learn";
import { Product } from "./Product";
import { Route } from "./Route";
import { Tournament } from "./Tournament";
import { Trade } from "./Trade";

// Scene lengths in frames at 30 fps. Each fade overlaps the next scene by FADE frames.
export const LAUNCH_SCENES = {
  hook: 135,
  desk: 180,
  judge: 180,
  tournament: 180,
  trade: 180,
  learn: 195,
  route: 165,
  product: 240,
  cta: 165,
};
export const FADE = 12;
export const LAUNCH_TOTAL =
  Object.values(LAUNCH_SCENES).reduce((sum, value) => sum + value, 0) -
  FADE * (Object.keys(LAUNCH_SCENES).length - 1);

const timing = linearTiming({ durationInFrames: FADE });
const scenes: [string, number, React.FC][] = [
  ["Hook", LAUNCH_SCENES.hook, Hook],
  ["Desk", LAUNCH_SCENES.desk, Desk],
  ["Judge", LAUNCH_SCENES.judge, Judge],
  ["Tournament", LAUNCH_SCENES.tournament, Tournament],
  ["Trade", LAUNCH_SCENES.trade, Trade],
  ["Learn", LAUNCH_SCENES.learn, Learn],
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
