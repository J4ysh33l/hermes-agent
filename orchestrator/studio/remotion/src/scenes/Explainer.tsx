// The explainer scenes of /edit (statement, counter, stack, steps, points, bars, balance, badge) in a faceless
// short: the same components (edit/Scenes.tsx), drawn in the page profile's colours and font on the short's
// own background, each part arriving on the sentence that says it (revealAt over the scene's beats).
import React from "react";
import {revealAt} from "../motion";
import {useTheme} from "../theme";
import type {ExplainerScene} from "../types";
import {EXPLAINERS, light, Look, SceneItem} from "../edit/Scenes";

const FAMILY: Record<string, string> = {inter: "inter", intertight: "intertight", montserrat: "montserrat", anton: "anton", jetbrains: "inter"};

const useLook = (): Look => {
  const theme = useTheme();
  const dark = !light(theme.bg.startsWith("#") ? theme.bg : "#000000");
  return {
    font: FAMILY[theme.font] ?? "inter", serif: FAMILY[theme.font] ?? "inter",
    ink: dark ? theme.bg : theme.text, paper: dark ? theme.text : theme.bg,
    accent: theme.accent, alert: theme.bad, good: theme.good, box_bg: theme.bg, box_fg: theme.text,
    figure: theme.cool, radius: 16,
    title: {kind: "none", font: theme.font, bg: theme.bg, fg: theme.text, size: 60, y: 0.1, subtitle: false, weight: 600, accent: theme.accent},
  };
};

// The scene's fields → the edit's item, every part given the frame it arrives on.
const toItem = (s: ExplainerScene, frames: number): SceneItem => {
  const at = (k: number, count: number) => revealAt(k, count, frames, s.beats);
  const base = {kind: "scene" as const, type: s.type, layout: "full" as const};
  switch (s.type) {
    case "statement": {
      const lines = s.lines.map((l, k) => ({text: l.text, tone: l.tone, at: at(k, s.lines.length)}));
      return {...base, icon: s.icon || undefined, sub: s.sub || undefined, sub_at: at(s.lines.length - 1, s.lines.length) + 12,
        lines: lines.map((l, k) => ({...l, strike_at: s.lines[k].strike ? (lines[k + 1]?.at ?? Math.max(l.at + 20, frames - 30)) : undefined}))};
    }
    case "counter":
      return {...base, number: s.value, count_from: s.count_from, prefix: s.prefix, suffix: s.suffix, label: s.label, sub: s.sub || undefined,
        tone: s.tone, at: 4};
    case "stack":
      return {...base, title: s.title || undefined, tone: s.tone,
        rows: s.rows.map((r, k) => ({text: r.text, icon: r.icon || undefined, mark: r.mark, at: at(k, s.rows.length)}))};
    case "steps":
      return {...base, title: s.title || undefined,
        steps: s.steps.map((st, k) => ({label: st.label, icon: st.icon || undefined, sub: st.sub || undefined, at: at(k, s.steps.length)}))};
    case "points": {
      const items = s.items.map((text, k) => ({text, at: at(k, s.items.length)}));
      return {...base, title: s.title, numbered: s.numbered, items,
        strike_at: s.struck ? Math.max(items[items.length - 1].at + 24, frames - 36) : undefined};
    }
    case "bars":
      return {...base, title: s.title || undefined, bars: s.bars.map((b, k) => ({...b, at: at(k, s.bars.length)}))};
    case "balance":
      return {...base, type: "compare", title: s.title || undefined, left: {text: s.left}, right: {text: s.right}, heavy: s.heavy,
        strike: s.strike === "none" ? undefined : s.strike, strike_at: s.strike === "none" ? undefined : Math.round(frames * 0.6), at: 12};
    case "badge":
      return {...base, icon: s.icon, text: s.text, badge: s.badge || undefined, at: at(0, 1) + 10};
  }
};

export const Explainer: React.FC<{scene: ExplainerScene; frames: number}> = ({scene, frames}) => {
  const look = useLook();
  const item = toItem(scene, frames);
  const View = EXPLAINERS[item.type];
  return View ? <div style={{width: "100%"}}><View look={look} item={item} frames={frames} dark={!light(look.box_bg)} /></div> : null;
};
