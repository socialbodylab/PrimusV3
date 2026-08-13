# Primus + Radius systems site

Greyscale presentation of how Primus (light) and Radius (sound) share a show LAN without mixing show and setup traffic.

## Run

From this directory:

```bash
python3 -m http.server 8765
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/).

ES modules require HTTP (not `file://`).

## Sections

1. **Thesis** — Show / Setup / Watch lane table  
2. **Cue flow** — SVG tabs: light · sound · together  
3. **Role × time** — stage mgr / LD / sound / wardrobe  
4. **Lock matrix** — Primus prototype/production vs Radius prep/show  
5. **Recipes** — light and sound pipelines  
6. **API map** — filterable cheat sheet (detail in `../API_CONTROLS.md`)

## Stack

Static HTML/CSS + vanilla ES modules. No build step.
