import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {usePop} from "../motion";
import {theme} from "../theme";
import type {CodeScene} from "../types";

const KEYWORDS = /\b(const|let|var|function|return|if|else|for|while|import|from|export|def|class|async|await|new|true|false|None|null)\b/;
const TOKENS = /(\/\/.*$|#.*$|"[^"]*"|'[^']*'|`[^`]*`|\b\d+(?:\.\d+)?\b|\b\w+\b|\s+|.)/gm;

const colour = (token: string) => {
  if (/^(\/\/|#)/.test(token)) return theme.muted;
  if (/^["'`]/.test(token)) return theme.good;
  if (/^\d/.test(token)) return theme.bad;
  if (KEYWORDS.test(token) && token.match(KEYWORDS)?.[0] === token) return theme.cool;
  return theme.text;
};

// Editor window; the code types itself out over the first 60% of the scene, with a blinking cursor.
export const Code: React.FC<{scene: CodeScene; frames: number}> = ({scene, frames}) => {
  const frame = useCurrentFrame();
  const win = usePop(0);
  const shown = Math.floor(interpolate(frame, [6, Math.max(7, frames * 0.6)], [0, scene.code.length], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  }));
  const text = scene.code.slice(0, shown);
  const size = scene.code.split("\n").some((l) => l.length > 30) ? 34 : 42;
  return (
    <div
      style={{
        background: theme.panel, borderRadius: 28, overflow: "hidden", boxShadow: "0 40px 120px rgba(0,0,0,0.55)",
        transform: `translateY(${interpolate(win, [0, 1], [80, 0])}px)`,
      }}
    >
      <div style={{display: "flex", alignItems: "center", gap: 14, padding: "22px 28px", background: "#0f1422"}}>
        {[theme.bad, theme.accent, theme.good].map((c) => (
          <div key={c} style={{width: 22, height: 22, borderRadius: 11, background: c}} />
        ))}
        <div style={{fontFamily: theme.mono, fontSize: 30, color: theme.muted, marginLeft: 18}}>{scene.title}</div>
      </div>
      <pre style={{margin: 0, padding: "34px 36px", fontFamily: theme.mono, fontSize: size, lineHeight: 1.45,
        whiteSpace: "pre-wrap", wordBreak: "break-word", minHeight: 300}}>
        {(text.match(TOKENS) ?? []).map((t, n) => <span key={n} style={{color: colour(t)}}>{t}</span>)}
        <span style={{color: theme.accent, opacity: Math.floor(frame / 8) % 2 ? 0 : 1}}>▌</span>
      </pre>
    </div>
  );
};
