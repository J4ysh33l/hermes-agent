import React from "react";
import {Arrive, usePop} from "../motion";
import {useTheme} from "../theme";
import type {QuoteScene} from "../types";

// A big quotation mark drops in, the quote rises line by line, the author slides in under a rule.
export const Quote: React.FC<{scene: QuoteScene; frames: number}> = ({scene}) => {
  const theme = useTheme();
  const rule = usePop(14);
  const size = scene.text.length > 120 ? 58 : scene.text.length > 70 ? 68 : 80;
  return (
    <div style={{display: "flex", flexDirection: "column", gap: 30}}>
      <Arrive enter="drop" style={{fontFamily: "Georgia, serif", fontSize: 260, lineHeight: 0.6, color: theme.accent,
        height: 130}}>“</Arrive>
      <Arrive delay={4} enter="rise" style={{fontFamily: theme.sans, fontWeight: 800, fontSize: size, lineHeight: 1.2,
        color: theme.text}}>{scene.text}</Arrive>
      {scene.author ? (
        <>
          <div style={{height: 6, width: 160 * rule, background: theme.accent, borderRadius: 3}} />
          <Arrive delay={16} enter="slide" style={{fontFamily: theme.sans, fontWeight: 700, fontSize: 46,
            color: theme.muted}}>— {scene.author}</Arrive>
        </>
      ) : null}
    </div>
  );
};
