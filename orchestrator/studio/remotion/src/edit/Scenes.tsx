// Explainer scenes for edits of your own footage: the director's main tools besides cutting.
// Each scene fills one of three layouts:
//   panel: the top half (0–960) on the brand colour; ffmpeg moves your face, zoomed, into the bottom half
//   full:  the whole frame (your voice carries on); captions sit near the bottom
//   top:   no background; big type in the space above your head (a hook, a number)
// Elements arrive on the words they belong to: every `at` here is a frame from the scene's start
// (render.py turns the plan's "S4.12" anchors into frames).
import "@fontsource/poppins/600.css";
import "@fontsource/poppins/700.css";
import "@fontsource/poppins/800.css";
import React from "react";
import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import * as L from "lucide-react";
import {EditLook, FAMILIES} from "./Graphic";

export const SEAM = 960;
const W = 760; // content width before the layout's zoom (panel ×1.25, full ×1.3)

// The icons a plan may name (plan.py ICONS lists the same names).
export const ICONS: Record<string, React.FC<L.LucideProps>> = {
  hospital: L.Hospital, stethoscope: L.Stethoscope, pill: L.Pill, syringe: L.Syringe, "heart-pulse": L.HeartPulse,
  activity: L.Activity, ambulance: L.Ambulance, bed: L.Bed, clipboard: L.Clipboard, "clipboard-check": L.ClipboardCheck,
  file: L.FileText, receipt: L.Receipt, wallet: L.Wallet, rupee: L.IndianRupee, "piggy-bank": L.PiggyBank,
  shield: L.Shield, "shield-check": L.ShieldCheck, user: L.User, users: L.Users, calendar: L.Calendar, clock: L.Clock,
  alert: L.AlertTriangle, cross: L.XCircle, check: L.CheckCircle2, "trending-up": L.TrendingUp,
  "trending-down": L.TrendingDown, chart: L.BarChart3, database: L.Database, phone: L.Smartphone, monitor: L.Monitor,
  laptop: L.Laptop, offline: L.WifiOff, languages: L.Languages, training: L.GraduationCap, building: L.Building2,
  home: L.Home, pin: L.MapPin, call: L.Phone, search: L.Search, idea: L.Lightbulb, target: L.Target, zap: L.Zap,
  lock: L.Lock, scale: L.Scale, rocket: L.Rocket, sparkles: L.Sparkles, microscope: L.Microscope, test: L.TestTube,
  scan: L.ScanLine, brain: L.Brain, care: L.HandHeart, cash: L.Banknote, government: L.Landmark, insurance: L.Umbrella,
  timer: L.Timer, hourglass: L.Hourglass, settings: L.Settings, wrench: L.Wrench, chat: L.MessageCircle, mic: L.Mic,
  camera: L.Camera, arrow: L.ArrowRight, ban: L.Ban, hand: L.Hand, eye: L.Eye, heart: L.Heart, baby: L.Baby,
  leaf: L.Leaf, apple: L.Apple, fitness: L.Dumbbell, coins: L.Coins, card: L.CreditCard, "file-x": L.FileX,
  "calendar-x": L.CalendarX, "user-x": L.UserX, sad: L.Frown, happy: L.Smile, "thumbs-up": L.ThumbsUp,
  globe: L.Globe, truck: L.Truck, package: L.Package, printer: L.Printer, chip: L.Cpu, bot: L.Bot, cloud: L.Cloud,
  sync: L.RefreshCw, layers: L.Layers, dashboard: L.LayoutDashboard, checklist: L.ListChecks, siren: L.Siren,
  blood: L.Droplet, fever: L.Thermometer, bandage: L.Bandage, plus: L.Cross,
};

export type Tone = "problem" | "solution" | "neutral";
export type SceneItem = {
  kind: "scene";
  type: string;
  layout: "panel" | "full" | "top";
  text?: string;
  lines?: {text: string; tone?: Tone; strike_at?: number; underline_at?: number; at?: number}[];
  sub?: string;
  sub_at?: number;
  kicker?: string;
  title?: string;
  tone?: Tone;
  icon?: string;
  strike_at?: number;
  underline_at?: number;
  count_from?: number;
  number?: number;
  prefix?: string;
  suffix?: string;
  label?: string;
  at?: number;
  rows?: {text: string; icon?: string; mark?: "cross" | "check" | "none"; at?: number}[];
  steps?: {label: string; sub?: string; icon?: string; at?: number; sub_at?: number}[];
  left?: {text: string};
  right?: {text: string};
  heavy?: "left" | "right";
  strike?: "left" | "right";
  bars?: {label: string; value: string; size: number; tone?: Tone; at?: number}[];
  items?: {text: string; at?: number}[];
  numbered?: boolean;
  badge?: string;
  cta?: string;
  logo?: string; // a file next to props.json
  handle?: string;
};

type Props = {look: EditLook & {handle?: string}; item: SceneItem; frames: number};

const pop = (frame: number, at = 0, fps = 30, soft = false) =>
  spring({frame: frame - at, fps, config: soft ? {damping: 18, stiffness: 140} : {damping: 12, stiffness: 220, mass: 0.6}});

const toneColour = (look: EditLook, tone: Tone | undefined, onDark: boolean) =>
  tone === "problem" ? look.alert : tone === "solution" ? (onDark ? look.accent : look.good) : onDark ? "#FFFFFF" : look.ink;

const Icon: React.FC<{name?: string; size: number; colour: string; stroke?: number}> = ({name, size, colour, stroke = 2}) => {
  const C = name ? ICONS[name] : undefined;
  return C ? <C size={size} color={colour} strokeWidth={stroke} /> : null;
};

// A red line drawn across the text from left to right, from `at` (in frames).
const Strike: React.FC<{at?: number; colour: string; thick?: number}> = ({at, colour, thick = 8}) => {
  const frame = useCurrentFrame();
  if (at === undefined) return null;
  const w = interpolate(frame, [at, at + 8], [0, 104], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return <div style={{position: "absolute", left: "-2%", top: "52%", height: thick, width: `${w}%`, background: colour,
    borderRadius: thick, transform: "rotate(-2deg)"}} />;
};

const Underline: React.FC<{at?: number; colour: string}> = ({at, colour}) => {
  const frame = useCurrentFrame();
  if (at === undefined) return null;
  const w = interpolate(frame, [at, at + 8], [0, 100], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return <div style={{position: "absolute", left: 0, bottom: -6, height: 7, width: `${w}%`, background: colour, borderRadius: 4}} />;
};

const struck = (frame: number, at?: number) => (at !== undefined && frame > at + 6 ? 0.55 : 1);

// ---- layouts ------------------------------------------------------------------------------------------

const Background: React.FC<{look: EditLook; layout: SceneItem["layout"]; frames: number; handle?: string; children: React.ReactNode}> =
  ({look, layout, frames, handle, children}) => {
    const frame = useCurrentFrame();
    const {fps} = useVideoConfig();
    const p = spring({frame, fps, config: {damping: 20, stiffness: 200}});
    const out = interpolate(frame, [frames - 6, frames], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
    if (layout === "top") {
      return <AbsoluteFill style={{opacity: Math.min(1, p * 1.5) * (1 - out)}}>{children}</AbsoluteFill>;
    }
    const height = layout === "panel" ? SEAM : 1920;
    const bg = look.box_bg;
    const shift = layout === "panel" ? (1 - p + out) * -height : 0;
    const fade = layout === "full" ? Math.min(1, p * 1.6) * (1 - out) : 1;
    return (
      <AbsoluteFill>
        <div style={{position: "absolute", left: 0, top: 0, width: 1080, height, overflow: "hidden", opacity: fade,
          transform: `translateY(${shift}px)`, background: `radial-gradient(circle at 85% 8%, ${bg}, ${shade(bg, -0.18)} 70%)`}}>
          <div style={{position: "absolute", right: -160, top: -160, width: 520, height: 520, borderRadius: 520,
            background: "rgba(255,255,255,0.05)"}} />
          <div style={{position: "absolute", left: -220, bottom: -260, width: 640, height: 640, borderRadius: 640,
            background: "rgba(255,255,255,0.04)"}} />
          {handle ? (
            <div style={{position: "absolute", right: 36, bottom: layout === "panel" ? 28 : 360, display: "flex", alignItems: "center",
              gap: 8, color: "rgba(255,255,255,0.75)", fontFamily: FAMILIES.poppins, fontWeight: 600, fontSize: 20}}>
              <Icon name="camera" size={22} colour="rgba(255,255,255,0.75)" />{handle}
            </div>
          ) : null}
          {layout === "panel" ? <div style={{position: "absolute", left: 0, right: 0, bottom: 0, height: 6, background: look.accent}} /> : null}
          <div style={{position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", padding: layout === "full" ? "0 40px 480px" : "0 30px"}}>
            <div style={{zoom: layout === "full" ? 1.3 : 1.25, display: "flex", flexDirection: "column", alignItems: "center"}}>{children}</div>
          </div>
        </div>
      </AbsoluteFill>
    );
  };

const shade = (hex: string, amount: number) => {
  const n = parseInt(hex.slice(1), 16);
  const f = (c: number) => Math.max(0, Math.min(255, Math.round(c * (1 + amount))));
  return `rgb(${f(n >> 16)}, ${f((n >> 8) & 255)}, ${f(n & 255)})`;
};

// ---- the scene types ----------------------------------------------------------------------------------

const Kicker: React.FC<{text?: string; look: EditLook; dark: boolean}> = ({text, look, dark}) =>
  text ? <div style={{fontFamily: FAMILIES.poppins, fontWeight: 700, fontSize: 26, letterSpacing: 5, textTransform: "uppercase",
    color: dark ? look.accent : look.good, marginBottom: 14}}>{text}</div> : null;

const Title: React.FC<{text?: string; look: EditLook; dark: boolean; size?: number}> = ({text, look, dark, size = 64}) =>
  text ? <div style={{fontFamily: FAMILIES[look.font], fontWeight: 700, fontSize: size, lineHeight: 1.08, letterSpacing: -1,
    color: dark ? "#FFFFFF" : look.ink, textAlign: "center", marginBottom: 34}}>{text}</div> : null;

const bigSize = (text: string) => (text.length <= 8 ? 150 : text.length <= 14 ? 112 : text.length <= 24 ? 80 : 60);

const Statement: React.FC<Props & {dark: boolean}> = ({look, item, dark}) => {
  const frame = useCurrentFrame();
  const lines = item.lines ?? [{text: item.text ?? "", tone: item.tone, strike_at: item.strike_at, underline_at: item.underline_at}];
  const top = item.layout === "top";
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
      ...(top ? {position: "absolute", top: 150, left: 40, right: 40} : {})}}>
      <Kicker text={item.kicker} look={look} dark={dark} />
      {item.icon ? <div style={{transform: `scale(${pop(frame, 2)})`, marginBottom: 16}}>
        <Icon name={item.icon} size={110} colour={toneColour(look, item.tone, dark)} /></div> : null}
      {lines.map((line, n) => {
        const p = pop(frame, line.at ?? n * 6);
        const size = top ? Math.min(Math.round(bigSize(line.text) * 1.5), 170) : bigSize(line.text);
        return (
          <div key={n} style={{position: "relative", fontFamily: FAMILIES[look.font], fontWeight: 800, fontSize: size,
            lineHeight: 1.04, letterSpacing: -2, color: toneColour(look, line.tone, dark), opacity: Math.min(1, p * 1.5) * struck(frame, line.strike_at),
            transform: `scale(${0.7 + 0.3 * p})`, textAlign: "center",
            textShadow: top ? "0 4px 24px rgba(255,255,255,0.6)" : "0 6px 30px rgba(0,0,0,0.25)"}}>
            {line.text}
            <Strike at={line.strike_at} colour={look.alert} thick={Math.max(6, size / 14)} />
            <Underline at={line.underline_at} colour={look.alert} />
          </div>
        );
      })}
      {item.sub ? <div style={{fontFamily: FAMILIES.poppins, fontWeight: 600, fontSize: 40, marginTop: 18,
        color: dark ? "rgba(255,255,255,0.85)" : look.ink, opacity: pop(frame, item.sub_at ?? 8), textAlign: "center"}}>{item.sub}</div> : null}
    </div>
  );
};

const Counter: React.FC<Props & {dark: boolean}> = ({look, item, dark}) => {
  const frame = useCurrentFrame();
  const at = item.at ?? 0;
  const from = item.count_from ?? 0;
  const to = item.number ?? 0;
  const k = interpolate(frame, [at, at + 22], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const value = from + (to - from) * (1 - Math.pow(1 - k, 3));
  const digits = Number.isInteger(to) ? 0 : 1;
  const shown = value.toLocaleString("en-IN", {maximumFractionDigits: digits, minimumFractionDigits: digits});
  const colour = toneColour(look, item.tone ?? "problem", dark);
  const top = item.layout === "top";
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "center", ...(top ? {position: "absolute", top: 120, left: 40, right: 40} : {})}}>
      <Kicker text={item.kicker} look={look} dark={dark} />
      <div style={{fontFamily: FAMILIES[look.font], fontWeight: 800, fontSize: top ? 230 : 240, lineHeight: 1, letterSpacing: -6,
        color: colour, transform: `scale(${0.8 + 0.2 * pop(frame, at)})`}}>{item.prefix ?? ""}{shown}{item.suffix ?? ""}</div>
      {item.label ? <div style={{fontFamily: FAMILIES.poppins, fontWeight: 700, fontSize: top ? 46 : 50, marginTop: 8,
        color: dark ? "#FFFFFF" : look.ink, textAlign: "center", opacity: pop(frame, at + 6)}}>{item.label}</div> : null}
      {item.icon ? <div style={{marginTop: 26, transform: `scale(${pop(frame, at + 12)})`}}><Icon name={item.icon} size={84} colour={colour} /></div> : null}
      {item.sub ? <div style={{marginTop: 18, background: look.ink, color: "#FFFFFF", fontFamily: FAMILIES.poppins, fontWeight: 700,
        fontSize: 32, padding: "8px 20px", borderRadius: 8, letterSpacing: 2, textTransform: "uppercase", opacity: pop(frame, at + 14)}}>{item.sub}</div> : null}
    </div>
  );
};

const Stack: React.FC<Props & {dark: boolean}> = ({look, item, dark}) => {
  const frame = useCurrentFrame();
  const rows = item.rows ?? [];
  const bad = (item.tone ?? "problem") === "problem";
  const fill = bad ? "rgba(70,30,34,0.92)" : "rgba(10,40,44,0.85)";
  return (
    <div style={{width: W}}>
      <Kicker text={item.kicker} look={look} dark={dark} />
      <Title text={item.title} look={look} dark={dark} size={56} />
      {rows.map((row, n) => {
        const p = pop(frame, row.at ?? n * 10);
        const arrived = frame >= (row.at ?? n * 10);
        return (
          <div key={n} style={{height: 116, marginBottom: 22, borderRadius: 18, border: `2px solid rgba(255,255,255,${arrived ? 0 : 0.18})`,
            position: "relative", overflow: "hidden"}}>
            <div style={{position: "absolute", inset: 0, background: fill, borderRadius: 18, display: "flex", alignItems: "center",
              gap: 26, padding: "0 30px", opacity: Math.min(1, p * 1.4), transform: `translateX(${(1 - p) * -60}px)`}}>
              <Icon name={row.icon} size={54} colour={bad ? "#FFB4B4" : look.accent} />
              <div style={{flex: 1, fontFamily: FAMILIES.poppins, fontWeight: 700, fontSize: 44, color: "#FFFFFF"}}>{row.text}</div>
              {row.mark && row.mark !== "none" ? <Icon name={row.mark === "check" ? "check" : "cross"} size={52}
                colour={row.mark === "check" ? look.accent : look.alert} /> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const Steps: React.FC<Props & {dark: boolean}> = ({look, item, dark}) => {
  const frame = useCurrentFrame();
  const steps = item.steps ?? [];
  const n = steps.length;
  const gap = W / Math.max(1, n);
  const reached = steps.filter((s, k) => frame >= (s.at ?? k * 12)).length;
  const line = interpolate(frame, [steps[Math.max(0, reached - 1)]?.at ?? 0, (steps[Math.max(0, reached - 1)]?.at ?? 0) + 10],
    [Math.max(0, reached - 2), Math.max(0, reached - 1)], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <div style={{width: W}}>
      <Kicker text={item.kicker} look={look} dark={dark} />
      <Title text={item.title} look={look} dark={dark} size={54} />
      <div style={{position: "relative", height: 420}}>
        <div style={{position: "absolute", left: gap / 2, right: gap / 2, top: 170, height: 8, background: "rgba(255,255,255,0.2)", borderRadius: 4}} />
        <div style={{position: "absolute", left: gap / 2, top: 170, height: 8, width: n > 1 ? (line / (n - 1)) * (W - gap) : 0,
          background: look.accent, borderRadius: 4}} />
        {steps.map((s, k) => {
          const at = s.at ?? k * 12;
          const on = frame >= at;
          const p = pop(frame, at);
          const x = gap * k + gap / 2;
          return (
            <div key={k} style={{position: "absolute", left: x - gap / 2, width: gap, top: 0, display: "flex", flexDirection: "column", alignItems: "center"}}>
              <div style={{height: 100, opacity: on ? 1 : 0.35}}><Icon name={s.icon} size={66} colour="#FFFFFF" /></div>
              <div style={{width: 96, height: 96, borderRadius: 96, marginTop: 4, display: "flex", alignItems: "center", justifyContent: "center",
                background: on ? look.accent : "transparent", border: `4px solid ${on ? look.accent : "rgba(255,255,255,0.35)"}`,
                transform: `scale(${on ? 0.8 + 0.2 * p : 0.85})`, fontFamily: FAMILIES.poppins, fontWeight: 800, fontSize: 40,
                color: on ? look.ink : "rgba(255,255,255,0.6)"}}>{k + 1}</div>
              <div style={{marginTop: 18, fontFamily: FAMILIES.poppins, fontWeight: 700, fontSize: n > 3 ? 30 : 36, lineHeight: 1.15,
                textAlign: "center", color: on ? "#FFFFFF" : "rgba(255,255,255,0.45)", padding: "0 6px"}}>{s.label}</div>
              {s.sub ? <div style={{marginTop: 8, fontFamily: FAMILIES.poppins, fontWeight: 600, fontSize: 24, textAlign: "center",
                color: look.accent, opacity: pop(frame, s.sub_at ?? at + 10)}}>{s.sub}</div> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Compare: React.FC<Props & {dark: boolean}> = ({look, item, dark}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const at = item.at ?? 10;
  const tilt = spring({frame: frame - at, fps, config: {damping: 9, stiffness: 90}}) * (item.heavy === "left" ? -9 : 9);
  const box = (side: "left" | "right", text?: string) => {
    const heavy = item.heavy === side;
    return (
      <div style={{position: "relative", background: heavy ? look.alert : "rgba(255,255,255,0.12)", color: "#FFFFFF", borderRadius: 14,
        padding: heavy ? "34px 30px" : "20px 26px", fontFamily: FAMILIES.poppins, fontWeight: 700, fontSize: heavy ? 44 : 36,
        opacity: struck(frame, item.strike === side ? item.strike_at : undefined), transform: `scale(${pop(frame, side === "left" ? 0 : 6)})`}}>
        {text}
        {item.strike === side ? <Strike at={item.strike_at} colour={look.alert} thick={6} /> : null}
      </div>
    );
  };
  return (
    <div style={{width: W + 20, display: "flex", flexDirection: "column", alignItems: "center"}}>
      <Kicker text={item.kicker} look={look} dark={dark} />
      <Title text={item.title} look={look} dark={dark} size={56} />
      <div style={{width: W - 40, transform: `rotate(${tilt}deg)`, transformOrigin: "50% 100%"}}>
        <div style={{display: "flex", justifyContent: "space-between", alignItems: "flex-end", padding: "0 10px"}}>
          {box("left", item.left?.text)}{box("right", item.right?.text)}
        </div>
        <div style={{height: 16, background: "rgba(255,255,255,0.3)", borderRadius: 8, marginTop: 10}} />
      </div>
      <div style={{width: 0, height: 0, borderLeft: "56px solid transparent", borderRight: "56px solid transparent",
        borderBottom: `96px solid ${look.accent}`, marginTop: 4}} />
    </div>
  );
};

const Bars: React.FC<Props & {dark: boolean}> = ({look, item, dark}) => {
  const frame = useCurrentFrame();
  const bars = item.bars ?? [];
  const tall = item.layout === "panel" ? 420 : 620;
  return (
    <div style={{width: W, display: "flex", flexDirection: "column", alignItems: "center"}}>
      <Kicker text={item.kicker} look={look} dark={dark} />
      <Title text={item.title} look={look} dark={dark} size={72} />
      <div style={{display: "flex", alignItems: "flex-end", justifyContent: "center", gap: 90, height: tall + 120,
        borderBottom: "4px solid rgba(255,255,255,0.4)", width: W - 60}}>
        {bars.map((b, k) => {
          const at = b.at ?? k * 15;
          const g = interpolate(frame, [at, at + 18], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
          const h = Math.max(12, tall * Math.max(0.03, Math.min(1, b.size)) * (1 - Math.pow(1 - g, 3)));
          const colour = toneColour(look, b.tone ?? (k ? "problem" : "solution"), true);
          return (
            <div key={k} style={{display: "flex", flexDirection: "column", alignItems: "center", width: 200}}>
              <div style={{fontFamily: FAMILIES.poppins, fontWeight: 800, fontSize: 46, color: colour, opacity: g, marginBottom: 12}}>{b.value}</div>
              <div style={{width: 160, height: h, background: colour, borderRadius: "14px 14px 0 0"}} />
            </div>
          );
        })}
      </div>
      <div style={{display: "flex", justifyContent: "center", gap: 90, width: W - 60, marginTop: 14}}>
        {bars.map((b, k) => <div key={k} style={{width: 200, textAlign: "center", fontFamily: FAMILIES.poppins, fontWeight: 600, fontSize: 32,
          color: "rgba(255,255,255,0.85)"}}>{b.label}</div>)}
      </div>
    </div>
  );
};

const Points: React.FC<Props & {dark: boolean}> = ({look, item, dark}) => {
  const frame = useCurrentFrame();
  const items = item.items ?? [];
  return (
    <div style={{width: W}}>
      <Kicker text={item.kicker} look={look} dark={dark} />
      <Title text={item.title} look={look} dark={dark} size={item.numbered ? 76 : 86} />
      {items.map((it, k) => {
        const at = it.at ?? k * 12;
        const p = pop(frame, at, 30, true);
        const strikeAt = item.strike_at !== undefined ? item.strike_at + k * 5 : undefined;
        return (
          <div key={k} style={{display: "flex", alignItems: "center", gap: 28, marginBottom: item.numbered ? 30 : 20,
            opacity: Math.min(1, p * 1.4) * struck(frame, strikeAt), transform: `translateX(${(1 - p) * -40}px)`,
            borderBottom: item.numbered ? "2px solid rgba(255,255,255,0.18)" : "none", paddingBottom: item.numbered ? 22 : 0}}>
            {item.numbered
              ? <div style={{fontFamily: FAMILIES[look.font], fontWeight: 800, fontSize: 110, lineHeight: 1, color: look.accent, width: 150}}>
                  {String(k + 1).padStart(2, "0")}</div>
              : <div style={{width: 20, height: 20, borderRadius: 20, background: look.accent, flexShrink: 0}} />}
            <div style={{position: "relative", fontFamily: FAMILIES.poppins, fontWeight: 700, fontSize: item.numbered ? 58 : 54, color: "#FFFFFF"}}>
              {it.text}
              <Strike at={strikeAt} colour={look.alert} thick={6} />
            </div>
          </div>
        );
      })}
    </div>
  );
};

const Badge: React.FC<Props & {dark: boolean}> = ({look, item, dark}) => {
  const frame = useCurrentFrame();
  const at = item.at ?? 12;
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "center"}}>
      <Kicker text={item.kicker} look={look} dark={dark} />
      <div style={{width: 150, height: 150, borderRadius: 26, border: `5px solid ${look.accent}`, display: "flex", alignItems: "center",
        justifyContent: "center", transform: `scale(${pop(frame, 0)})`}}><Icon name={item.icon ?? "hospital"} size={86} colour={look.accent} /></div>
      <div style={{marginTop: 30, fontFamily: FAMILIES[look.font], fontWeight: 800, fontSize: 76, lineHeight: 1.08, textAlign: "center",
        color: look.accent, opacity: pop(frame, 6)}}>{item.text}</div>
      <div style={{marginTop: 26, transform: `scale(${pop(frame, at)})`}}><Icon name="check" size={80} colour={look.accent} /></div>
      {item.badge ? <div style={{marginTop: 12, fontFamily: FAMILIES.poppins, fontWeight: 700, fontSize: 40, color: "#FFFFFF",
        opacity: pop(frame, at + 6)}}>{item.badge}</div> : null}
    </div>
  );
};

const End: React.FC<Props> = ({look, item, frames}) => {
  const frame = useCurrentFrame();
  const p = pop(frame, 0, 30, true);
  const dim = interpolate(frame, [Math.max(1, frames - 40), frames - 10], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{background: look.paper, alignItems: "center", justifyContent: "center", opacity: Math.min(1, p * 2)}}>
      {item.logo ? <Img src={staticFile(item.logo)} style={{width: 560, transform: `scale(${0.85 + 0.15 * p})`}} /> : null}
      {item.sub ? <div style={{marginTop: 24, fontFamily: FAMILIES.poppins, fontWeight: 600, fontSize: 40, color: look.ink}}>{item.sub}</div> : null}
      {item.cta ? <div style={{marginTop: 80, fontFamily: FAMILIES.poppins, fontWeight: 700, fontSize: 42, color: "#FFFFFF", maxWidth: 860, textAlign: "center",
        background: look.box_bg, padding: "22px 44px", borderRadius: 60, opacity: pop(frame, 14), transform: `translateY(${(1 - pop(frame, 14)) * 30}px)`}}>
        {item.cta}</div> : null}
      {item.handle ? <div style={{marginTop: 26, fontFamily: FAMILIES.poppins, fontWeight: 600, fontSize: 34, color: look.ink,
        opacity: pop(frame, 22)}}>{item.handle}</div> : null}
      <AbsoluteFill style={{background: "#000", opacity: dim * 0}} />
    </AbsoluteFill>
  );
};

const TYPES: Record<string, React.FC<Props & {dark: boolean}>> = {
  statement: Statement, counter: Counter, stack: Stack, steps: Steps, compare: Compare, bars: Bars, points: Points, badge: Badge,
};

export const Scene: React.FC<Props> = (props) => {
  if (props.item.type === "end") return <End {...props} />;
  const Type = TYPES[props.item.type];
  const dark = props.item.layout !== "top";
  return (
    <Background look={props.look} layout={props.item.layout} frames={props.frames}
      handle={props.item.layout === "top" ? undefined : props.look.handle}>
      {Type ? <Type {...props} dark={dark} /> : null}
    </Background>
  );
};
