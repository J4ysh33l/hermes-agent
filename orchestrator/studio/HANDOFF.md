# Studio → Claude handoff (copy this file to `studio/HANDOFF.md` in your handoff repo)

Setting up the repo and the Claude scheduled task: `orchestrator/HANDOFF.md`.

Hermes opens an issue for every `/studio make` when it has no Anthropic API key (Claude on your plan).
Your Claude scheduled task starts on the **issue opened** event and does this:

1. Read the issue. It names a folder `studio/<id>/` and a request file in it: `request.md` (a new
   video) or `fix-<n>.md` (the checks found problems in your last answer).
2. The request file is the whole brief: the page's style, the rules, the facts (the only source of
   numbers, quotes and headlines), the scene format, the real limits of the pipeline and, at the end,
   the contract for custom-scene components. Follow it exactly. Quality beats speed: the library scenes
   are a fast track, and any picture inside the limits can be a custom scene.
3. Commit, on the default branch, only the files the request names:
   - the storyboard JSON (`storyboard.json`, or `storyboard-fix<n>.json` for a fix request);
   - for every custom scene, its component `sceneNN.tsx` (hook 1 is scene 01; a custom hook 2 or 3 is
     `hook2.tsx` / `hook3.tsx`), with that scene's
     `"component"` set to the file name.
4. Close the issue.

Hermes checks for the answer every 30 minutes, runs every check (the storyboard's, and TypeScript plus
a real render of each component), and renders the video in the night window. A component that fails is
drawn as the scene's fallback, so the video is never lost; a storyboard that fails gets one fix request.
The notes can be private: keep this repo private.
