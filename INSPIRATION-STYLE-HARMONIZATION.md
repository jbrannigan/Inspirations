# Inspiration Style Harmonization

**Objective:** Align the `Inspirations` application with the data-first, minimalist **Edward Tufte** design principles utilized in the `New Home` prototype portal, while strictly preserving the soft, feminine, and cozy interior-design aesthetic of the original build.

This document serves as an architectural style guide for Codex to update `app/styles.css` and the associated React components.

---

## 1. Typography: Editorial Elegance meets Tufte Legibility
The current `DM Sans` provides a friendly, modern vibe, but lacks the structured "editorial" weight that grounds a Tufte design. We will adopt a dual-font system pairing classic serifs with a highly legible geometric sans-serif for UI.

- **Primary Headings & Titles (Serif):** 
  - *Recommendation:* `Playfair Display`, `Lora`, or `Libre Baskerville`.
  - *Usage:* Application branding, board titles, and primary H1/H2 delineations. This acts as the anchor to "architectural elegance" and the print-like feel.
- **Body & UI Elements (Sans-Serif):**
  - *Recommendation:* `Inter` or `Outfit` (shifting away from DM Sans).
  - *Usage:* Data tags, buttons, dense list items, and system UI. These fonts scale cleanly at tiny sizes without overwhelming the serif headers.

---

## 2. Refined Color Palette: Architectural Warmth
We want to keep the cozy interior-design feel but apply Tufte's core rule: *Use color sparingly, and only to highlight meaning or state.*

- **Canvas / Backgrounds:** 
  - Lighten the current `--bg` (`#faf8f5`) slightly to a true Tufte ivory/parchment tone, such as `#fdfbf7` or `#fffff8`. 
  - Ensure the contrast between `--bg` and `--panel` (`#ffffff`) remains whisper-thin. It should feel like high-quality architect's paper.
- **Primary Accent ("Highlighter" to "Hardware"):** 
  - Soften the primary `--accent` goldenrod (`#b8860b`) to a more muted, elegant brass or aged gold tone (e.g., `#c1a067` or `#c8a975`). It should feel less like a highlighter and more like high-end cabinet hardware.
- **Secondary Accents (Sage & Rose):** 
  - *Retain* `--accent-sage` (`#7a9b8a`) and `--accent-rose` (`#c4787a`). 
  - *Restriction:* Use them exactly like Tufte uses his famous red ink. The app should remain mostly ivory and deep charcoal. Use the Rose and Sage strictly for active tags, notification dots, or transient "selected" states. Avoid large blocks of these colors.
- **Text & Borders:** 
  - The current text color (`#2c2825`) is perfect—it acts as a warm espresso rather than a harsh, eye-straining pure black, reinforcing the cozy print feel.

### Suggested CSS Variables Update:
```css
:root {
  /* Surfaces */
  --bg: #fdfbf7; /* Lightened from #faf8f5 */
  --panel: #ffffff;
  --panel-hover: #f9f8f6;
  --surface-subtle: #f0ede8;

  /* Text (Unchanged - excellent warmth) */
  --text: #2c2825;
  --text-secondary: #6b6560;
  --muted: #9c9590;

  /* Borders */
  --border: rgba(44, 40, 37, 0.08); /* Softened */
  --border-hover: rgba(44, 40, 37, 0.15);

  /* Accents */
  --accent: #c1a067; /* Muted Brass */
  --accent-soft: rgba(193, 160, 103, 0.12);
  --accent-hover: #a88b56;
  
  --accent-rose: #c4787a;
  --accent-sage: #7a9b8a;
}
```

---

## 3. Whitespace & Geometry (The Tufte Structure)
Tufte design breathes through negative space. The UI framing the images must fade into the background, providing a structured, minimalist skeleton for the creative content.

- **Open the Margins:** 
  - Increase padding significantly inside panels and around dense text. A cozy vibe combined with massive whitespace creates a luxurious, "art gallery" feeling where every kitchen mockup and wood texture has room to breathe.
- **Soften the Shadows (Diffuse Warmth):** 
  - Swap out standard black/gray drop-shadows for warm-tinted, highly diffuse shadows. 
  - Example: `box-shadow: 0 4px 12px rgba(139, 111, 92, 0.06);` (using the `--accent-2` brown). This makes UI UI panels look like physical matte photographs resting on a desk, rather than digital floating boxes.
- **Invisible UI:** 
  - Strive for "No Borders" where possible. Rely on whitespace and subtle background shifts (`--panel` vs `--bg`) to delineate zones.
  - Drop heavy borders on search bars and inputs in favor of soft underlines or delicate 0.5px hairlines.

---

## Summary for Codex
1. Update the root CSS variables to the softer, warmer palette above.
2. Implement Google Fonts for a `serif` heading and a clean `sans-serif` UI body.
3. Loosen up padding globally across the grid and sidebars.
4. Tint box-shadows with a brown/amber hue at extremely low opacity.
