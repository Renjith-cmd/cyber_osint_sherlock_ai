# Sherlock AI — Workspaces Visual Reconstruction Report

## Executive Summary
This document reports on the complete, reference-accurate visual and functional reconstruction of the **Entities**, **Relationship Graph**, and **Evidence & Claims** workspaces in Sherlock AI, extending the aesthetic system and component architecture of the primary dashboard reference (`.user_uploaded/media_1791828264513.png`).

All three workspaces have been implemented as actual, fully functional investigation interfaces powered by the live FastAPI backend, with zero mock or synthetic data in production mode, 49 vector cat sticker assets, dynamic SVG graph layout, horizontal evidence timeline tracks, and slide-out inspection drawers.

---

## 1. Visual Design Architecture & Palette System

The three workspaces adopt the exact aesthetic hierarchy defined in the primary dashboard reference:

| Design Token | Value | Role in Workspaces |
| :--- | :--- | :--- |
| **`--bg-canvas`** | `#171827` / `#191A2B` | Deep obsidian background canvas and sidebar rail |
| **`--bg-ivory-panel`** | `#F7F1E9` | Main workspace panels, curved card containers, and headers |
| **`--card-surface`** | `#FFFDF9` | High-elevation card surfaces for entities, evidence, and toolbars |
| **`--accent-peach`** | `#F5AE89` | Primary action buttons, badges, border highlights, and brand accents |
| **`--text-plum`** | `#191A2B` | Ultra-dark purple/navy primary text for maximum legibility |
| **`--text-plum-muted`**| `#716B82` | Secondary labels, timestamps, metadata pill keys |
| **`--border-cream`** | `#E4DCD2` | Crisp warm-ivory dividing lines and card borders |
| **`--status-match`** | `#166534` (`#E2F4EC` bg) | Canonical / Verified / MATCH status pill |
| **`--status-review`** | `#9A3412` (`#FFE4D6` bg) | Provisional / Disputed / REVIEW status pill |
| **`--status-nonmatch`**| `#475569` (`#E8E5EE` bg) | Canonical singletons / NON-MATCH status pill |

---

## 2. Screen 5: Entities Workspace Reconstruction

### Structure & Layout
1. **Breadcrumb Navigation**: Header bar with interactive breadcrumb (`Overview / Entities`) and total entities count badge.
2. **Summary Metrics Row**: 4 dynamic metric cards reflecting real investigation state:
   - Total Tracked Entities
   - Confirmed Matches (`CANONICAL / MATCH`)
   - Awaiting Review (`PROVISIONAL / REVIEW`)
   - Unresolved Mentions / Singletons
3. **Investigation Toolbar**:
   - Live search input filtering by canonical name, entity ID, and mention record IDs with instant clear (`×`) button.
   - Filter dropdowns for Entity Type (`PERSON`, `ORGANIZATION`, `LOCATION`) and Status.
   - Sort selector (`Name A–Z`, `Name Z–A`, `Most Mentions`, `Fewest Mentions`).
   - Dual-mode view toggle between **3-Card Grid** and **Detailed Table View**.
4. **3-Card-per-Row Grid (`.entity-card-v2`)**:
   - Header with deterministic SVG sticker avatar blob (using `window.SherlockStickers`), category badge (`PERSON`, `ORGANIZATION`, `LOCATION`), and status pill (`MATCH`, `REVIEW`, `CANONICAL`).
   - Body with mention count chips, cluster ID pill, and sample mention record tags.
   - Footer actions: "Graph View" (navigates directly to Screen 6 and centers the graph on this node) and "Inspect Entity →".
5. **Slide-Out Entity Inspection Drawer (`#entity-detail-panel`)**:
   - Drawer sheet with backdrop blur.
   - Large sticker avatar, canonical name, entity ID, type badge, and resolution status.
   - Section cards for source mentions (with click-to-copy code pills) and cluster metadata.
   - Action buttons: "Focus in Graph" and "Split Entity" (opens modal for splitting multi-record clusters).
6. **Empty State & Pagination**:
   - Illustrated empty state with detective cat vector graphics and reset filter button.
   - Pagination bar with dynamic page pills, prev/next controls, and summary counts.

---

## 3. Screen 6: Interactive Relationship Graph Workspace

### Structure & Layout
1. **Ivory Panel Canvas (`#graph-workspace-panel`)**:
   - High-contrast SVG graph canvas with floating controls bar, floating legend, and floating zoom cluster.
2. **Floating Controls Bar**:
   - Root Entity selector (defaults to overview or focuses on a specific entity).
   - Search depth input and max nodes limit.
   - Edge Type filter (`WORKS_FOR`, `OWNS`, `COMMUNICATED_WITH`, etc.) and Epistemic Tier filter (`ASSERTED`, `INFERRED`, `DISPUTED`, `RETRACTED`).
   - Fullscreen toggle button that expands the workspace panel into native fullscreen.
   - Tabular view toggle for inspecting edges in table format.
3. **SVG Node & Edge Presentation**:
   - **Nodes**: Circular nodes with type-colored rings (`#F5AE89` for Person, `#7A6EA6` for Organization, `#489B78` for Location). Inside each circle is a deterministic vector cat sticker clipped to a circular path. High-legibility labels and subtype captions appear below the node.
   - **Edges**: Directed lines with custom SVG marker arrows. Confirmed edges use solid `#191629` lines; disputed edges use dashed `#E89D42` lines with reverse arrows; inferred edges use dotted lines.
   - **Edge Pills**: Every link features a centered, rounded pill displaying the relationship predicate in uppercase.
4. **Interactive Navigation & Zoom**:
   - Mouse pan and drag with coordinate tracking.
   - Mouse wheel zoom with clamp constraints (`0.3x` to `3.5x`).
   - Floating zoom buttons: Zoom In (`+`), Zoom Out (`-`), Fit to View, and Reset (`1:1`).
5. **Floating Selection Inspector (`#graph-inspector`)**:
   - Clicking any node displays its full metadata, connection count, and shortcut to open its profile drawer.
   - Clicking any edge displays source, target, relationship type, epistemic tier, review status, and warning badge if contradicting claims exist.

---

## 4. Screen 7: Evidence & Claims Workspace

### Structure & Layout
1. **Summary Metrics Row**:
   - Total Documents Grounded
   - Extracted Text Spans
   - Structured Claims Formed
   - Contradictions & Allegation Disputes
2. **Evidence Timeline Track (`#evidence-timeline-track`)**:
   - Expanded 4–6 card horizontal track matching the primary dashboard reference:
     - Card avatar with mini sticker icon.
     - Step count and character offset span tags (`[start:end]`).
     - Polarity badge (`POSITIVE / SUPPORTING` in emerald `#E2F4EC`, `NEGATIVE / CONTRADICTING` in peach `#FFE4D6`).
     - Full italicized quote excerpt in callout styling.
     - Document source pill with icon.
     - Quick "Inspect" button.
3. **Search & Filter Toolbar**:
   - Real-time text span search with clear button.
   - Polarity filter, status filter, and document source dropdown.
   - View mode toggle between **Ivory Evidence Cards** and **Structured Claims Table**.
4. **Ivory Evidence Card Grid (`.evidence-card-v2`)**:
   - Header with document badge, evidence ID, polarity, and verification status.
   - Body with blockquote excerpt with peach accent border, character offset coordinates, and extraction method pill (`SPAN_MATCHER`, `DETERMINISTIC_RULE`).
   - "Inspect Grounding & Claims →" button.
5. **Evidence Grounding & Review Drawer (`#evidence-detail-panel`)**:
   - Large avatar, provenance coordinates, SHA-256 document hash, polarity, and extraction method.
   - Associated Structured Claims list with inline "Review Decision →" buttons triggering claim review modal (Approve, Disputed, Retracted).

---

## 5. Verification & Test Suite Results

| Test Module | Tests | Execution Time | Result |
| :--- | :--- | :--- | :--- |
| `tests/test_reconstructed_workspaces.py` | 4 tests (HTML, CSS, JS, API) | 0.15s | **100% Passed** |
| `tests/test_sticker_registry.py` | 5 tests (49 SVGs, FNV-1a hash, diversity) | 0.03s | **100% Passed** |
| `Full Repository Test Suite` | 375 tests | 4.52s | **370 Passed, 5 Skipped, 0 Failed** |

### Live Service Verification
- FastAPI Server: Running at `http://127.0.0.1:8000/`.
- UI Web Interface: `http://127.0.0.1:8000/` returns HTTP 200 with full reconstructed layout.
- Static Assets: `/static/app.css`, `/static/app.js`, `/static/stickers.js`, and SVG sticker files deliver HTTP 200.
- Live Case: `demo_benchmark_4495` provides 9 entities, 4 relationships, 5 claims, and 5 evidence items without fabrication.
