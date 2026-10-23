import React from "react";
import { Composition, Folder } from "remotion";
import sample from "../sample/synthetic-recap.json";
import { RecapProps } from "./data";
import { Recap } from "./Recap";
import { Closing } from "./scenes/Closing";
import { Opening } from "./scenes/Opening";
import { Pipeline } from "./scenes/Pipeline";
import { Result } from "./scenes/Result";
import { Tape } from "./scenes/Tape";
import { FPS, SCENES, TOTAL } from "./theme";

const defaults = sample as RecapProps;
const size = { width: 1920, height: 1080, fps: FPS };

export const RemotionRoot: React.FC = () => (
  <>
    <Folder name="Recap-Scenes">
      <Composition
        id="Opening"
        component={Opening}
        durationInFrames={SCENES.opening}
        defaultProps={defaults}
        {...size}
      />
      <Composition
        id="Tape"
        component={Tape}
        durationInFrames={SCENES.tape}
        defaultProps={defaults}
        {...size}
      />
      <Composition
        id="Pipeline"
        component={Pipeline}
        durationInFrames={SCENES.pipeline}
        defaultProps={defaults}
        {...size}
      />
      <Composition
        id="Result"
        component={Result}
        durationInFrames={SCENES.result}
        defaultProps={defaults}
        {...size}
      />
      <Composition
        id="Closing"
        component={Closing}
        durationInFrames={SCENES.closing}
        defaultProps={defaults}
        {...size}
      />
    </Folder>
    <Composition
      id="Recap"
      component={Recap}
      durationInFrames={TOTAL}
      defaultProps={defaults}
      {...size}
    />
  </>
);
