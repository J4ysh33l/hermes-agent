---
name: Hermes motion graphics
description: The scenes, marks and captions drawn over faceless shorts and over edits of your own footage; every colour and face comes from the style.
colors:
  field: "#111111"
  on-field: "#FFFFFF"
  accent: "#FFD400"
  alert: "#E53935"
  good: "#2ECC71"
  ink: "#111111"
  paper: "#FFFFFF"
typography:
  display:
    fontFamily: "{style.graphics.font}"
    fontSize: "84–190px (fitted to one line)"
    fontWeight: 600
    lineHeight: 1.02
    letterSpacing: "-0.035em"
  number:
    fontFamily: "{style.graphics.font}"
    fontSize: "up to 300px (fitted)"
    fontWeight: 600
    lineHeight: 0.95
    letterSpacing: "-0.05em"
  row:
    fontFamily: "{style.graphics.font}"
    fontSize: "60–72px"
    fontWeight: 500
    lineHeight: 1.08
    letterSpacing: "-0.02em"
  support:
    fontFamily: "{style.graphics.font}"
    fontSize: "36–54px"
    fontWeight: 500
    lineHeight: 1.2
rounded:
  chip: "{style.graphics.radius}"
  icon-well: "24px"
  pill: "999px"
spacing:
  side: "84px"
  panel-top: "96px"
  row-panel: "146px"
  row-numbered: "170px"
components:
  panel-field:
    backgroundColor: "{colors.field}"
    textColor: "{colors.on-field}"
    height: "960px"
    width: "1080px"
  top-chip:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.chip}"
    padding: "6px 30px 14px"
  end-cta:
    backgroundColor: "{colors.field}"
    textColor: "{colors.on-field}"
    rounded: "{rounded.pill}"
    padding: "26px 44px"
---

# Hermes motion graphics

Code: `src/kit.tsx` (motion and marks for both pipelines), `src/edit/Scenes.tsx` (explainer scenes for
edits), `src/edit/Timeline.tsx` (one overlay: scenes and captions), `src/scenes/` (the faceless library),
`src/theme.ts` (faceless profiles). A brand is a style file (`$HERMES_HOME/edit/styles/<name>.yaml`) or a
faceless profile; brand files never live in this repo.

## Overview

Calm, editorial explainer graphics for vertical video (1080×1920, 30 fps) that sit with a talking person
rather than shout over them. One idea per scene, said in a few large words, arriving exactly on the spoken
word. The brand comes in only through the style: field colour, accent, alert, ink, paper, one typeface,
one radius. Every scene must render correctly in any palette, light or dark (checked: a dark teal field and
a cream field with a serif, from the same props). The tokens above are the neutral `clean` style; brands override them.

## Colors

- **field** (`graphics.box_bg`): the panel and full-frame background, a soft vertical gradient to 16% darker.
- **on-field**: worked out per field: white on a dark field, `ink` on a light one (relative luminance > 0.4).
  Dim text, hairlines (14%) and tints come from it with alpha. A white literal anywhere is a bug.
- **accent**: the starred word, list numerals, ticks, the seam line, the curtain. Never body text.
- **alert**: problems: strikes, crosses, a problem counter. **good**: solutions on light grounds.
- **paper / ink**: the light chips over the wall (`top` layout) and the end card.
- Tints for icon wells: accent or alert at 16% alpha; an icon in an alert well is alert mixed 45% toward on-field.

## Typography

One family per brand (`graphics.font`), three weights: 600 display and numbers, 500 rows and support. Size
does the hierarchy: display 84–190 px fitted to one line (`fitLine`), rows 60–72, support 36–54. Tracking
tightens as size grows (-0.02em rows, -0.035em headings, -0.05em numbers). Numbers are tabular.
The accent word: `*word*` in any title or line sets that word in the accent colour, in italic. One or two per
scene; it is the brand's voice, not decoration. Sentence case. No labels above headings.

## Layout

- **panel**: the top half (0–960) is the field; ffmpeg moves the face, zoomed ×1.3, into the bottom half on
  exactly the overlay's frames. The panel is solid from its first frame to its last: a hard cut both ways,
  never a slide (a slide shows two faces).
- **full**: the whole frame; content between y 300 and 1360, captions low (y 1560).
- **top**: no field; light chips (paper, ink text, soft shadow) above the head.
- Content is left-aligned on an 84 px margin, except statements over the wall and the end card.
- List scenes reserve their rows' height and centre the block; the title sits large in the middle before the
  first row and moves up as it lands.
- Captions move with the layout: a caption page that crosses a panel's edge splits there.

## Elevation & Depth

Flat fields. The only shadows: light chips over footage (`0 18px 40px rgba(0,0,0,0.18)`), so they lift off
a busy wall. No glow, no glass, no decorative circles.

## Shapes

Radius from the style (`graphics.radius`) on chips; 24 px icon wells; pills for the end card's call to
action. Hairline rules (2 px, 14%) between rows. Marks are drawn, round-capped: a strike bar, ticks and
crosses (SVG strokes in a 16% disc).

## Components

- **Motion vocabulary** (`kit.tsx`), used by every scene in both pipelines:
  - `Rise`: type rises out of a mask, 14 frames, ease-out-expo `cubic-bezier(0.16, 1, 0.3, 1)`.
  - Curtain: on a panel or full scene's first frame the accent fills the field and collapses into the seam
    line (or off the bottom) over 11 frames. The scene's one authored moment.
  - `Strike`: a bar across the whole text (8% overshoot, -1.5° rise), drawn over 9 frames; struck text dims to
    50%. `Underline`, `Tick` (check or cross drawing itself), `useCount` (lands exactly on the number).
  - Exits are cuts. Nothing bounces.
- **Scenes** (edit): statement, counter, stack, steps, compare, bars, points, badge, end; `library` draws
  any faceless scene (chart, timeline, map, diagram, quote, clipping, ...) full-frame in the style's colours.
- **Captions**: word pages, the spoken word in an accent box (`mode: box`), problem/solution words in
  alert/good.

## Do's and Don'ts

- Do take every colour from the style or the profile. A new scene must pass in a dark and a light palette.
- Do time every element to a word (`at`); a scene arrives about 0.6 s before its first element, never
  empty for longer.
- Do size display type to fit one line; never let a phone wrap a heading into three.
- Don't add kickers or eyebrows, numbered sections unless the count matters, gradient text, glass, side
  stripes, or bouncing entrances.
- Don't slide a panel: the footage under it cuts on one frame.
- Don't add a font a style can't name: new faces go in `FAMILIES` (edit) and `FONTS` (faceless) together.
- Verify by rendering stills (`remotion still ... --frame`) over real footage at 1080×1920 before shipping.
