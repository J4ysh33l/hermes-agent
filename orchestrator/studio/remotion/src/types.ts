import type {Enter, Exit, Profile} from "./theme";

// The props video.py writes (props.json). Times are seconds on the voice track; the composition is
// as long as the voice plus a short tail. Every file path is relative to the job folder (--public-dir).

export interface Word {
  text: string;
  start: number;
  end: number;
  emphasis: boolean; // *marked* in the script: accent colour + camera punch
}

export interface Side {
  label: string;
  points: string[];
}

interface SceneBase {
  start: number;
  end: number;
  beats: number[]; // each sentence's start, seconds from the scene's start
  enter: Enter | ""; // "" = the profile's
  exit: Exit | "";
  emoji: string; // "" = none; else it pops on the scene's first *emphasised* word (or 0.3 s in)
}

export interface TitleScene extends SceneBase {
  type: "title";
  text: string;
  kicker: string;
}

export interface BulletsScene extends SceneBase {
  type: "bullets";
  title: string;
  items: string[];
}

export interface CodeScene extends SceneBase {
  type: "code";
  title: string;
  code: string;
}

export interface StatScene extends SceneBase {
  type: "stat";
  value: number;
  prefix: string;
  suffix: string;
  label: string;
}

export interface ImageScene extends SceneBase {
  type: "image";
  src: string;
  caption: string;
}

export interface CompareScene extends SceneBase {
  type: "compare";
  left: Side;
  right: Side;
}

export interface TerminalScene extends SceneBase {
  type: "terminal";
  title: string;
  lines: string[]; // "$ cmd" lines type themselves; others print as output
}

export interface ChartScene extends SceneBase {
  type: "chart";
  kind: "bar" | "line";
  title: string;
  labels: string[];
  values: number[];
  suffix: string;
  highlight: number; // index of the bar/point to colour; -1 = the largest
}

export interface DiagramScene extends SceneBase {
  type: "diagram";
  title: string;
  nodes: string[]; // a chain, top to bottom, arrows between
}

export interface QuoteScene extends SceneBase {
  type: "quote";
  text: string;
  author: string;
}

export interface Event {
  when: string;
  what: string;
}

export interface TimelineScene extends SceneBase {
  type: "timeline";
  title: string;
  events: Event[];
}

export interface ClippingScene extends SceneBase {
  type: "clipping";
  source: string;
  date: string;
  headline: string;
  highlight: string; // words in the headline to sweep a highlighter over
}

export interface PostScene extends SceneBase {
  type: "post";
  name: string;
  handle: string;
  text: string;
  likes: string;
}

export interface MemeScene extends SceneBase {
  type: "meme";
  src: string;
  top: string;
  bottom: string;
}

export interface Panel {
  label: string;
  src: string;
}

export interface BeforeAfterScene extends SceneBase {
  type: "beforeafter";
  before: Panel;
  after: Panel;
}

export interface LogoScene extends SceneBase {
  type: "logo";
  name: string;
  src: string;
  tagline: string;
}

export interface MapScene extends SceneBase {
  type: "map";
  title: string;
  focus: string; // country the camera flies to ("" = all highlighted)
  highlight: string[];
  route: string[]; // countries in order; an arc draws between each pair
  labels: boolean;
}

export type Scene = MapScene | TitleScene | BulletsScene | CodeScene | StatScene | ImageScene | CompareScene | TerminalScene |
  ChartScene | DiagramScene | QuoteScene | TimelineScene | ClippingScene | PostScene | MemeScene | BeforeAfterScene |
  LogoScene;

export interface ShortProps extends Record<string, unknown> {
  profile: Profile;
  audio: string;
  seconds: number;
  scenes: Scene[];
  words: Word[];
}

// cover.py's props: one scene (start 0, every part already said) and the cover's words.
export type CoverProps = {
  profile: Profile;
  scene: Scene;
  words: string;
};
