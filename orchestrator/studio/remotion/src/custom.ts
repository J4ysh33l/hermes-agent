import type React from "react";
import type {CustomScene} from "./types";

// Custom scenes: components written for one video (by Claude, or by hand), checked by studio/custom.py,
// and registered by that job's own entry file before the root is. A custom scene whose component did not
// pass the checks never reaches here: Python renders its fallback (a library scene) instead.
export type CustomView = React.FC<{scene: CustomScene; frames: number}>;

const VIEWS: Record<string, CustomView> = {};

export const registerCustom = (views: Record<string, CustomView>) => {
  Object.assign(VIEWS, views);
};

export const customView = (key: string): CustomView | undefined => VIEWS[key];
