import React from "react";
import {Arrive} from "../motion";
import {useTheme} from "../theme";
import type {TitleScene} from "../types";

// Big punch line, words landing one after another; the last word in the accent; a small tag above.
export const Title: React.FC<{scene: TitleScene; frames: number}> = ({scene}) => {
  const theme = useTheme();
  const words = scene.text.split(/\s+/).filter(Boolean);
  const size = words.join(" ").length > 40 ? 96 : 124;
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 36}}>
      {scene.kicker ? (
        <Arrive style={{fontFamily: theme.monoFamily, fontSize: 40, color: theme.bg, background: theme.accent,
          padding: "10px 22px", borderRadius: 10}}>
          {scene.kicker}
        </Arrive>
      ) : null}
      <div style={{display: "flex", flexWrap: "wrap", fontFamily: theme.sans, fontWeight: 900, fontSize: size,
        lineHeight: 1.05, color: theme.text}}>
        {words.map((word, n) => (
          <Arrive key={n} delay={3 + n * 3} style={{marginRight: 26,
            color: n === words.length - 1 ? theme.accent : theme.text}}>
            {word}
          </Arrive>
        ))}
      </div>
    </div>
  );
};
