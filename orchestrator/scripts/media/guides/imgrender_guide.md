# Writing template.json (imgrender.py)

Write the template once. The script then renders one image per data row with no model calls. Do not generate PIL code.

## Steps
1. `imgrender.py fonts` if you need a font name other than `DejaVu Sans` / `DejaVu Sans Bold`.
2. Write `template.json` and a data file (`rows.csv`, or `rows.json` as a list of objects).
3. `imgrender.py check template.json --data rows.csv` — tests every row in memory, saves nothing. Fix every `FAIL` and `WARN`.
4. `imgrender.py render template.json --data rows.csv --out OUT/`
5. Open at least one output image and look at it before delivering. The script cannot judge taste or contrast.

One image without a data file: `--set title="Hello" --set price=99`.

## Template
```json
{
  "size": [1080, 1080],
  "background": {"gradient": ["#0f1b2d", "#274060"], "angle": 90},
  "output": "promo_{id}.png",
  "layers": [
    {"type": "rect",  "box": [0, 0, 1080, 14], "fill": "#ffcc00"},
    {"type": "text",  "text": "{headline}", "box": [70, 150, 940, 520], "font": "DejaVu Sans Bold",
     "size": 110, "min_size": 44, "max_lines": 5, "valign": "middle", "color": "#ffffff"},
    {"type": "image", "path": "{logo}", "box": [70, 910, 220, 120], "fit": "contain", "optional": true}
  ]
}
```
- `size` and every `box` are pixels; `box` is `[x, y, width, height]`. Layers draw in order, later on top.
- `{field}` is filled from the row's column. A missing field fails that row (`FAIL n: data field 'x' missing`); it is never left blank.
- `{id}` in `output` is the row number unless your data has an `id` column. Use one so file names are stable.
- `background`: a colour, `{"gradient": [c1, c2], "angle": 90}`, or `{"image": "bg.png", "fit": "cover"}`.
- Layer types: `rect` (fill, radius, opacity), `text`, `image` (fit `contain|cover|stretch`, opacity).
- `text`: shrinks from `size` to `min_size` until it fits `box` within `max_lines`. If it still does not fit you get a WARN. Fix by a bigger box, a lower `min_size`, shorter copy or more `max_lines`. Never accept the warning silently.
- `image` with `"optional": true` is skipped when the field is empty or the file is missing. Without it that row fails.
- Relative paths (images, fonts, backgrounds) resolve next to the template file.

## Exit codes
0 all ok, 1 some rows failed or had warnings, 2 bad template or usage. Check the code, not just the printed lines.

## Brand rules
Colours, fonts, logo placement and copy tone come from the user. Ask for them; do not invent.
