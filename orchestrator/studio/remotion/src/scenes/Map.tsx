import {geoCentroid, geoInterpolate, geoMercator, geoPath} from "d3-geo";
import type {Feature, FeatureCollection, Geometry} from "geojson";
import React, {useMemo} from "react";
import {Easing, interpolate, useCurrentFrame} from "remotion";
import {feature} from "topojson-client";
import type {GeometryCollection, Topology} from "topojson-specification";
import world from "world-atlas/countries-50m.json";
import {Arrive, usePop} from "../motion";
import {useTheme} from "../theme";
import type {MapScene} from "../types";

const W = 900;
const H = 1100;
type Country = Feature<Geometry, {name: string}>;

const COUNTRIES: Country[] = (feature(world as unknown as Topology,
  (world as unknown as Topology).objects.countries as GeometryCollection<{name: string}>) as FeatureCollection<Geometry, {name: string}>).features;
const BY_NAME = new Map(COUNTRIES.map((c) => [c.properties.name.toLowerCase(), c]));
export const country = (name: string) => BY_NAME.get(name.toLowerCase());

// Where the camera ends: the focus country (or all highlighted ones) filling the frame with a margin.
// The centre comes from the fitted projection itself (a bounding box breaks across the date line: Alaska).
const target = (shapes: Country[]) => {
  const collection = {type: "FeatureCollection" as const, features: shapes};
  const fitted = geoMercator().fitExtent([[90, 120], [W - 90, H - 120]], collection);
  const scale = Math.min(fitted.scale(), 6000);
  const centre = fitted.invert!([W / 2, H / 2]) as [number, number];
  return {centre, scale};
};

const LABEL_H = 64;
const SHORT: Record<string, string> = {"United States of America": "USA", "United Kingdom": "UK",
  "United Arab Emirates": "UAE", "Central African Rep.": "CAR", "Dem. Rep. Congo": "DR Congo"};
export const labelOf = (name: string) => SHORT[name] ?? name;
const widthOf = (name: string) => labelOf(name).length * 26 + 40;

// Each label sits on its country, kept inside the map, and moved the shortest way (up or down) until
// it overlaps no earlier label (neighbours like China / Taiwan / South Korea).
const placeLabels = (spots: {x: number; y: number; width: number}[]) => {
  const placed: {x: number; y: number; width: number}[] = [];
  for (const spot of spots) {
    const x = Math.min(W - spot.width / 2 - 12, Math.max(spot.width / 2 + 12, spot.x));
    const free = (y: number) => !placed.some((p) => Math.abs(p.x - x) < (p.width + spot.width) / 2 + 8 &&
      Math.abs(p.y - y) < LABEL_H);
    const offsets = [0, 1, -1, 2, -2, 3, -3, 4, -4].map((k) => spot.y + k * LABEL_H)
      .filter((y) => y > LABEL_H && y < H - LABEL_H / 2);
    placed.push({...spot, x, y: offsets.find(free) ?? spot.y});
  }
  return placed;
};

// A map: the camera flies from the whole world to the focus; highlighted countries fill in; a route
// (country to country) draws itself as an arc; names pop up. Natural Earth shapes (public domain).
export const WorldMap: React.FC<{scene: MapScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const lit = scene.highlight.map(country).filter(Boolean) as Country[];
  const focus = (scene.focus ? [country(scene.focus)!] : lit.length ? lit : COUNTRIES);
  const end = useMemo(() => target(focus), [scene.focus, scene.highlight.join()]);
  const flyEnd = Math.min(45, frames * 0.4);
  const fly = interpolate(frame, [0, flyEnd], [0, 1], {extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic)});
  const startScale = W / (2 * Math.PI);
  const projection = useMemo(() => geoMercator()
    .center([end.centre[0] * fly, interpolate(fly, [0, 1], [25, end.centre[1]])])
    .scale(Math.exp(interpolate(fly, [0, 1], [Math.log(startScale), Math.log(end.scale)])))
    .translate([W / 2, H / 2]), [end, fly, startScale]);
  const path = geoPath(projection);
  // 241 country outlines are the slow part: once the camera stops they are drawn once and reused.
  const outlines = useMemo(() => COUNTRIES.map((c) => path(c) ?? ""), [projection]);
  const fill = interpolate(frame, [flyEnd - 6, flyEnd + 8], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const stops = scene.route.map(country).filter(Boolean) as Country[];
  const routeAt = flyEnd + 10;
  const draw = interpolate(frame, [routeAt, routeAt + Math.max(20, frames * 0.25)], [0, 1], {extrapolateLeft: "clamp",
    extrapolateRight: "clamp", easing: Easing.inOut(Easing.quad)});
  const arcs = stops.slice(1).map((stop, i) => {
    const between = geoInterpolate(geoCentroid(stops[i]), geoCentroid(stop));
    return Array.from({length: 41}, (_, k) => projection(between(k / 40))!);
  });
  const names = scene.labels ? (lit.length ? lit : focus.slice(0, 1)) : [];
  return (
    <div>
      {scene.title ? (
        <Arrive style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 76, color: theme.text, marginBottom: 20}}>
          {scene.title}
        </Arrive>
      ) : null}
      <svg width={W} height={H} style={{borderRadius: 30, background: `${theme.panel}88`, overflow: "hidden"}}>
        {COUNTRIES.map((c, i) => {
          const on = lit.includes(c);
          return (
            <path key={i} d={outlines[i]} fill={on ? theme.accent : theme.panel} fillOpacity={on ? 0.35 + 0.55 * fill : 1}
              stroke={on ? theme.accent : `${theme.muted}66`} strokeWidth={on ? 3 : 1} />
          );
        })}
        {arcs.map((points, i) => {
          const share = interpolate(draw, [i / arcs.length, (i + 1) / arcs.length], [0, 1], {extrapolateLeft: "clamp",
            extrapolateRight: "clamp"});
          const shown = points.slice(0, Math.max(1, Math.round(share * points.length)));
          const tip = shown[shown.length - 1];
          return share > 0 ? (
            <g key={i}>
              <polyline points={shown.map((p) => p.join(",")).join(" ")} fill="none" stroke={theme.cool} strokeWidth={9}
                strokeLinecap="round" strokeDasharray="2 18" />
              <circle cx={tip[0]} cy={tip[1]} r={16} fill={theme.cool} />
            </g>
          ) : null;
        })}
        {placeLabels(names.map((c) => {
          const [x, y] = path.centroid(c);
          return {x, y, width: widthOf(c.properties.name)};
        })).map((spot, i) => (
          <Label key={i} at={[spot.x, spot.y]} name={names[i].properties.name} delay={flyEnd + 4 + i * 4} />
        ))}
      </svg>
    </div>
  );
};

const Label: React.FC<{at: [number, number]; name: string; delay: number}> = ({at, name, delay}) => {
  const theme = useTheme();
  const p = usePop(delay);
  if (!Number.isFinite(at[0])) return null;
  const width = widthOf(name);
  return (
    <g transform={`translate(${at[0]} ${at[1]}) scale(${p})`} opacity={Math.min(1, p * 2)}>
      <rect x={-width / 2} y={-34} width={width} height={60} rx={14} fill={theme.bg} opacity={0.85} />
      <text textAnchor="middle" y={10} fontFamily={theme.sans} fontWeight={900} fontSize={40} fill={theme.text}>{labelOf(name)}</text>
    </g>
  );
};
