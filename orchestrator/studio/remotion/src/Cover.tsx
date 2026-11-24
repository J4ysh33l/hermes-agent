import React from "react";
import {AbsoluteFill, useVideoConfig} from "remotion";
import {Emoji} from "./Emoji";
import {SceneFrame} from "./motion";
import {BACKGROUNDS, SCENES} from "./Short";
import {FONTS, ProfileProvider, SAFE, useProfile, useTheme} from "./theme";
import type {CoverProps} from "./types";

// A cover (thumbnail): one scene of the video, fully arrived, under 2-4 huge words in the caption font,
// the last word in the accent. Rendered as a still from the same scene code, so it always matches the video.
const Body: React.FC<CoverProps> = ({scene, words}) => {
  const theme = useTheme();
  const {captions} = useProfile();
  const {durationInFrames} = useVideoConfig();
  const Background = BACKGROUNDS[theme.background];
  const {view: View, fullBleed} = SCENES[scene.type];
  const list = words.split(/\s+/).filter(Boolean);
  const size = list.join(" ").length > 18 ? 150 : 180;
  return (
    <AbsoluteFill style={{background: theme.bg}}>
      <Background />
      <AbsoluteFill style={{transform: "translateY(330px)"}}>
        {/* frames past the still's frame: the scene has arrived and has not started leaving */}
        <SceneFrame frames={durationInFrames + 60} enter={scene.enter || undefined} fullBleed={fullBleed}>
          <View scene={scene as never} frames={durationInFrames} />
        </SceneFrame>
      </AbsoluteFill>
      <AbsoluteFill style={{justifyContent: "flex-start", alignItems: "center", paddingTop: SAFE.top - 60,
        paddingLeft: SAFE.side - 30, paddingRight: SAFE.side - 30}}>
        <div style={{display: "flex", flexWrap: "wrap", justifyContent: "center", gap: `0 ${size * 0.3}px`}}>
          {list.map((word, n) => (
            <span key={n} style={{fontFamily: FONTS[captions.font], fontWeight: 900, fontSize: size, lineHeight: 1.02,
              textTransform: captions.upper ? "uppercase" : "none",
              color: n === list.length - 1 ? theme.accent : captions.fill,
              WebkitTextStroke: `${captions.stroke + 4}px ${captions.outline}`, paintOrder: "stroke fill",
              textShadow: `0 14px 40px ${captions.outline}aa`}}>
              {word}
            </span>
          ))}
        </div>
      </AbsoluteFill>
      {scene.emoji ? (
        // a second after its pop: landed, sparks gone, not yet faded; moved down beside the scene, off the words
        <AbsoluteFill style={{transform: "translateY(520px)"}}><Emoji char={scene.emoji} at={durationInFrames - 30} /></AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

export const Cover: React.FC<CoverProps> = (props) => (
  <ProfileProvider profile={props.profile}>
    <Body {...props} />
  </ProfileProvider>
);
