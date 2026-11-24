import React from "react";
import {Arrive} from "../motion";
import {useTheme} from "../theme";
import type {PostScene} from "../types";

// A generic social post card (no platform's branding): avatar initial, name, handle, text, likes.
export const Post: React.FC<{scene: PostScene; frames: number}> = ({scene}) => {
  const theme = useTheme();
  return (
    <Arrive enter="pop" style={{background: "#ffffff", color: "#0f1419", borderRadius: 34, padding: "44px 46px",
      boxShadow: "0 40px 120px rgba(0,0,0,0.45)", fontFamily: theme.sans}}>
      <div style={{display: "flex", alignItems: "center", gap: 24, marginBottom: 28}}>
        <div style={{width: 96, height: 96, borderRadius: 48, background: theme.accent, color: "#0f1419",
          display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 900, fontSize: 50}}>
          {scene.name.slice(0, 1).toUpperCase()}
        </div>
        <div>
          <div style={{fontWeight: 900, fontSize: 46}}>{scene.name}</div>
          <div style={{fontWeight: 600, fontSize: 36, color: "#536471"}}>{scene.handle}</div>
        </div>
      </div>
      <Arrive delay={6} enter="fade" style={{fontWeight: 600, fontSize: scene.text.length > 140 ? 44 : 54,
        lineHeight: 1.3}}>{scene.text}</Arrive>
      {scene.likes ? (
        <Arrive delay={14} enter="pop" style={{marginTop: 30, fontWeight: 800, fontSize: 38, color: "#f91880"}}>
          ♥ {scene.likes}
        </Arrive>
      ) : null}
    </Arrive>
  );
};
