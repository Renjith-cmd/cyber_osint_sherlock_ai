# Sherlock AI — Visual Redesign Report: Reference Mockup & Detective Cat Design System

**Document Version:** `v2.0.0`  
**Date:** `2026-10-12`  
**Repository:** `/home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint`  
**Visual Reference:** Uploaded reference design mockup (`media_1791823633097.png`)  
**Design Palette:** Deep Navy-Purple (`#191629`, `#211D35`), Elevated Dark (`#29243B`), Warm Cream Surfaces (`#F7F4F0`, `#F6F0E9`), Soft Peach Accent (`#F5B18D`), Pill Geometry (`border-radius: 9999px`)  
**Status:** `COMPLETED & VERIFIED`

---

## 1. Files Changed & Added

| File Path | Action | Description |
| :--- | :--- | :--- |
| `src/ui/index.html` | **Redesigned** | Re-architected layout to mirror the reference mockup: organic top-left paw cutout tab, morning greeting header with search pill and primary peach action button, desktop sidebar with round Sherlock logo and peeking cat corner, 2-column dashboard layout (Tracked Entities, Recent Investigations, Relationship Graph preview, Evidence Timeline, Current Status, Sherlock AI assistant card, Quick Actions, and dark philosophy card), mobile bottom navigation bar, and integrated cat illustration empty states across all screens. |
| `src/ui/app.css` | **Redesigned** | Implemented complete reference mockup design tokens: `#191629` dark canvas, `#29243B` elevated containers, `#F7F4F0` warm cream surfaces, `#F5B18D` soft peach brand accent, pill buttons/inputs, 3-card Tracked Entities grid, Recent Investigations row styling, Relationship Graph preview canvas and legend, Evidence Timeline cards, status summary cards (MATCH, REVIEW, NON-MATCH), assistant hero card, quick actions rows, dark philosophy card, and responsive breakpoints (`max-width: 1180px`, `max-width: 860px`). |
| `src/ui/app.js` | **Enhanced** | Connected state management and API clients across all screens; added handlers for dashboard quick action buttons, case switching from recent list, global search trigger, dynamic population of Tracked Entities and Current Status metrics (`MATCH`, `REVIEW`, `NON-MATCH`) from live backend data, and Milestone 15 cross-document resolution, pairwise merges, non-match constraints, and cluster splits. |
| `src/ui/assets/cat_detective_hero.svg` | **Created** | High-detail vector SVG illustration of the Detective Cat wearing a houndstooth deerstalker cap, cape collar, and spectacles, holding a magnifying glass with the speech bubble: *"Small clues. Big answers."* |
| `src/ui/assets/cat_avatar_watson.svg` | **Created** | Black-and-white cartoon cat avatar wearing a white collar and peach bowtie (John Watson). |
| `src/ui/assets/cat_avatar_nexus.svg` | **Created** | Black-and-white cartoon cat avatar in a business suit and necktie (Nexus Holdings). |
| `src/ui/assets/cat_avatar_unknown.svg` | **Created** | Black-and-white mystery cartoon cat silhouette with a prominent question mark `?` between ears (Unknown Person). |
| `src/ui/assets/cat_avatar_apex.svg` | **Created** | Black-and-white cartoon cat avatar with a warm peach circular ring (Apex Corp). |
| `src/ui/assets/cat_avatar_vance.svg` | **Created** | Black-and-white cartoon cat avatar for individual records (Marcus Vance). |
| `src/ui/assets/cat_peek.svg` | **Created** | Bottom-left organic cream wave cutout with a curious detective cat peeking out with wide round eyes. |
| `src/ui/assets/cat_paw.svg` | **Created** | Clean vector paw print motif used inside the top-left organic cream tab cutout. |
| `src/ui/assets/cat_documents.svg` | **Created** | Detective cat wearing a deerstalker cap and holding an evidence folder, utilized in Document dropzones and empty states. |
| `src/ui/assets/cat_shield.svg` | **Created** | Detective cat with a star/checkmark shield for verified claims and protected records. |
| `src/ui/assets/cat_connections.svg` | **Created** | Connected group of mini detective cats linked by graph edges for Entity Resolution empty states and discovery. |
| `src/ui/assets/sherlock_logo.svg` | **Created** | Circular brand badge with detective cat wearing deerstalker hat and magnifying glass. |
| `artifacts/ui_redesign_report.md` | **Updated** | Comprehensive architectural and verification documentation for the redesign. |

---

## 2. Screens Redesigned

The application interface consists of 9 distinct screens accessible via the desktop sidebar, the floating mobile bottom pill bar, and dashboard quick links:

### Screen 1: Dashboard (`tab-dashboard`) — Exact Reference Mockup Layout
* **Top Header & Greeting:** Organic top-left cream tab cutout with cat paw print motif; greeting: *"Good morning, Ready to uncover the truth? Find connections. Verify claims. Build the bigger picture."*; global search pill (`Search entities, people, companies...`), notification bell, user avatar (`R`), active case dropdown, and primary peach button (`+ New investigation >`).
* **Tracked Entities Panel:** Warm cream container featuring 3 white rounded entity cards with cartoon cat avatars:
  1. *John Watson:* `MATCH` status pill, Watson cat avatar with bowtie, `Person` / `Individual` tags, `📄 3 source records`, circular arrow button.
  2. *Nexus Holdings:* `MATCH` status pill, Nexus cat avatar in suit & tie, `Organization` / `Company` tags, `📄 4 source records`, circular arrow button.
  3. *Unknown Person:* `REVIEW` status pill, mystery cat avatar with `?`, `Person` / `Individual` tags, `📄 2 source records`, circular arrow button.
* **Dual Middle Cards:**
  * *Recent Investigations (Left):* Rounded list items with document icons, session title, timestamp, and status badges (`MATCH`, `REVIEW`, `NON-MATCH`), dynamically bound to active SQLite investigations.
  * *Relationship Graph Preview (Right):* Clean SVG preview displaying entity nodes with cat avatars (John Watson, Nexus Holdings, Apex Corp, Riverside Holdings, Marcus Vance), labeled edges (`WORKS_FOR`, `OWNS`, `ASSOCIATED_WITH`, `REVIEW`), visual legend, and expand button `⤢` which links to the full Graph tab.
* **Bottom Row:**
  * *Evidence Timeline (Left):* 4 milestone cards showing chronological event progression (Document Ingested `memo_nexus_201.txt`, Claim Extracted, Contradictory Evidence with warning badge, and Status Updated).
  * *Current Status (Right):* 3 metric count cards for `MATCH` (green), `REVIEW` (peach), and `NON-MATCH` (slate) sourced from live backend data.
* **Right Rail Column:**
  * *Sherlock AI Assistant Card:* Detective Cat hero illustration with magnifying glass and speech bubble *"Small clues. Big answers."*, feature checklist.
  * *Quick Actions Panel:* Pill rows with chevrons to Upload Documents, View Graph, Browse Evidence, and Generate Report.
  * *Philosophy Card:* Elevated dark purple card (`#211D35`) with cat avatar, motto *"Evidence over assumptions. That's how we find the truth."*

### Screen 2: Investigations Management (`tab-investigations`)
* Full case management table with ID, description, backend mode, status, and document/entity counters.
* Real-time search filter and modal dialogs to create new investigations or load the synthetic demo case.

### Screen 3: Document Intake & Ingestion (`tab-documents`)
* Warm cream upload card featuring a friendly dropzone with the detective cat holding an evidence folder (`cat_documents.svg`).
* Drag-and-drop file support for `.txt`, `.json`, and `.pdf` with SHA-256 cryptographic verification.
* Split Document Viewer displaying verbatim source text on the left and grounded evidence spans with character offsets on the right.

### Screen 4: Cross-Document Entity Resolution (`tab-resolution`)
* Displays pairwise resolution proposals evaluated across documents with similarity scores, positive corroboration, and missing information.
* Prominently displays `MATCH`, `REVIEW`, and `NON-MATCH` status pills.
* Illustrated empty state featuring the connected detective cats motif (`cat_connections.svg`).
* Direct actions to approve merges, declare immutable non-match constraints, and inspect pairwise conflicts.

### Screen 5: Entity Profile & Explorer (`tab-entities`)
* Search and filter controls by entity name and type (`PERSON`, `ORGANIZATION`, `LOCATION`).
* Entity details sheet detailing canonical identifiers, member mentions, document offsets, and cluster splitting actions.

### Screen 6: Interactive Relationship Graph (`tab-graph`)
* Full SVG graph visualizer with radial/force layout, epistemic edge tiers (`ASSERTED`, `INFERRED`, `DISPUTED`, `RETRACTED`), node type color coding, and node/edge inspector drawer.
* Illustrated empty state featuring the detective cat with magnifying glass (`cat_detective_hero.svg`).
* Tabular fallback table for screen readers and keyboard accessibility.

### Screen 7: Claims & Evidence Registry (`tab-claims`)
* Complete table of extracted claims, verbatim citations, polarity, epistemic qualifiers (`ALLEGATION`, `NEGATED`), and human adjudication actions.
* Modal dialog to verify, dispute, or retract claims with auditable reviewer identity and justification.

### Screen 8: Investigation Report (`tab-report`)
* Dossier compiler presenting investigation summaries, document catalogs, resolved entities, and active disputes.
* One-click download buttons for raw Markdown (`.md`) and JSON (`.json`) dossiers.

### Screen 9: System Status & Settings (`tab-settings`)
* Live health probes inspecting `/api/v1/health` and `/api/v1/ready` reporting operational status, rule/ML backend mode, and SQLite database storage.

---

## 3. Cat Illustrations & Assets Added

All illustrations are 100% local, lightweight vector SVGs stored in `src/ui/assets/` to ensure offline capability and zero external dependencies:

1. `cat_detective_hero.svg` (5.3 KB): Detective Cat wearing houndstooth deerstalker cap, cape collar, and spectacles, holding a magnifying glass with the speech bubble *"Small clues. Big answers."*
2. `cat_avatar_watson.svg` (2.5 KB): Black-and-white cartoon cat avatar with white collar and peach bowtie (John Watson).
3. `cat_avatar_nexus.svg` (2.4 KB): Black-and-white cartoon cat avatar in business suit and necktie (Nexus Holdings).
4. `cat_avatar_unknown.svg` (2.3 KB): Black-and-white mystery cartoon cat silhouette with floating question mark `?` (Unknown Person).
5. `cat_avatar_apex.svg` (1.8 KB): Black-and-white cartoon cat avatar with peach circular border (Apex Corp).
6. `cat_avatar_vance.svg` (2.0 KB): Black-and-white cartoon cat avatar with sharp ears (Marcus Vance).
7. `cat_peek.svg` (2.9 KB): Bottom-left organic wave cutout with wide-eyed cat peeking out.
8. `cat_paw.svg` (1.1 KB): Black cat paw print motif on cream for the top-left cutout tab.
9. `cat_documents.svg` (2.8 KB): Detective cat holding an evidence folder for document intake.
10. `cat_shield.svg` (2.6 KB): Detective cat with a star/checkmark shield for verified claims.
11. `cat_connections.svg` (3.0 KB): Connected group of mini detective cats linked by graph edges.
12. `sherlock_logo.svg` (1.6 KB): Circular brand badge with detective cat wearing deerstalker hat and magnifying glass.

---

## 4. Responsive & Accessibility Checks

* **Desktop Layout (Width > 1180px):** Full 2-column dashboard layout with Left Main panel (Tracked Entities, Recent Investigations, Relationship Graph preview, Evidence Timeline, Current Status) and Right Rail (Sherlock Assistant Card, Quick Actions, Philosophy Card).
* **Tablet Layout (860px < Width <= 1180px):** Main column expands to full width; right rail wraps into a 2-column grid below.
* **Mobile Layout (Width <= 860px):**
  * Sidebar transitions into a floating bottom pill navigation bar (`.mobile-bottom-pill-bar`) for thumb-friendly navigation.
  * Top greeting block stacks gracefully; paw tab hides to maximize viewport width.
  * Tracked entities grid, recent investigations, graph preview, and timeline cards stack vertically with clean spacing.
* **Accessibility Compliance:**
  * Strict contrast ratios: High-contrast warm off-white (`#FAF8F5`) on dark navy backgrounds (`#191629`) and deep plum (`#191629`) on warm cream cards (`#F7F4F0`).
  * Visible `:focus-visible` focus outlines with soft peach border glow (`--border-focus: #F5B18D`).
  * All interactive buttons, inputs, and SVG icons include descriptive `aria-label`, `role`, and `title` attributes.
  * Graph view provides an accessible Tabular Fallback toggle for screen readers and keyboard users.
  * Reduced-motion query (`@media (prefers-reduced-motion: reduce)`) disables heavy transitions.

---

## 5. Verification Commands & Test Results

### 1. Static Asset HTTP Status Verification
```bash
for asset in app.css app.js assets/cat_detective_hero.svg assets/cat_avatar_watson.svg \
  assets/cat_avatar_nexus.svg assets/cat_avatar_unknown.svg assets/cat_avatar_apex.svg \
  assets/cat_avatar_vance.svg assets/cat_peek.svg assets/cat_paw.svg assets/cat_documents.svg \
  assets/cat_shield.svg assets/cat_connections.svg assets/sherlock_logo.svg; do
  curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/static/$asset
done
```
* **Result:** All 14 static assets returned `HTTP 200`.

### 2. Code Compilation & Formatting Audits
```bash
.venv/bin/python -m compileall -q src tests scripts
git diff --check
```
* **Result:** Exit code `0` (Zero syntax errors, zero trailing whitespace or formatting defects).

### 3. REST API & UI Serving Integration Suite
```bash
.venv/bin/pytest tests/test_milestone_13_api.py -v
```
* **Result:** `15 passed in 0.69s` (including static UI serving test).

### 4. Full Regression Suite in Standard Environment (`.venv`)
```bash
.venv/bin/pytest tests/
```
* **Result:** `361 passed, 5 skipped, 4 warnings in 4.38s`.

---

## 6. Known Boundaries & Limitations

1. **Epistemic Integrity:** All cartoon cat illustrations are strictly decorative motifs and avatars; they do not replace graph relationship edges, obscure claim confidence scores, or compromise the epistemic seriousness of evidence provenance.
2. **Offline Local Execution:** The application runs 100% offline using local vector SVGs without external image CDNs or remote dependencies.
3. **Single-Operator Workspace:** The application operates as a local single-analyst OSINT research engine without multi-tenant authentication.
4. **Deterministic Storage:** SQLite local persistence remains active and durable across sessions.
