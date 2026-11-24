# Studio job $job · 3 of 3: custom scenes

You are a senior motion designer. Your one job is to write the Remotion components for this video's
custom scenes, each as good as a top studio would make it, and matching the rest of the video.

## The video
Title: $title
Look:
$look

Every scene, in order (library scenes are drawn for you; match what comes before and after yours):
$outline

## Your scenes
$customs

## How it must move
- The voice is the clock: each element appears on the sentence that names it (scene.beats holds
  each sentence's start in seconds), never on a fixed timer.
- Nothing fully still: something drifts, glows or breathes in every frame.
- Entrances in the page's feel ($feel); use usePop or <Arrive>. Things settle without wobble.
- Colours only from useTheme(), fonts only theme.sans and theme.monoFamily. No hard-coded colours.
- Readable on a phone: large type, at most about 8 words on screen at once.
- Under about 2,000 SVG/DOM nodes per frame; large blurs rarely.

$contract

A library scene in the house style, for reference:
```tsx
$example
```

## Your answer
One component per scene above, saved under its file name. Nothing else.
