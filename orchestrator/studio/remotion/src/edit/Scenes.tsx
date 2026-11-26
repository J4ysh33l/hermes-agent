// Explainer scenes for edits of your own footage: the director's main tools besides cutting.
// Each scene fills one of three layouts:
//   panel: the top half (0–960) on the brand colour; ffmpeg moves your face, zoomed, into the bottom half
//          on the same frames, so the panel is solid from its first frame to its last (a hard cut both ways)
//   full:  the whole frame (your voice carries on); captions sit near the bottom
//   top:   no background; type on light chips in the space above your head (a hook, a number)
// Elements arrive on the words they belong to: every `at` here is a frame from the scene's start
// (render.py turns the plan's "S4.12" anchors into frames). Type rises out of masks; the panel opens with
// the accent colour collapsing into the seam line; a starred word (*prevention*) is the accent, in italic.
import "@fontsource/inter-tight/500.css";
import "@fontsource/inter-tight/600.css";
import "@fontsource/inter-tight/600-italic.css";
import "@fontsource/inter-tight/700.css";
import "@fontsource/poppins/600.css";
import "@fontsource/poppins/700.css";
import React from "react";
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from "remotion";
import * as L from "lucide-react";
import {decimalsOf, fitLine, Marked, plain, ramp, Rise, Strike, Tick, Underline, useCount} from "../kit";
import {SceneFrame} from "../motion";
import {SCENES} from "../Short";
import {DEFAULT_PROFILE, Profile, ProfileProvider} from "../theme";
import type {Scene as LibraryScene} from "../types";
import {EditLook, FAMILIES} from "./Graphic";

export const SEAM = 960;
const SIDE = 84; // margin each side
const CW = 1080 - 2 * SIDE; // content width

// Every colour a scene draws comes from the style: the field (box_bg), accent, alert, ink, paper. Text on the
// field is white on a dark field and ink on a light one; hairlines, dim text and tints are made from those.
const rgb = (hex: string) => {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6), 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
};
export const alpha = (hex: string, a: number) => `rgba(${rgb(hex).join(", ")}, ${a})`;
export const light = (hex: string) => {
  const [r, g, b] = rgb(hex).map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4;
};
const mix = (hex: string, other: string, k: number) => {
  const a = rgb(hex), b = rgb(other);
  return `rgb(${a.map((c, i) => Math.round(c + (b[i] - c) * k)).join(", ")})`;
};
const pal = (look: EditLook) => {
  const fg = light(look.box_bg) ? look.ink : "#FFFFFF";
  return {
    fg,
    fade: (a: number) => alpha(fg, a),
    line: alpha(fg, 0.14),
    alertTint: alpha(look.alert, 0.16),
    accentTint: alpha(look.accent, 0.16),
    alertSoft: mix(look.alert, fg, 0.45), // an icon in the alert's tint, readable on the field
  };
};

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
  blood: L.Droplet, fever: L.Thermometer, bandage: L.Bandage, plus: L.Cross, code: L.Code, terminal: L.Terminal,
  server: L.Server, key: L.Key, mail: L.Mail, star: L.Star, flag: L.Flag, book: L.BookOpen, car: L.Car, plane: L.Plane,
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
  kicker?: string; // accepted for old plans, not drawn: the heading carries itself
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
  scene?: Record<string, unknown>; // type "library": a scene of the faceless library (chart, map, timeline, ...)
  beats?: {at: number}[];
};

export type Look = EditLook & {handle?: string};
export type Props = {look: Look; item: SceneItem; frames: number; dark: boolean};

const display = (look: EditLook) => FAMILIES[look.font] ?? FAMILIES.intertight;
const textFamily = (look: EditLook) => FAMILIES[look.font] ?? FAMILIES.intertight;

const toneColour = (look: EditLook, tone: Tone | undefined, dark: boolean) =>
  tone === "problem" ? look.alert : tone === "solution" ? (dark ? look.accent : look.good) : dark ? pal(look).fg : look.ink;

const Icon: React.FC<{name?: string; size: number; colour: string; stroke?: number}> = ({name, size, colour, stroke = 1.8}) => {
  const C = name ? ICONS[name] : undefined;
  return C ? <C size={size} color={colour} strokeWidth={stroke} /> : null;
};

// Struck text dims once the stroke has crossed it.
const dimmed = (frame: number, at?: number) => (at === undefined ? 1 : interpolate(frame, [at + 6, at + 14], [1, 0.5],
  {extrapolateLeft: "clamp", extrapolateRight: "clamp"}));

// ---- layouts ------------------------------------------------------------------------------------------

// The field: solid from frame 0. The accent colour fills it on the cut and collapses down into the seam line
// (panel) or off the bottom (full) over 10 frames, uncovering the content.
const Field: React.FC<{look: Look; layout: SceneItem["layout"]; bare?: boolean; children: React.ReactNode}> =
  ({look, layout, bare, children}) => {
    const P = pal(look);
  const frame = useCurrentFrame();
  const height = layout === "panel" ? SEAM : 1920;
  const curtain = ramp(frame, 0, 11);
  const seam = layout === "panel" ? 6 : 0;
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", left: 0, top: 0, width: 1080, height, overflow: "hidden",
        background: `linear-gradient(180deg, ${look.box_bg} 0%, ${shade(look.box_bg, -0.16)} 100%)`}}>
        {look.handle ? (
          <div style={{position: "absolute", right: SIDE - 20, top: layout === "panel" ? 44 : 250, display: "flex", alignItems: "center",
            gap: 8, color: P.fade(0.62), fontFamily: textFamily(look), fontWeight: 500, fontSize: 24}}>
            {look.handle}
          </div>
        ) : null}
        {bare ? children : (
          <div style={{position: "absolute", left: SIDE, right: SIDE, top: layout === "panel" ? 96 : 300,
            bottom: layout === "panel" ? 70 : 560, display: "flex", flexDirection: "column", justifyContent: "center"}}>
            {children}
          </div>
        )}
        <div style={{position: "absolute", left: 0, right: 0, bottom: 0, height: seam + (height - seam) * (1 - curtain),
          background: look.accent}} />
      </div>
    </AbsoluteFill>
  );
};

const shade = (hex: string, amount: number) => {
  const n = parseInt(hex.slice(1), 16);
  const f = (c: number) => Math.max(0, Math.min(255, Math.round(c * (1 + amount))));
  return `rgb(${f(n >> 16)}, ${f((n >> 8) & 255)}, ${f(n & 255)})`;
};

// A heading for a scene with parts. Before the first part arrives it sits large in the middle; when the first
// part lands it moves up to its place above them (the list grows under it).
const Heading: React.FC<{text?: string; look: Look; dark: boolean; first: number; below: number; size: number}> =
  ({text, look, dark, first, below, size}) => {
    const P = pal(look);
    const frame = useCurrentFrame();
    if (!text) return null;
    const dock = ramp(frame, first - 2, 14);
    return (
      <div style={{transform: `translateY(${(1 - dock) * below / 2}px) scale(${1 + 0.14 * (1 - dock)})`, transformOrigin: "left center",
        marginBottom: 44}}>
        <Rise at={0}>
          <div style={{fontFamily: display(look), fontWeight: 600, fontSize: size, lineHeight: 1.02, letterSpacing: "-0.035em",
            color: dark ? P.fg : look.ink, textWrap: "balance"} as React.CSSProperties}>
            <Marked text={text} accent={dark ? look.accent : look.good} />
          </div>
        </Rise>
      </div>
    );
  };

// ---- the scene types ----------------------------------------------------------------------------------

const Statement: React.FC<Props> = ({look, item, dark}) => {
  const P = pal(look);
  const frame = useCurrentFrame();
  const lines = item.lines ?? [{text: item.text ?? "", tone: item.tone, strike_at: item.strike_at, underline_at: item.underline_at}];
  const top = item.layout === "top";
  const most = top ? 140 : item.layout === "full" ? 190 : 170;
  if (top) {
    return (
      <AbsoluteFill style={{alignItems: "center", paddingTop: 150}}>
        {lines.map((line, n) => {
          const size = fitLine(line.text, most, CW - 60, look.font);
          const colour = line.tone === "problem" ? look.alert : look.ink;
          return (
            <Rise key={n} at={line.at ?? n * 5} style={{marginBottom: 14}}>
              <div style={{position: "relative", background: look.paper, borderRadius: look.radius, padding: "6px 30px 14px",
                fontFamily: display(look), fontWeight: 600, fontSize: size, lineHeight: 1.04, letterSpacing: "-0.035em", color: colour,
                boxShadow: "0 18px 40px rgba(0,0,0,0.18)", opacity: dimmed(frame, line.strike_at)}}>
                <Marked text={line.text} accent={look.good} />
                <Strike at={line.strike_at} colour={look.alert} thick={Math.max(6, size / 11)} />
              </div>
            </Rise>
          );
        })}
        {item.sub ? <Rise at={item.sub_at ?? 10}><div style={{marginTop: 6, background: look.box_bg, color: P.fg, borderRadius: look.radius,
          padding: "10px 24px", fontFamily: textFamily(look), fontWeight: 500, fontSize: 42}}><Marked text={item.sub} accent={look.accent} /></div></Rise> : null}
      </AbsoluteFill>
    );
  }
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "flex-start"}}>
      {item.icon ? <div style={{marginBottom: 28, opacity: ramp(frame, 0, 10), transform: `translateY(${(1 - ramp(frame, 0, 12)) * 20}px)`}}>
        <Icon name={item.icon} size={96} colour={toneColour(look, item.tone, dark)} stroke={1.6} /></div> : null}
      {lines.map((line, n) => {
        const size = fitLine(line.text, most, CW, look.font);
        return (
          <Rise key={n} at={line.at ?? n * 5}>
            <div style={{position: "relative", display: "inline-block", fontFamily: display(look), fontWeight: 600, fontSize: size,
              lineHeight: 1.02, letterSpacing: "-0.04em", color: toneColour(look, line.tone, dark), opacity: dimmed(frame, line.strike_at)}}>
              <Marked text={line.text} accent={look.accent} />
              <Strike at={line.strike_at} colour={look.alert} thick={Math.max(7, size / 12)} />
              <Underline at={line.underline_at} colour={look.accent} thick={Math.max(6, size / 18)} />
            </div>
          </Rise>
        );
      })}
      {item.sub ? <Rise at={item.sub_at ?? 10} style={{marginTop: 30}}>
        <div style={{fontFamily: textFamily(look), fontWeight: 500, fontSize: 54, lineHeight: 1.2, color: P.fade(0.82)}}>
          <Marked text={item.sub} accent={look.accent} /></div></Rise> : null}
    </div>
  );
};

const Counter: React.FC<Props> = ({look, item, dark}) => {
  const P = pal(look);
  const at = item.at ?? 0;
  const to = item.number ?? 0;
  const value = useCount(item.count_from ?? 0, to, at);
  const digits = decimalsOf(to);
  const shown = `${item.prefix ?? ""}${value.toLocaleString("en-IN", {maximumFractionDigits: digits, minimumFractionDigits: digits})}${item.suffix ?? ""}`;
  const final = `${item.prefix ?? ""}${to.toLocaleString("en-IN", {maximumFractionDigits: digits, minimumFractionDigits: digits})}${item.suffix ?? ""}`;
  const top = item.layout === "top";
  const size = fitLine(final, top ? 230 : 300, top ? 700 : CW, look.font) * 0.92;
  const colour = toneColour(look, item.tone ?? "problem", dark || top ? !top : false);
  const body = (
    <>
      <Rise at={at} frames={12}>
        <div style={{fontFamily: display(look), fontWeight: 600, fontSize: size, lineHeight: 0.95, letterSpacing: "-0.05em",
          color: top ? (item.tone === "solution" ? look.good : look.alert) : colour, fontVariantNumeric: "tabular-nums"}}>{shown}</div>
      </Rise>
      {item.label ? <Rise at={at + 6} style={{marginTop: top ? 6 : 18}}><div style={{fontFamily: textFamily(look), fontWeight: 500,
        fontSize: top ? 44 : 54, lineHeight: 1.15, letterSpacing: "-0.01em", color: top ? look.ink : P.fg, textAlign: top ? "center" : "left"}}>
        <Marked text={item.label} accent={top ? look.good : look.accent} /></div></Rise> : null}
      {item.sub ? <Rise at={at + 14} style={{marginTop: 20}}><div style={{display: "inline-block", background: top ? look.box_bg : P.fade(0.1),
        color: P.fg, fontFamily: textFamily(look), fontWeight: 500, fontSize: 36, padding: "8px 22px", borderRadius: 999}}>
        {item.sub}</div></Rise> : null}
    </>
  );
  if (top) {
    return (
      <AbsoluteFill style={{alignItems: "center", paddingTop: 120}}>
        <div style={{background: look.paper, borderRadius: look.radius * 2, padding: "26px 56px 34px", display: "flex", flexDirection: "column",
          alignItems: "center", boxShadow: "0 18px 40px rgba(0,0,0,0.18)", opacity: ramp(useCurrentFrame(), at - 4, 8)}}>{body}</div>
      </AbsoluteFill>
    );
  }
  return <div style={{display: "flex", flexDirection: "column", alignItems: "flex-start"}}>{body}</div>;
};

const firstAt = (ats: (number | undefined)[], step: number) => Math.min(...ats.map((a, k) => a ?? k * step), 999);

const Stack: React.FC<Props> = ({look, item, dark}) => {
  const P = pal(look);
  const rows = item.rows ?? [];
  const bad = (item.tone ?? "problem") === "problem";
  const rowH = 146;
  const first = firstAt(rows.map((r) => r.at), 10);
  return (
    <div>
      <Heading text={item.title} look={look} dark={dark} first={first} below={rows.length * rowH} size={item.layout === "full" ? 112 : 96} />
      {rows.map((row, n) => {
        const at = row.at ?? n * 10;
        return (
          <Rise key={n} at={at}>
            <div style={{height: rowH, display: "flex", alignItems: "center", gap: 30, borderTop: `2px solid ${P.line}`}}>
              <div style={{width: 88, height: 88, borderRadius: 24, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                background: bad ? P.alertTint : P.accentTint}}>
                <Icon name={row.icon} size={48} colour={bad ? P.alertSoft : look.accent} />
              </div>
              <div style={{flex: 1, fontFamily: textFamily(look), fontWeight: 500, fontSize: 60, lineHeight: 1.08, letterSpacing: "-0.02em",
                color: P.fg}}><Marked text={row.text} accent={look.accent} /></div>
              {row.mark && row.mark !== "none" ? <Tick at={at + 6} kind={row.mark} size={64}
                colour={row.mark === "check" ? look.accent : look.alert} /> : null}
            </div>
          </Rise>
        );
      })}
    </div>
  );
};

const Points: React.FC<Props> = ({look, item, dark}) => {
  const P = pal(look);
  const frame = useCurrentFrame();
  const items = item.items ?? [];
  const rowH = item.numbered ? 170 : 128;
  const first = firstAt(items.map((i) => i.at), 12);
  return (
    <div>
      <Heading text={item.title} look={look} dark={dark} first={first} below={items.length * rowH} size={item.layout === "full" ? 120 : 100} />
      {items.map((it, k) => {
        const at = it.at ?? k * 12;
        const strikeAt = item.strike_at !== undefined ? item.strike_at + k * 5 : undefined;
        return (
          <Rise key={k} at={at}>
            <div style={{minHeight: rowH, display: "flex", alignItems: "center", gap: 34, borderTop: item.numbered ? `2px solid ${P.line}` : "none",
              opacity: dimmed(frame, strikeAt)}}>
              {item.numbered
                ? <div style={{fontFamily: display(look), fontWeight: 600, fontSize: 112, lineHeight: 1, letterSpacing: "-0.05em", color: look.accent,
                    width: 120, fontVariantNumeric: "tabular-nums"}}>{k + 1}</div>
                : <div style={{width: 30, height: 6, borderRadius: 6, background: look.accent, flexShrink: 0}} />}
              <div style={{position: "relative", fontFamily: textFamily(look), fontWeight: 500, fontSize: item.numbered ? 72 : 64,
                lineHeight: 1.1, letterSpacing: "-0.02em", color: P.fg}}>
                <Marked text={it.text} accent={look.accent} />
                <Strike at={strikeAt} colour={look.alert} thick={item.numbered ? 10 : 9} />
              </div>
            </div>
          </Rise>
        );
      })}
    </div>
  );
};

const Steps: React.FC<Props> = ({look, item, dark}) => {
  const P = pal(look);
  const frame = useCurrentFrame();
  const steps = item.steps ?? [];
  const n = steps.length;
  const gap = CW / Math.max(1, n);
  const ats = steps.map((s, k) => s.at ?? k * 12);
  const reached = ats.filter((a) => frame >= a).length;
  const last = ats[Math.max(0, reached - 1)] ?? 0;
  const line = Math.max(0, reached - 2) + ramp(frame, last, 12) * (reached > 1 ? 1 : 0);
  return (
    <div>
      <Heading text={item.title} look={look} dark={dark} first={firstAt(ats, 12)} below={380} size={item.layout === "full" ? 96 : 80} />
      <div style={{position: "relative", height: 380}}>
        <div style={{position: "absolute", left: gap / 2, right: gap / 2, top: 44, height: 4, background: P.line, borderRadius: 4}} />
        <div style={{position: "absolute", left: gap / 2, top: 44, height: 4, width: n > 1 ? (line / (n - 1)) * (CW - gap) : 0,
          background: look.accent, borderRadius: 4}} />
        {steps.map((s, k) => {
          const on = frame >= ats[k];
          const p = ramp(frame, ats[k], 12);
          return (
            <div key={k} style={{position: "absolute", left: gap * k, width: gap, top: 0, display: "flex", flexDirection: "column", alignItems: "center"}}>
              <div style={{width: 92, height: 92, borderRadius: 92, display: "flex", alignItems: "center", justifyContent: "center",
                background: on ? look.accent : look.box_bg, border: `3px solid ${on ? look.accent : P.line}`, transform: `scale(${0.9 + 0.1 * p})`}}>
                {s.icon ? <Icon name={s.icon} size={44} colour={on ? look.ink : P.fade(0.5)} />
                  : <span style={{fontFamily: display(look), fontWeight: 600, fontSize: 40, color: on ? look.ink : P.fade(0.5)}}>{k + 1}</span>}
              </div>
              <div style={{marginTop: 26, opacity: 0.35 + 0.65 * p, transform: `translateY(${(1 - p) * 16}px)`, fontFamily: textFamily(look),
                fontWeight: 600, fontSize: n > 3 ? 34 : 40, lineHeight: 1.1, textAlign: "center", color: P.fg, padding: "0 8px"}}>{s.label}</div>
              {s.sub ? <div style={{marginTop: 10, fontFamily: textFamily(look), fontWeight: 500, fontSize: 28, textAlign: "center",
                color: look.accent, opacity: ramp(frame, s.sub_at ?? ats[k] + 10, 10)}}>{s.sub}</div> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Compare: React.FC<Props> = ({look, item, dark}) => {
  const P = pal(look);
  const frame = useCurrentFrame();
  const at = item.at ?? 10;
  const tilt = ramp(frame, at, 22) * (item.heavy === "left" ? -7 : 7);
  const box = (side: "left" | "right", text?: string) => {
    const heavy = item.heavy === side;
    const strikeAt = item.strike === side ? item.strike_at : undefined;
    return (
      <Rise at={side === "left" ? 0 : 6}>
        <div style={{position: "relative", background: heavy ? look.alert : P.fade(0.1), color: P.fg, borderRadius: look.radius,
          padding: heavy ? "30px 34px" : "20px 28px", fontFamily: textFamily(look), fontWeight: 600, fontSize: heavy ? 48 : 38, lineHeight: 1.1,
          opacity: dimmed(frame, strikeAt)}}>
          {text}
          <Strike at={strikeAt} colour={heavy ? P.fg : look.alert} thick={7} />
        </div>
      </Rise>
    );
  };
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "center"}}>
      <div style={{alignSelf: "stretch"}}><Heading text={item.title} look={look} dark={dark} first={0} below={0} size={84} /></div>
      <div style={{width: CW - 40, transform: `rotate(${tilt}deg)`, transformOrigin: "50% 100%"}}>
        <div style={{display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 24}}>
          {box("left", item.left?.text)}{box("right", item.right?.text)}
        </div>
        <div style={{height: 10, background: P.fade(0.32), borderRadius: 8, marginTop: 12}} />
      </div>
      <div style={{width: 0, height: 0, borderLeft: "48px solid transparent", borderRight: "48px solid transparent",
        borderBottom: `84px solid ${look.accent}`, marginTop: 2}} />
    </div>
  );
};

const Bars: React.FC<Props> = ({look, item, dark}) => {
  const P = pal(look);
  const frame = useCurrentFrame();
  const bars = item.bars ?? [];
  const tall = item.layout === "panel" ? 380 : 620;
  const colW = Math.min(260, (CW - 40) / Math.max(1, bars.length) - 40);
  return (
    <div>
      <Heading text={item.title} look={look} dark={dark} first={0} below={0} size={item.layout === "full" ? 116 : 96} />
      <div style={{display: "flex", alignItems: "flex-end", justifyContent: "space-around", height: tall + 110, borderBottom: `3px solid ${P.line}`}}>
        {bars.map((b, k) => {
          const at = b.at ?? k * 15;
          const g = ramp(frame, at, 22);
          const h = Math.max(10, tall * Math.max(0.03, Math.min(1, b.size)) * g);
          const colour = toneColour(look, b.tone ?? (k ? "solution" : "problem"), true);
          return (
            <div key={k} style={{display: "flex", flexDirection: "column", alignItems: "center", width: colW}}>
              <div style={{fontFamily: display(look), fontWeight: 600, fontSize: 58, letterSpacing: "-0.03em", color: colour, opacity: g,
                marginBottom: 14, whiteSpace: "nowrap"}}>{b.value}</div>
              <div style={{width: colW * 0.72, height: h, background: colour, borderRadius: "24px 24px 0 0"}} />
            </div>
          );
        })}
      </div>
      <div style={{display: "flex", justifyContent: "space-around", marginTop: 18}}>
        {bars.map((b, k) => <div key={k} style={{width: colW, textAlign: "center", fontFamily: textFamily(look), fontWeight: 500, fontSize: 36,
          color: P.fade(0.8), opacity: ramp(frame, b.at ?? k * 15, 12)}}>{b.label}</div>)}
      </div>
    </div>
  );
};

const Badge: React.FC<Props> = ({look, item}) => {
  const P = pal(look);
  const frame = useCurrentFrame();
  const at = item.at ?? 12;
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "flex-start"}}>
      <div style={{width: 132, height: 132, borderRadius: 34, background: P.accentTint, display: "flex", alignItems: "center",
        justifyContent: "center", opacity: ramp(frame, 0, 10), transform: `scale(${0.9 + 0.1 * ramp(frame, 0, 14)})`}}>
        <Icon name={item.icon ?? "hospital"} size={72} colour={look.accent} /></div>
      <Rise at={5} style={{marginTop: 34}}><div style={{fontFamily: display(look), fontWeight: 600, fontSize: fitLine(item.text ?? "", 120, CW, look.font),
        lineHeight: 1.02, letterSpacing: "-0.04em", color: P.fg}}><Marked text={item.text ?? ""} accent={look.accent} /></div></Rise>
      {item.badge ? <div style={{marginTop: 30, display: "flex", alignItems: "center", gap: 16}}>
        <Tick at={at} kind="check" colour={look.accent} size={64} />
        <Rise at={at + 4}><div style={{fontFamily: textFamily(look), fontWeight: 500, fontSize: 46, color: P.fg}}>{item.badge}</div></Rise>
      </div> : null}
    </div>
  );
};

// A scene from the faceless library (chart, map, timeline, quote, clipping, diagram, ...), drawn in this
// edit's colours on the full field. Its parts arrive on `beats` (frames from the scene's start).
const toProfile = (look: Look): Profile => ({
  ...DEFAULT_PROFILE,
  name: "edit",
  theme: {...DEFAULT_PROFILE.theme, bg: look.box_bg, glow: look.box_bg, panel: shade(look.box_bg, 0.25), text: pal(look).fg,
    muted: pal(look).fade(0.7), accent: look.accent, cool: look.figure && look.figure !== "none" ? look.figure : look.accent,
    bad: look.alert, good: look.good, font: look.font === "intertight" ? "intertight" : "inter", background: "flat"},
  motion: {...DEFAULT_PROFILE.motion, feel: "soft", enter: "rise", exit: "cut", exit_frames: 1, drift: 0.02, transition: "none"},
});

const Library: React.FC<{look: Look; item: SceneItem; frames: number}> = ({look, item, frames}) => {
  const P = pal(look);
  const scene = {start: 0, end: frames / 30, enter: "", exit: "", transition: "", emoji: "",
    beats: (item.beats ?? []).map((b) => b.at / 30), ...item.scene} as unknown as LibraryScene;
  const entry = SCENES[scene.type];
  if (!entry) return null;
  const View = entry.view;
  return (
    <ProfileProvider profile={toProfile(look)}>
      <SceneFrame frames={frames} enter="fade" exit="cut" fullBleed={entry.fullBleed}>
        <View scene={scene as never} frames={frames} />
      </SceneFrame>
    </ProfileProvider>
  );
};

const End: React.FC<{look: Look; item: SceneItem}> = ({look, item}) => {
  const P = pal(look);
  const frame = useCurrentFrame();
  const curtain = ramp(frame, 0, 12);
  return (
    <AbsoluteFill style={{background: look.paper, alignItems: "center", justifyContent: "center"}}>
      {item.logo ? <div style={{opacity: ramp(frame, 4, 14), transform: `translateY(${(1 - ramp(frame, 4, 18)) * 40}px)`}}>
        <Img src={staticFile(item.logo)} style={{width: 640}} /></div> : null}
      {item.sub ? <Rise at={10} style={{marginTop: 26}}><div style={{fontFamily: display(look), fontWeight: 500, fontSize: 46,
        letterSpacing: "-0.02em", color: look.ink}}><Marked text={item.sub} accent={look.good} /></div></Rise> : null}
      {item.cta ? (
        <div style={{marginTop: 96, display: "flex", alignItems: "center", gap: 18, maxWidth: 900, background: look.box_bg, color: P.fg,
          padding: "26px 44px", borderRadius: 999, fontFamily: textFamily(look), fontWeight: 600, fontSize: 42, lineHeight: 1.15,
          opacity: ramp(frame, 16, 10), transform: `translateY(${(1 - ramp(frame, 16, 16)) * 30}px)`}}>
          <span style={{textAlign: "center"}}>{plain(item.cta)}</span>
          <L.ArrowRight size={44} color={look.accent} strokeWidth={2.2} style={{flexShrink: 0}} />
        </div>
      ) : null}
      {item.handle ? <div style={{marginTop: 30, fontFamily: textFamily(look), fontWeight: 500, fontSize: 34, color: look.ink,
        opacity: 0.8 * ramp(frame, 24, 12)}}>{item.handle}</div> : null}
      <div style={{position: "absolute", left: 0, right: 0, bottom: 0, height: 1920 * (1 - curtain), background: look.accent}} />
    </AbsoluteFill>
  );
};

export const EXPLAINERS: Record<string, React.FC<Props>> = {
  statement: Statement, counter: Counter, stack: Stack, steps: Steps, compare: Compare, bars: Bars, points: Points, badge: Badge,
};

export const Scene: React.FC<{look: Look; item: SceneItem; frames: number}> = ({look, item, frames}) => {
  const P = pal(look);
  if (item.type === "end") return <End look={look} item={item} />;
  if (item.type === "library") {
    return <Field look={{...look, handle: undefined}} layout="full" bare><Library look={look} item={item} frames={frames} /></Field>;
  }
  const Type = EXPLAINERS[item.type];
  if (!Type) return null;
  if (item.layout === "top") return <Type look={look} item={item} frames={frames} dark={false} />;
  return <Field look={look} layout={item.layout}><Type look={look} item={item} frames={frames} dark /></Field>;
};
