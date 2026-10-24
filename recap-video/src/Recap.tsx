import React from "react";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { RecapProps } from "./data";
import { Closing } from "./scenes/Closing";
import { Opening } from "./scenes/Opening";
import { Pipeline } from "./scenes/Pipeline";
import { Result } from "./scenes/Result";
import { Tape } from "./scenes/Tape";
import { SCENES, TRANSITION } from "./theme";

const timing = linearTiming({ durationInFrames: TRANSITION });

export const Recap: React.FC<RecapProps> = (data) => (
  <TransitionSeries>
    <TransitionSeries.Sequence name="Opening" durationInFrames={SCENES.opening}>
      <Opening {...data} />
    </TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={timing} />
    <TransitionSeries.Sequence name="Tape" durationInFrames={SCENES.tape}>
      <Tape {...data} />
    </TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={timing} />
    <TransitionSeries.Sequence
      name="Pipeline"
      durationInFrames={SCENES.pipeline}
    >
      <Pipeline {...data} />
    </TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={timing} />
    <TransitionSeries.Sequence name="Result" durationInFrames={SCENES.result}>
      <Result {...data} />
    </TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={timing} />
    <TransitionSeries.Sequence name="Closing" durationInFrames={SCENES.closing}>
      <Closing {...data} />
    </TransitionSeries.Sequence>
  </TransitionSeries>
);
