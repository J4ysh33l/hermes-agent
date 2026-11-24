import React from "react";
import {Img, staticFile} from "remotion";
import {Arrive} from "../motion";
import {FONTS} from "../theme";
import type {MemeScene} from "../types";

const CAPTION: React.CSSProperties = {fontFamily: FONTS.anton, fontSize: 92, color: "#fff", textAlign: "center",
  textTransform: "uppercase", lineHeight: 1.05, WebkitTextStroke: "10px #000", paintOrder: "stroke fill"};

// Classic meme card: your own (CC0) image, top and bottom text in heavy outlined caps.
export const Meme: React.FC<{scene: MemeScene; frames: number}> = ({scene}) => {
  const src = /^https?:/.test(scene.src) ? scene.src : staticFile(scene.src);
  return (
    <Arrive enter="pop" style={{position: "relative", borderRadius: 18, overflow: "hidden",
      boxShadow: "0 40px 120px rgba(0,0,0,0.5)", background: "#000"}}>
      <Img src={src} style={{width: "100%", display: "block", maxHeight: 1100, objectFit: "cover"}} />
      {scene.top ? <div style={{...CAPTION, position: "absolute", top: 24, left: 24, right: 24}}>{scene.top}</div> : null}
      {scene.bottom ? (
        <Arrive delay={12} enter="drop" style={{...CAPTION, position: "absolute", bottom: 24, left: 24, right: 24}}>
          {scene.bottom}
        </Arrive>
      ) : null}
    </Arrive>
  );
};
