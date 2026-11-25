// One graphic laid over your own footage (orchestrator/edit/render.py): rendered alone, on a transparent
// 1080×1920 frame, for exactly its time on screen, then composited by ffmpeg. Cards sit in the lower third
// (captions step aside while one shows), the title at the top, cutaways cover the whole frame.
import "@fontsource/manrope/700.css";
import "@fontsource/manrope/800.css";
import "@fontsource/newsreader/500.css";
import "@fontsource/newsreader/600.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/800.css";
import "@fontsource/inter-tight/500.css";
import "@fontsource/inter-tight/500-italic.css";
import "@fontsource/inter-tight/600.css";
import "@fontsource/inter-tight/600-italic.css";
import "@fontsource/inter-tight/700.css";
import "@fontsource/montserrat/700.css";
import "@fontsource/anton/400.css";
import "@fontsource/poppins/700.css";
import React from "react";
import {AbsoluteFill, Img, interpolate, OffthreadVideo, spring, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

export const FAMILIES: Record<string, string> = {
  manrope: "Manrope, sans-serif",
  inter: "Inter, sans-serif",
  intertight: "'Inter Tight', Inter, sans-serif",
  montserrat: "Montserrat, sans-serif",
  anton: "Anton, sans-serif",
  newsreader: "Newsreader, Georgia, serif",
  poppins: "Poppins, sans-serif",
};

export type EditLook = {
  font: string;
  serif: string;
  ink: string;
  paper: string;
  accent: string;
  alert: string;
  good: string;
  box_bg: string;
  box_fg: string;
  figure: string; // the number in a stat box ("none" = box_fg)
  radius: number;
  title: {kind: "card" | "pill" | "none"; font: string; bg: string; fg: string; size: number; y: number; subtitle: boolean;
    weight: number; accent: string};
};

export type EditItem = {
  kind: string;
  text?: string;
  sub?: string;
  source?: string;
  by?: string;
  caption?: string;
  items?: string[];
  beats?: number[]; // frame each list item arrives on
  n?: number;
  emoji?: string;
  src?: string; // a file next to props.json (public dir)
  video?: boolean;
  side?: "left" | "right"; // pop
};

export type GraphicProps = {
  look: EditLook;
  item: EditItem;
  frames: number;
};

const OUT = 6; // frames the exit takes
const CARD_TOP = 1240; // the lower third, under the face and clear of the app's buttons (below ~1560)

const useArrive = (delay = 0) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const p = spring({frame: frame - delay, fps, config: {damping: 16, stiffness: 190, mass: 0.7}});
  const out = interpolate(frame, [durationInFrames - OUT, durationInFrames], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return {opacity: Math.min(p * 1.4, 1) * out, transform: `translateY(${(1 - p) * 26}px) scale(${0.94 + 0.06 * p})`};
};

const Card: React.FC<{children: React.ReactNode; top?: number; style?: React.CSSProperties}> = ({children, top = CARD_TOP, style}) => {
  const arrive = useArrive();
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", top, left: 0, right: 0, display: "flex", justifyContent: "center"}}>
        <div style={{maxWidth: 940, ...arrive, ...style}}>{children}</div>
      </div>
    </AbsoluteFill>
  );
};

const shadow = "0 18px 50px rgba(0,0,0,0.35)";

// "Care without *the chaos*": starred words in the style's accent colour, italic (title.accent; none = plain).
const marked = (text: string, accent: string) =>
  text.split(/(\*[^*]+\*)/).map((part, n) => part.startsWith("*") && part.endsWith("*") && part.length > 2
    ? (accent === "none" ? part.slice(1, -1) : <span key={n} style={{color: accent, fontStyle: "italic"}}>{part.slice(1, -1)}</span>)
    : part);

const Title: React.FC<GraphicProps> = ({look, item}) => {
  const t = look.title;
  const pill = t.kind === "pill";
  return (
    <Card top={Math.round(t.y * 1920)}>
      <div style={{background: t.bg, color: t.fg, fontFamily: FAMILIES[t.font], fontWeight: t.weight,
        fontSize: t.size, lineHeight: 1.12, textAlign: "center", padding: pill ? "16px 34px" : "18px 34px 22px",
        borderRadius: pill ? 22 : 4, boxShadow: shadow, letterSpacing: t.weight < 700 ? -1.2 : -0.3}}>
        {marked(item.text ?? "", t.accent)}
      </div>
      {t.subtitle && item.sub ? (
        <div style={{margin: "10px auto 0", width: "fit-content", background: "rgba(255,255,255,0.92)", color: "#222",
          fontFamily: FAMILIES[look.font], fontWeight: 700, fontSize: 28, padding: "6px 14px", borderRadius: 4}}>{item.sub}</div>
      ) : null}
    </Card>
  );
};

const Stat: React.FC<GraphicProps> = ({look, item}) => (
  <Card>
    <div style={{background: look.box_bg + "EB", color: look.box_fg, fontFamily: FAMILIES[look.font], borderRadius: look.radius,
      padding: "22px 34px", textAlign: "center", boxShadow: shadow}}>
      <div style={{fontWeight: 800, fontSize: 84, lineHeight: 1.05, letterSpacing: -1,
        color: look.figure === "none" ? look.box_fg : look.figure}}>{item.text}</div>
      {item.sub ? <div style={{fontWeight: 700, fontSize: 34, marginTop: 8, opacity: 0.85}}>{item.sub}</div> : null}
    </div>
  </Card>
);

const Headline: React.FC<GraphicProps> = ({look, item}) => (
  <Card style={{rotate: "-1deg"}}>
    <div style={{background: "#f6f2ea", color: "#141210", padding: "26px 34px 32px", boxShadow: shadow, width: 860}}>
      {item.source ? (
        <div style={{fontFamily: FAMILIES[look.font], fontWeight: 800, fontSize: 24, letterSpacing: 3, textTransform: "uppercase",
          borderBottom: "2px solid #141210", paddingBottom: 10, marginBottom: 16}}>{item.source}</div>
      ) : null}
      <div style={{fontFamily: FAMILIES[look.serif], fontWeight: 600, fontSize: (item.text ?? "").length > 60 ? 44 : 52, lineHeight: 1.15}}>
        {item.text}
      </div>
    </div>
  </Card>
);

const List: React.FC<GraphicProps> = ({look, item}) => {
  const frame = useCurrentFrame();
  const items = item.items ?? [];
  return (
    <Card top={CARD_TOP - 60}>
      <div style={{background: look.box_bg + "EB", color: look.box_fg, fontFamily: FAMILIES[look.font], borderRadius: look.radius,
        padding: "24px 34px", boxShadow: shadow, minWidth: 620}}>
        {items.map((text, n) => {
          const at = item.beats?.[n] ?? n * 8;
          const p = spring({frame: frame - at, fps: 30, config: {damping: 18, stiffness: 200}});
          return (
            <div key={n} style={{display: "flex", gap: 18, alignItems: "baseline", fontWeight: 800, fontSize: 44, lineHeight: 1.35,
              opacity: p, transform: `translateX(${(1 - p) * -20}px)`}}>
              <span style={{color: look.accent}}>{n + 1}</span><span>{text}</span>
            </div>
          );
        })}
      </div>
    </Card>
  );
};

const Chapter: React.FC<GraphicProps> = ({look, item}) => (
  <Card top={CARD_TOP - 40}>
    <div style={{display: "flex", alignItems: "center", gap: 22, background: look.box_bg + "D1", color: "#fff",
      border: "1.5px solid rgba(255,255,255,0.35)", borderRadius: 18, padding: "18px 30px", fontFamily: FAMILIES[look.font],
      boxShadow: shadow}}>
      <span style={{color: look.accent, fontWeight: 800, fontSize: 54}}>{String(item.n ?? 1).padStart(2, "0")}</span>
      <span style={{fontWeight: 800, fontSize: 46}}>{item.text}</span>
    </div>
  </Card>
);

const LowerThird: React.FC<GraphicProps> = ({look, item}) => {
  const arrive = useArrive();
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", left: 70, top: 1380, ...arrive, fontFamily: FAMILIES[look.font]}}>
        <div style={{background: look.paper, color: look.ink, fontWeight: 800, fontSize: 44, padding: "8px 18px", width: "fit-content"}}>{item.text}</div>
        {item.sub ? <div style={{background: look.accent, color: look.ink, fontWeight: 700, fontSize: 30, padding: "6px 18px",
          width: "fit-content"}}>{item.sub}</div> : null}
      </div>
    </AbsoluteFill>
  );
};

const Emoji: React.FC<GraphicProps> = ({item}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const p = spring({frame, fps: 30, config: {damping: 9, stiffness: 220}});
  const out = interpolate(frame, [durationInFrames - OUT, durationInFrames], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", left: 760, top: 520, fontSize: 170, transform: `scale(${p}) rotate(${(1 - p) * -25}deg)`,
        opacity: out}}>{item.emoji}</div>
    </AbsoluteFill>
  );
};

const Quote: React.FC<GraphicProps> = ({look, item}) => (
  <Card top={CARD_TOP - 40}>
    <div style={{background: look.paper, color: look.ink, padding: "28px 36px", boxShadow: shadow, width: 860, borderRadius: 4}}>
      <div style={{fontFamily: FAMILIES[look.serif], fontStyle: "italic", fontWeight: 500, fontSize: 44, lineHeight: 1.25}}>“{item.text}”</div>
      {item.by ? <div style={{fontFamily: FAMILIES[look.font], fontWeight: 800, fontSize: 28, marginTop: 14}}>— {item.by}</div> : null}
    </div>
  </Card>
);

const Picture: React.FC<GraphicProps> = ({look, item}) => (
  <Card top={980}>
    <div style={{background: "#fff", padding: 10, borderRadius: 18, boxShadow: shadow, width: 880}}>
      <Img src={staticFile(item.src ?? "")} style={{width: "100%", maxHeight: 640, objectFit: "contain", borderRadius: 10, display: "block"}} />
      {item.caption ? <div style={{fontFamily: FAMILIES[look.font], fontWeight: 700, fontSize: 30, color: "#222", padding: "10px 8px 4px"}}>{item.caption}</div> : null}
    </div>
  </Card>
);

const Cutaway: React.FC<GraphicProps> = ({item, frames}) => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, frames], [1, 1.08]);
  const fade = interpolate(frame, [0, 4, frames - 4, frames], [0, 1, 1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const media: React.CSSProperties = {width: "100%", height: "100%", objectFit: "cover", transform: `scale(${scale})`};
  return (
    <AbsoluteFill style={{opacity: fade, background: "#000"}}>
      {item.video ? <OffthreadVideo src={staticFile(item.src ?? "")} muted style={media} /> : <Img src={staticFile(item.src ?? "")} style={media} />}
    </AbsoluteFill>
  );
};

export const SEAM = 960; // split screen: the picture above, your face (moved down by ffmpeg) below

// The picture fills the top half and slides in from the top; a thin accent line marks the seam.
const Split: React.FC<GraphicProps> = ({look, item, frames}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({frame, fps, config: {damping: 20, stiffness: 220}});
  const out = interpolate(frame, [frames - OUT, frames], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const y = (1 - p + out) * -SEAM;
  const scale = interpolate(frame, [0, frames], [1, 1.06]);
  const media: React.CSSProperties = {width: "100%", height: "100%", objectFit: "cover", transform: `scale(${scale})`};
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", left: 0, top: 0, width: 1080, height: SEAM, overflow: "hidden", transform: `translateY(${y}px)`,
        background: "#000"}}>
        {item.video ? <OffthreadVideo src={staticFile(item.src ?? "")} muted style={media} /> : <Img src={staticFile(item.src ?? "")} style={media} />}
        <div style={{position: "absolute", left: 0, right: 0, bottom: 0, height: 6, background: look.accent}} />
      </div>
    </AbsoluteFill>
  );
};

// A 1–3 word chip that pops in beside the face on the word it names (side: left | right, set by render.py).
const Pop: React.FC<GraphicProps> = ({look, item, frames}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({frame, fps, config: {damping: 9, stiffness: 260, mass: 0.6}});
  const out = interpolate(frame, [frames - 5, frames], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const left = item.side !== "right";
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", top: 660, [left ? "left" : "right"]: 56, opacity: Math.min(1, p * 2) * out,
        transform: `scale(${(0.4 + 0.6 * p) * (0.85 + 0.15 * out)}) rotate(${(left ? -1 : 1) * (3 + (1 - p) * 8)}deg)`,
        transformOrigin: left ? "left center" : "right center",
        background: look.paper, color: look.ink, fontFamily: FAMILIES[look.font], fontWeight: 700, fontSize: 54,
        padding: "14px 26px", borderRadius: look.radius, boxShadow: shadow,
        [left ? "borderLeft" : "borderRight"]: `10px solid ${look.accent}`, maxWidth: 560, lineHeight: 1.1}}>
        {item.text}
      </div>
    </AbsoluteFill>
  );
};

const KINDS: Record<string, React.FC<GraphicProps>> = {
  title: Title, stat: Stat, headline: Headline, list: List, chapter: Chapter, lower_third: LowerThird, emoji: Emoji,
  quote: Quote, image: Picture, screenshot: Picture, cutaway: Cutaway, split: Split, pop: Pop,
};

export const Graphic: React.FC<GraphicProps> = (props) => {
  const Kind = KINDS[props.item.kind];
  return <AbsoluteFill style={{backgroundColor: "transparent"}}>{Kind ? <Kind {...props} /> : null}</AbsoluteFill>;
};
