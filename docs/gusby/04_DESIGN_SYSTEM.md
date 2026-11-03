# Gusby: Design System & Visual Specification (DESIGN_SYSTEM.md)
**Version:** 1.1 (Extended via CR-001)  
**Status:** Approved & Binding  
**Source of Truth Precedence:** 00_PRODUCT_BRIEF.md > 04_DESIGN_SYSTEM.md > DECISIONS.md > Prompt Defaults

---

## 1. Aesthetic Vision & Design Philosophy `[Decided]`

Gusby is an **intellectual, editorial, and graph-first** workspace. It rejects the hyper-saturated gradients, cartoonish illustrations, and cluttered widgets of generic SaaS dashboards. 

### Core Aesthetic Axioms:
1. **Pure White Canvas**: Background is strictly pure white (`#FFFFFF`). No muddy gray backgrounds.
2. **Generous Whitespace**: Abundant negative space around elements to foster deep concentration and structural clarity.
3. **Light Mode Only**: No dark mode in MVP. The interface embodies the clarity of crisp white paper and editorial typesetting.
4. **Subtle Hairlines**: Borders are razor-thin (1px) with low-contrast neutral tones (`#E5E7EB` / `#E2E8F0`).
5. **Earthy Preset Palettes**: Accents and node groupings rely on natural, mineral pigments (slate, terracotta, olive moss, ochre sand).
6. **Subtle Motion**: All transitions are understated (150ms–250ms `cubic-bezier(0.16, 1, 0.3, 1)`), zero springy or bouncy cartoon physics.
7. **Admin Utility Restraint**: Admin screens follow the identical design tokens. Tables, metrics cards, and SVG charts maintain editorial typography, razor hairlines, and whitespace. No flashy third-party admin templates.

---

## 2. Color Palette & Design Tokens `[Decided]`

### 2.1. Canvas & Neutral Tokens
```css
:root {
  --canvas-bg: #FFFFFF;
  --surface-raised: #FAFAFA;
  --surface-overlay: #FFFFFF;
  --hairline: #E5E7EB;
  --hairline-focus: #9CA3AF;
  
  --text-primary: #111827;    /* Ink Black */
  --text-secondary: #4B5563;  /* Charcoal */
  --text-muted: #9CA3AF;      /* Muted Slate */
  --text-faint: #D1D5DB;      /* Whispering Silver */
}
```

### 2.2. Earthy Palette Presets (Selectable in Settings)

#### Preset 1: Editorial Slate (Default)
- Primary Accent: `#2C3E50` (Deep Slate)
- Node Fill: `#F1F5F9` (Muted Ice)
- Node Stroke: `#64748B` (Steel Slate)
- Edge Color: `#CBD5E1` (Silver Cord)
- Highlight / Evidence: `#FEF3C7` (Soft Parchment) / Border `#D97706`

#### Preset 2: Terracotta Stone
- Primary Accent: `#9C4221` (Burnt Terracotta)
- Node Fill: `#FDF2E9` (Clay Tint)
- Node Stroke: `#C05621` (Red Clay)
- Edge Color: `#E2D9D2` (Dusty Cord)
- Highlight / Evidence: `#FEE2E2` (Soft Clay Glow) / Border `#B91C1C`

#### Preset 3: Olive Moss
- Primary Accent: `#2D3B2D` (Forest Pine)
- Node Fill: `#F4F7F4` (Sage Mist)
- Node Stroke: `#5A6B5C` (Lichen Green)
- Edge Color: `#D4DDD5` (Earthy Willow)
- Highlight / Evidence: `#ECFDF5` (Mint Leaf Glow) / Border `#059669`

#### Preset 4: Desert Ochre
- Primary Accent: `#785E2F` (Warm Ochre)
- Node Fill: `#FBF8F1` (Sand Tint)
- Node Stroke: `#A38042` (Raw Ochre)
- Edge Color: `#E8E2D5` (Sand Cord)
- Highlight / Evidence: `#FEF9C3` (Pale Sand Glow) / Border `#CA8A04`

---

## 3. Typography & Typesetting `[Decided]`

- **Display & Headings**: Inter or system modern sans-serif (`font-sans`), weights 500 (Medium) and 600 (Semi-bold).
- **Body Text**: Inter (`font-sans`), weight 400 (Regular), relaxed leading (`line-height: 1.625`), tracking slightly negative (`-0.011em`).
- **Data, Offsets, Logs & Code**: JetBrains Mono or system monospace (`font-mono`), weight 400.
- **Sizes**:
  - Display / Hero: `text-2xl` (24px, 1.5rem, weight 600)
  - Section Headings: `text-lg` (18px, 1.125rem, weight 600)
  - Card Titles: `text-sm` (14px, 0.875rem, weight 600)
  - Body: `text-sm` (14px, 0.875rem, weight 400)
  - Captions / Meta / Badges: `text-xs` (12px, 0.75rem, weight 500)

---

## 4. Admin Component & Visual Specifications `[Decided - CR-001]`

### 4.1. Status Badges & Semantic Colors
All badges use muted backgrounds with saturated text and hairline borders:
- **Healthy / Enabled / Completed**: Background `#ECFDF5`, Border `#A7F3D0`, Text `#065F46` (Emerald).
- **Degraded / Circuit Open / Needs Review**: Background `#FFFBEB`, Border `#FDE68A`, Text `#92400E` (Warm Amber).
- **Down / Failed / Error / Retracted**: Background `#FEF2F2`, Border `#FECACA`, Text `#991B1B` (Ruby Crimson).
- **Paused / Waiting for AI / Queued**: Background `#F8FAFC`, Border `#E2E8F0`, Text `#475569` (Cool Slate).

### 4.2. Metric Cards & KPI Layout
- **Card Container**: Pure white background (`bg-white`), 1px hairline border (`border border-gray-200`), rounded corners (`rounded-lg`), subtle shadow (`shadow-sm`), generous padding (`p-5`).
- **Label**: `text-xs font-medium text-gray-500 uppercase tracking-wider`.
- **Value**: `text-2xl font-semibold text-gray-900 tracking-tight font-sans` or `font-mono`.
- **Sub-label / Trend**: `text-xs text-gray-500 mt-1`.

### 4.3. Lightweight Inline SVG Charts
- **No external chart libraries**: Zero dependency on Chart.js, Highcharts, or D3 bundle bloat.
- **Sparklines & Area Charts**:
  - Implemented as responsive `<svg viewBox="0 0 300 60" preserveAspectRatio="none">`.
  - Stroke: 1.5px hairline (`stroke-gray-800` or `stroke-emerald-600`).
  - Fill: Subtle gradient to transparent (`stop-opacity="0.12"` to `stop-opacity="0.0"`).
  - Gridlines: Minimal horizontal guidelines (`stroke-dasharray="2,2"` with `#F3F4F6`).

### 4.4. Data Tables
- **Container**: `bg-white border border-gray-200 rounded-lg overflow-hidden`.
- **Header**: `bg-gray-50/70 border-b border-gray-200 text-xs font-semibold text-gray-500 uppercase tracking-wider py-3 px-4`.
- **Row**: `border-b border-gray-100 hover:bg-gray-50/50 transition-colors py-3 px-4 text-sm text-gray-700`.
- **Empty State**: Centered icon, muted headline, subtle description, generous vertical padding (`py-12`).

### 4.5. Destructive Confirmation Modals
- **Backdrop**: `bg-black/25 backdrop-blur-xs`.
- **Dialog Surface**: Pure white `bg-white border border-gray-200 rounded-xl shadow-xl max-w-lg p-6`.
- **Warning Header**: Red warning icon badge (`bg-red-50 text-red-600 border border-red-100 p-2 rounded-full`).
- **Consequence Summary**: Bordered amber/red callout detailing exact items affected (e.g. `"Deleting this document will soft-retract 4 canonical propositions."`).
- **Typed Input Requirement**: Monospace input (`font-mono border border-gray-300 focus:border-red-500`) requiring exact string match. Submit button remains disabled until exact match is typed.
