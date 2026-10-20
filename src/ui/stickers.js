// =============================================================================
// Sherlock AI — Reusable Entity Sticker & Avatar Registry
// Contains 44 original vector stickers for scalable, deterministic avatar assignment.
// =============================================================================

(function() {
  "use strict";

  const STICKER_REGISTRY = [
  {
    "id": "cat_detective_deerstalker",
    "name": "Sherlock Deerstalker Cat",
    "types": [
      "PERSON"
    ],
    "category": "detective",
    "label": "Detective cat wearing houndstooth deerstalker cap",
    "path": "/static/assets/stickers/cat_detective_deerstalker.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 24 112 Q 30 88, 60 84 Q 90 88, 96 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"36,54 26,24 50,40\" fill=\"#191629\"/>\n  <polygon points=\"84,54 94,24 70,40\" fill=\"#191629\"/>\n  <path d=\"M 38 52 Q 60 22, 82 52 Z\" fill=\"#E8DEC8\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <path d=\"M 30 52 Q 60 46, 90 52 Q 60 58, 30 52 Z\" fill=\"#E8DEC8\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <circle cx=\"60\" cy=\"22\" r=\"4\" fill=\"#F5B18D\"/>\n  <ellipse cx=\"60\" cy=\"66\" rx=\"30\" ry=\"24\" fill=\"#191629\"/>\n  <ellipse cx=\"50\" cy=\"65\" rx=\"6\" ry=\"8\" fill=\"#FFFFFF\"/>\n  <circle cx=\"51\" cy=\"65\" r=\"4\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"63\" r=\"1.8\" fill=\"#FFFFFF\"/>\n  <ellipse cx=\"70\" cy=\"65\" rx=\"6\" ry=\"8\" fill=\"#FFFFFF\"/>\n  <circle cx=\"69\" cy=\"65\" r=\"4\" fill=\"#191629\"/>\n  <circle cx=\"67\" cy=\"63\" r=\"1.8\" fill=\"#FFFFFF\"/>\n  <polygon points=\"60,73 57,70 63,70\" fill=\"#F5B18D\"/>\n  <path d=\"M 60 74 Q 57 78, 54 76\" stroke=\"#FFFFFF\" stroke-width=\"1.5\" fill=\"none\"/>\n  <path d=\"M 60 74 Q 63 78, 66 76\" stroke=\"#FFFFFF\" stroke-width=\"1.5\" fill=\"none\"/>\n</svg>"
  },
  {
    "id": "cat_detective_magnifier",
    "name": "Magnifier Detective Cat",
    "types": [
      "PERSON"
    ],
    "category": "detective",
    "label": "Detective cat examining evidence with a magnifying glass",
    "path": "/static/assets/stickers/cat_detective_magnifier.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 35 88, 60 85 Q 85 88, 92 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"38,58 28,28 52,44\" fill=\"#191629\"/>\n  <polygon points=\"82,58 92,28 68,44\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"68\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"67\" r=\"7\" fill=\"#FFFFFF\"/>\n  <circle cx=\"50\" cy=\"67\" r=\"4.5\" fill=\"#191629\"/>\n  <circle cx=\"48\" cy=\"65\" r=\"2\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"67\" r=\"7\" fill=\"#FFFFFF\"/>\n  <circle cx=\"70\" cy=\"67\" r=\"4.5\" fill=\"#191629\"/>\n  <circle cx=\"68\" cy=\"65\" r=\"2\" fill=\"#FFFFFF\"/>\n  <polygon points=\"60,74 57,71 63,71\" fill=\"#F5B18D\"/>\n  <circle cx=\"80\" cy=\"80\" r=\"16\" fill=\"none\" stroke=\"#191629\" stroke-width=\"3\"/>\n  <circle cx=\"80\" cy=\"80\" r=\"14\" fill=\"rgba(245, 177, 141, 0.25)\"/>\n  <line x1=\"91\" y1=\"91\" x2=\"105\" y2=\"105\" stroke=\"#191629\" stroke-width=\"4.5\" stroke-linecap=\"round\"/>\n</svg>"
  },
  {
    "id": "cat_detective_fedora",
    "name": "Noir Fedora Cat",
    "types": [
      "PERSON"
    ],
    "category": "detective",
    "label": "Noir style detective cat in fedora hat",
    "path": "/static/assets/stickers/cat_detective_fedora.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 26 112 Q 32 88, 60 84 Q 88 88, 94 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"36,54 28,26 48,42\" fill=\"#191629\"/>\n  <polygon points=\"84,54 92,26 72,42\" fill=\"#191629\"/>\n  <path d=\"M 38 48 C 38 32, 50 26, 60 26 C 70 26, 82 32, 82 48 Z\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <path d=\"M 38 48 L 82 48\" stroke=\"#F5B18D\" stroke-width=\"3\"/>\n  <path d=\"M 28 48 Q 60 42, 92 48 Q 60 56, 28 48 Z\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <ellipse cx=\"60\" cy=\"68\" rx=\"28\" ry=\"22\" fill=\"#191629\"/>\n  <circle cx=\"50\" cy=\"67\" r=\"5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"70\" cy=\"67\" r=\"5\" fill=\"#FFFFFF\"/>\n  <polygon points=\"60,74 57,71 63,71\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_detective_trenchcoat",
    "name": "Trenchcoat Detective Cat",
    "types": [
      "PERSON"
    ],
    "category": "detective",
    "label": "Investigator cat wearing classic trenchcoat with lapels",
    "path": "/static/assets/stickers/cat_detective_trenchcoat.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 24 112 Q 30 84, 60 80 Q 90 84, 96 112 Z\" fill=\"#E8DEC8\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <path d=\"M 46 80 L 60 100 L 74 80\" fill=\"none\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <circle cx=\"60\" cy=\"104\" r=\"3\" fill=\"#F5B18D\"/>\n  <polygon points=\"38,56 26,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 94,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"64\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"63\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"50\" cy=\"63\" r=\"3.5\" fill=\"#191629\"/>\n  <circle cx=\"71\" cy=\"63\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"70\" cy=\"63\" r=\"3.5\" fill=\"#191629\"/>\n  <polygon points=\"60,70 57,67 63,67\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_detective_notebook",
    "name": "Field Notebook Cat",
    "types": [
      "PERSON"
    ],
    "category": "detective",
    "label": "Detective cat recording forensic case notes",
    "path": "/static/assets/stickers/cat_detective_notebook.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 35 88, 60 85 Q 85 88, 92 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"50\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"51\" cy=\"64\" r=\"3.5\" fill=\"#191629\"/>\n  <circle cx=\"70\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"69\" cy=\"64\" r=\"3.5\" fill=\"#191629\"/>\n  <rect x=\"70\" y=\"80\" width=\"26\" height=\"30\" rx=\"3\" fill=\"#FFFFFF\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <line x1=\"75\" y1=\"88\" x2=\"91\" y2=\"88\" stroke=\"#F5B18D\" stroke-width=\"2\"/>\n  <line x1=\"75\" y1=\"94\" x2=\"88\" y2=\"94\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n  <line x1=\"75\" y1=\"100\" x2=\"85\" y2=\"100\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n</svg>"
  },
  {
    "id": "cat_detective_flashlight",
    "name": "Searchlight Cat",
    "types": [
      "PERSON"
    ],
    "category": "detective",
    "label": "Detective cat searching with focused beam flashlight",
    "path": "/static/assets/stickers/cat_detective_flashlight.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 35 88, 60 85 Q 85 88, 92 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <path d=\"M 80 88 L 110 74 L 110 102 Z\" fill=\"rgba(245, 177, 141, 0.4)\"/>\n  <rect x=\"70\" y=\"84\" width=\"16\" height=\"8\" rx=\"2\" fill=\"#191629\"/>\n  <circle cx=\"86\" cy=\"88\" r=\"4\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_detective_badge",
    "name": "Special Agent Cat",
    "types": [
      "PERSON"
    ],
    "category": "detective",
    "label": "Investigator cat bearing official gold agency badge",
    "path": "/static/assets/stickers/cat_detective_badge.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 26 112 Q 34 86, 60 84 Q 86 86, 94 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"60,92 63,98 70,98 64,102 66,108 60,104 54,108 56,102 50,98 57,98\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"1\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"64\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"63\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"63\" r=\"6\" fill=\"#FFFFFF\"/>\n  <polygon points=\"60,70 57,67 63,67\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_detective_whiskers",
    "name": "Alert Whiskers Cat",
    "types": [
      "PERSON"
    ],
    "category": "detective",
    "label": "Keen detective cat with sensitive sensory whiskers",
    "path": "/static/assets/stickers/cat_detective_whiskers.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 35 88, 60 85 Q 85 88, 92 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"36,54 26,22 52,40\" fill=\"#191629\"/>\n  <polygon points=\"84,54 94,22 68,40\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"30\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"63\" r=\"6.5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"63\" r=\"6.5\" fill=\"#FFFFFF\"/>\n  <polygon points=\"60,70 57,67 63,67\" fill=\"#F5B18D\"/>\n  <line x1=\"38\" y1=\"68\" x2=\"16\" y2=\"65\" stroke=\"#FFFFFF\" stroke-width=\"2\" stroke-linecap=\"round\"/>\n  <line x1=\"38\" y1=\"74\" x2=\"14\" y2=\"76\" stroke=\"#FFFFFF\" stroke-width=\"2\" stroke-linecap=\"round\"/>\n  <line x1=\"82\" y1=\"68\" x2=\"104\" y2=\"65\" stroke=\"#FFFFFF\" stroke-width=\"2\" stroke-linecap=\"round\"/>\n  <line x1=\"82\" y1=\"74\" x2=\"106\" y2=\"76\" stroke=\"#FFFFFF\" stroke-width=\"2\" stroke-linecap=\"round\"/>\n</svg>"
  },
  {
    "id": "cat_detective_pipe",
    "name": "Victorian Pipe Cat",
    "types": [
      "PERSON"
    ],
    "category": "detective",
    "label": "Gentleman investigator cat contemplating clues",
    "path": "/static/assets/stickers/cat_detective_pipe.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 35 88, 60 85 Q 85 88, 92 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"64\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"63\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"63\" r=\"6\" fill=\"#FFFFFF\"/>\n  <path d=\"M 64 74 Q 72 78, 80 72\" stroke=\"#E8DEC8\" stroke-width=\"3\" fill=\"none\"/>\n  <rect x=\"78\" y=\"66\" width=\"8\" height=\"10\" rx=\"2\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n  <circle cx=\"82\" cy=\"60\" r=\"2.5\" fill=\"#E8DEC8\" opacity=\"0.6\"/>\n</svg>"
  },
  {
    "id": "cat_detective_cloak",
    "name": "Inverness Cloak Cat",
    "types": [
      "PERSON"
    ],
    "category": "detective",
    "label": "Detective cat wrapped in Victorian Inverness cape",
    "path": "/static/assets/stickers/cat_detective_cloak.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 20 112 Q 30 78, 60 76 Q 90 78, 100 112 Z\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 40 78 L 60 102 L 80 78\" stroke=\"#F5B18D\" stroke-width=\"2\" fill=\"none\"/>\n  <polygon points=\"38,54 26,24 52,40\" fill=\"#191629\"/>\n  <polygon points=\"82,54 94,24 68,40\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"62\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"61\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"61\" r=\"6\" fill=\"#FFFFFF\"/>\n</svg>"
  },
  {
    "id": "cat_analyst_spectacles",
    "name": "Spectacles Analyst Cat",
    "types": [
      "PERSON"
    ],
    "category": "analyst",
    "label": "Intel analyst cat wearing reading glasses",
    "path": "/static/assets/stickers/cat_analyst_spectacles.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 35 88, 60 85 Q 85 88, 92 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <!-- Round Spectacles -->\n  <circle cx=\"48\" cy=\"64\" r=\"11\" fill=\"none\" stroke=\"#F5B18D\" stroke-width=\"2.5\"/>\n  <circle cx=\"48\" cy=\"64\" r=\"5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"72\" cy=\"64\" r=\"11\" fill=\"none\" stroke=\"#F5B18D\" stroke-width=\"2.5\"/>\n  <circle cx=\"72\" cy=\"64\" r=\"5\" fill=\"#FFFFFF\"/>\n  <line x1=\"59\" y1=\"64\" x2=\"61\" y2=\"64\" stroke=\"#F5B18D\" stroke-width=\"3\"/>\n  <polygon points=\"60,72 57,69 63,69\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_analyst_headphones",
    "name": "Audio Intel Analyst Cat",
    "types": [
      "PERSON"
    ],
    "category": "analyst",
    "label": "Surveillance cat wearing communication headphones",
    "path": "/static/assets/stickers/cat_analyst_headphones.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 35 88, 60 85 Q 85 88, 92 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <path d=\"M 26 62 C 26 30, 94 30, 94 62\" stroke=\"#F5B18D\" stroke-width=\"3.5\" fill=\"none\"/>\n  <rect x=\"22\" y=\"58\" width=\"9\" height=\"18\" rx=\"4\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n  <rect x=\"89\" y=\"58\" width=\"9\" height=\"18\" rx=\"4\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n  <circle cx=\"49\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n</svg>"
  },
  {
    "id": "cat_analyst_coffee",
    "name": "Midnight Coffee Cat",
    "types": [
      "PERSON"
    ],
    "category": "analyst",
    "label": "Investigator cat working late with hot coffee",
    "path": "/static/assets/stickers/cat_analyst_coffee.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 35 88, 60 85 Q 85 88, 92 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <!-- Coffee Mug -->\n  <rect x=\"72\" y=\"86\" width=\"18\" height=\"18\" rx=\"3\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"1.8\"/>\n  <path d=\"M 90 90 Q 96 95, 90 100\" stroke=\"#191629\" stroke-width=\"2\" fill=\"none\"/>\n  <path d=\"M 76 82 Q 78 78, 80 82\" stroke=\"#E8DEC8\" stroke-width=\"1.5\" fill=\"none\"/>\n</svg>"
  },
  {
    "id": "cat_analyst_charts",
    "name": "Graph Metrics Cat",
    "types": [
      "PERSON"
    ],
    "category": "analyst",
    "label": "Entity resolution data analyst charting relationships",
    "path": "/static/assets/stickers/cat_analyst_charts.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 35 88, 60 85 Q 85 88, 92 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"62\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"61\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"61\" r=\"6\" fill=\"#FFFFFF\"/>\n  <rect x=\"36\" y=\"88\" width=\"48\" height=\"22\" rx=\"3\" fill=\"#FFFFFF\" stroke=\"#191629\" stroke-width=\"1.8\"/>\n  <rect x=\"42\" y=\"98\" width=\"6\" height=\"8\" fill=\"#191629\"/>\n  <rect x=\"52\" y=\"94\" width=\"6\" height=\"12\" fill=\"#F5B18D\"/>\n  <rect x=\"62\" y=\"91\" width=\"6\" height=\"15\" fill=\"#3EAE7C\"/>\n  <rect x=\"72\" y=\"96\" width=\"6\" height=\"10\" fill=\"#191629\"/>\n</svg>"
  },
  {
    "id": "cat_analyst_laptop",
    "name": "Cyber OSINT Cat",
    "types": [
      "PERSON"
    ],
    "category": "analyst",
    "label": "Open source intelligence cat analyst at terminal",
    "path": "/static/assets/stickers/cat_analyst_laptop.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"38,54 28,24 52,40\" fill=\"#191629\"/>\n  <polygon points=\"82,54 92,24 68,40\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"60\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"59\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"59\" r=\"6\" fill=\"#FFFFFF\"/>\n  <!-- Laptop -->\n  <polygon points=\"35,94 85,94 78,82 42,82\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"1.8\"/>\n  <rect x=\"30\" y=\"94\" width=\"60\" height=\"6\" rx=\"2\" fill=\"#E8DEC8\" stroke=\"#191629\" stroke-width=\"1.8\"/>\n  <circle cx=\"60\" cy=\"88\" r=\"3\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_analyst_bowtie",
    "name": "Watson Bowtie Cat",
    "types": [
      "PERSON"
    ],
    "category": "analyst",
    "label": "Gentleman analytical cat in bowtie",
    "path": "/static/assets/stickers/cat_analyst_bowtie.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 35 88, 60 85 Q 85 88, 92 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"50,92 60,96 50,100\" fill=\"#F5B18D\"/>\n  <polygon points=\"70,92 60,96 70,100\" fill=\"#F5B18D\"/>\n  <circle cx=\"60\" cy=\"96\" r=\"2.5\" fill=\"#191629\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <polygon points=\"60,71 57,68 63,68\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_analyst_magnifier_eye",
    "name": "Micro-Inspection Cat",
    "types": [
      "PERSON"
    ],
    "category": "analyst",
    "label": "Analyst cat examining microscopic evidence",
    "path": "/static/assets/stickers/cat_analyst_magnifier_eye.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"64\" r=\"5\" fill=\"#FFFFFF\"/>\n  <!-- Magnified Left Eye -->\n  <circle cx=\"71\" cy=\"64\" r=\"14\" fill=\"#FFFFFF\" stroke=\"#F5B18D\" stroke-width=\"3\"/>\n  <circle cx=\"71\" cy=\"64\" r=\"8\" fill=\"#191629\"/>\n  <circle cx=\"68\" cy=\"61\" r=\"3\" fill=\"#FFFFFF\"/>\n</svg>"
  },
  {
    "id": "cat_analyst_folder",
    "name": "Dossier Archivist Cat",
    "types": [
      "PERSON"
    ],
    "category": "analyst",
    "label": "Forensic records archivist carrying folder",
    "path": "/static/assets/stickers/cat_analyst_folder.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"64\" r=\"6\" fill=\"#FFFFFF\"/>\n  <path d=\"M 40 86 L 56 86 L 62 90 L 80 90 L 80 110 L 40 110 Z\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"2\"/>\n</svg>"
  },
  {
    "id": "cat_curious_tilted",
    "name": "Inquisitive Tilted Cat",
    "types": [
      "PERSON"
    ],
    "category": "curious",
    "label": "Curious cat tilting head at investigative paradox",
    "path": "/static/assets/stickers/cat_curious_tilted.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <g transform=\"rotate(12 60 60)\">\n    <polygon points=\"38,56 26,26 52,42\" fill=\"#191629\"/>\n    <polygon points=\"82,56 94,26 68,42\" fill=\"#191629\"/>\n    <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n    <circle cx=\"48\" cy=\"63\" r=\"7\" fill=\"#FFFFFF\"/>\n    <circle cx=\"72\" cy=\"63\" r=\"7\" fill=\"#FFFFFF\"/>\n    <polygon points=\"60,71 57,68 63,68\" fill=\"#F5B18D\"/>\n  </g>\n</svg>"
  },
  {
    "id": "cat_curious_wide_eyes",
    "name": "Wide-Eyed Discovery Cat",
    "types": [
      "PERSON"
    ],
    "category": "curious",
    "label": "Astonished cat uncovering crucial evidence lead",
    "path": "/static/assets/stickers/cat_curious_wide_eyes.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"36,52 24,20 50,38\" fill=\"#191629\"/>\n  <polygon points=\"84,52 96,20 70,38\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"30\" ry=\"26\" fill=\"#191629\"/>\n  <!-- Giant anime round eyes -->\n  <circle cx=\"46\" cy=\"62\" r=\"11\" fill=\"#FFFFFF\"/>\n  <circle cx=\"47\" cy=\"62\" r=\"8\" fill=\"#191629\"/>\n  <circle cx=\"44\" cy=\"59\" r=\"3.5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"74\" cy=\"62\" r=\"11\" fill=\"#FFFFFF\"/>\n  <circle cx=\"73\" cy=\"62\" r=\"8\" fill=\"#191629\"/>\n  <circle cx=\"70\" cy=\"59\" r=\"3.5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"60\" cy=\"74\" r=\"2.5\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_curious_peeking",
    "name": "Edge Peeking Cat",
    "types": [
      "PERSON"
    ],
    "category": "curious",
    "label": "Cat peering discreetly around corner",
    "path": "/static/assets/stickers/cat_curious_peeking.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 10 70 Q 60 60, 110 70 L 110 110 L 10 110 Z\" fill=\"#29243B\"/>\n  <polygon points=\"44,56 38,28 58,44\" fill=\"#191629\"/>\n  <polygon points=\"76,56 82,28 62,44\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"60\" rx=\"26\" ry=\"20\" fill=\"#191629\"/>\n  <circle cx=\"50\" cy=\"58\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"70\" cy=\"58\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"40\" cy=\"74\" r=\"5\" fill=\"#191629\"/>\n  <circle cx=\"80\" cy=\"74\" r=\"5\" fill=\"#191629\"/>\n</svg>"
  },
  {
    "id": "cat_suspicious_squint",
    "name": "Skeptical Squint Cat",
    "types": [
      "PERSON"
    ],
    "category": "curious",
    "label": "Investigator cat scrutinizing conflicting testimony",
    "path": "/static/assets/stickers/cat_suspicious_squint.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <line x1=\"42\" y1=\"63\" x2=\"56\" y2=\"63\" stroke=\"#FFFFFF\" stroke-width=\"3\" stroke-linecap=\"round\"/>\n  <line x1=\"64\" y1=\"63\" x2=\"78\" y2=\"63\" stroke=\"#FFFFFF\" stroke-width=\"3\" stroke-linecap=\"round\"/>\n  <polygon points=\"60,71 57,68 63,68\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_suspicious_side_eye",
    "name": "Side-Eye Doubt Cat",
    "types": [
      "PERSON"
    ],
    "category": "curious",
    "label": "Cat delivering suspicious side-eye glance",
    "path": "/static/assets/stickers/cat_suspicious_side_eye.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <ellipse cx=\"49\" cy=\"64\" rx=\"7\" ry=\"5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"44\" cy=\"64\" r=\"3.5\" fill=\"#191629\"/>\n  <ellipse cx=\"71\" cy=\"64\" rx=\"7\" ry=\"5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"66\" cy=\"64\" r=\"3.5\" fill=\"#191629\"/>\n</svg>"
  },
  {
    "id": "cat_sneaky_paws",
    "name": "Stealth Paws Cat",
    "types": [
      "PERSON"
    ],
    "category": "curious",
    "label": "Stealth operative cat moving silently",
    "path": "/static/assets/stickers/cat_sneaky_paws.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"62\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"61\" r=\"5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"61\" r=\"5\" fill=\"#FFFFFF\"/>\n  <ellipse cx=\"45\" cy=\"94\" rx=\"10\" ry=\"7\" fill=\"#191629\"/>\n  <circle cx=\"42\" cy=\"91\" r=\"2\" fill=\"#F5B18D\"/>\n  <circle cx=\"46\" cy=\"90\" r=\"2\" fill=\"#F5B18D\"/>\n  <circle cx=\"50\" cy=\"92\" r=\"2\" fill=\"#F5B18D\"/>\n  <ellipse cx=\"75\" cy=\"94\" rx=\"10\" ry=\"7\" fill=\"#191629\"/>\n  <circle cx=\"72\" cy=\"91\" r=\"2\" fill=\"#F5B18D\"/>\n  <circle cx=\"76\" cy=\"90\" r=\"2\" fill=\"#F5B18D\"/>\n  <circle cx=\"80\" cy=\"92\" r=\"2\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_alert_ears",
    "name": "Acoustic Alert Cat",
    "types": [
      "PERSON"
    ],
    "category": "curious",
    "label": "Counter-surveillance cat with tall perked ears",
    "path": "/static/assets/stickers/cat_alert_ears.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"36,60 22,14 54,38\" fill=\"#191629\"/>\n  <polygon points=\"36,54 26,22 48,38\" fill=\"#F5B18D\"/>\n  <polygon points=\"84,60 98,14 66,38\" fill=\"#191629\"/>\n  <polygon points=\"84,54 94,22 72,38\" fill=\"#F5B18D\"/>\n  <ellipse cx=\"60\" cy=\"68\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"67\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"67\" r=\"6\" fill=\"#FFFFFF\"/>\n</svg>"
  },
  {
    "id": "cat_mystery_question",
    "name": "Unresolved Identity Mystery Cat",
    "types": [
      "UNKNOWN",
      "PERSON"
    ],
    "category": "mystery",
    "label": "Mysterious identity cat with glowing question mark",
    "path": "/static/assets/stickers/cat_mystery_question.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <text x=\"60\" y=\"32\" font-family=\"'Plus Jakarta Sans', sans-serif\" font-size=\"28\" font-weight=\"800\" fill=\"#F5B18D\" text-anchor=\"middle\">?</text>\n  <polygon points=\"38,64 28,34 52,50\" fill=\"#191629\"/>\n  <polygon points=\"82,64 92,34 68,50\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"72\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"71\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"50\" cy=\"71\" r=\"3.5\" fill=\"#191629\"/>\n  <circle cx=\"71\" cy=\"71\" r=\"6\" fill=\"#FFFFFF\"/>\n  <circle cx=\"70\" cy=\"71\" r=\"3.5\" fill=\"#191629\"/>\n  <circle cx=\"60\" cy=\"78\" r=\"2.5\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_mystery_hoodie",
    "name": "Anonymous Hooded Cat",
    "types": [
      "UNKNOWN",
      "PERSON"
    ],
    "category": "mystery",
    "label": "Anonymous figure cat wearing concealment hoodie",
    "path": "/static/assets/stickers/cat_mystery_hoodie.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 112 Q 32 60, 60 50 Q 88 60, 92 112 Z\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <circle cx=\"60\" cy=\"74\" r=\"20\" fill=\"#191629\"/>\n  <circle cx=\"53\" cy=\"74\" r=\"4\" fill=\"#F5B18D\"/>\n  <circle cx=\"67\" cy=\"74\" r=\"4\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_mystery_shadow",
    "name": "Shadow Silhouette Cat",
    "types": [
      "UNKNOWN",
      "PERSON"
    ],
    "category": "mystery",
    "label": "Unconfirmed entity silhouette hidden in shadow",
    "path": "/static/assets/stickers/cat_mystery_shadow.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <ellipse cx=\"49\" cy=\"64\" rx=\"4\" ry=\"6\" fill=\"#F5B18D\"/>\n  <ellipse cx=\"71\" cy=\"64\" rx=\"4\" ry=\"6\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "cat_disputed_warning",
    "name": "Disputed Claim Alert Cat",
    "types": [
      "UNKNOWN",
      "PERSON"
    ],
    "category": "mystery",
    "label": "Investigative record under active dispute or conflict",
    "path": "/static/assets/stickers/cat_disputed_warning.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#E89D42\" stroke-width=\"3\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"64\" r=\"5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"64\" r=\"5\" fill=\"#FFFFFF\"/>\n  <!-- Warning Triangle -->\n  <polygon points=\"82,78 98,106 66,106\" fill=\"#E89D42\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <text x=\"82\" y=\"103\" font-family=\"'Plus Jakarta Sans', sans-serif\" font-size=\"14\" font-weight=\"900\" fill=\"#191629\" text-anchor=\"middle\">!</text>\n</svg>"
  },
  {
    "id": "cat_verified_shield",
    "name": "Verified Shield Cat",
    "types": [
      "PERSON",
      "UNKNOWN"
    ],
    "category": "mystery",
    "label": "Corroborated identity record with verified badge",
    "path": "/static/assets/stickers/cat_verified_shield.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#3EAE7C\" stroke-width=\"3\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"64\" r=\"5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"64\" r=\"5\" fill=\"#FFFFFF\"/>\n  <path d=\"M 72 80 L 92 80 C 92 94, 82 104, 82 108 C 82 104, 72 94, 72 80 Z\" fill=\"#3EAE7C\" stroke=\"#191629\" stroke-width=\"1.8\"/>\n  <path d=\"M 77 92 L 81 96 L 88 88\" stroke=\"#FFFFFF\" stroke-width=\"2.5\" fill=\"none\" stroke-linecap=\"round\"/>\n</svg>"
  },
  {
    "id": "cat_encrypted_key",
    "name": "Cryptographic Key Cat",
    "types": [
      "UNKNOWN",
      "PERSON"
    ],
    "category": "mystery",
    "label": "Protected record secured with cryptographic provenance",
    "path": "/static/assets/stickers/cat_encrypted_key.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"38,56 28,26 52,42\" fill=\"#191629\"/>\n  <polygon points=\"82,56 92,26 68,42\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"65\" rx=\"28\" ry=\"24\" fill=\"#191629\"/>\n  <circle cx=\"49\" cy=\"64\" r=\"5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"71\" cy=\"64\" r=\"5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"78\" cy=\"94\" r=\"6\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <line x1=\"84\" y1=\"94\" x2=\"98\" y2=\"94\" stroke=\"#191629\" stroke-width=\"3\"/>\n  <line x1=\"94\" y1=\"94\" x2=\"94\" y2=\"99\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n</svg>"
  },
  {
    "id": "org_corporate_suit",
    "name": "Executive Corporate Cat",
    "types": [
      "ORGANIZATION"
    ],
    "category": "corporate",
    "label": "Corporate organization entity in business suit and tie",
    "path": "/static/assets/stickers/org_corporate_suit.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 24 112 Q 32 86, 60 84 Q 88 86, 96 112 Z\" fill=\"#191629\"/>\n  <polygon points=\"50,84 60,104 70,84\" fill=\"#FFFFFF\"/>\n  <polygon points=\"57,90 63,90 61,110 59,110\" fill=\"#191629\"/>\n  <polygon points=\"38,54 28,24 52,40\" fill=\"#191629\"/>\n  <polygon points=\"82,54 92,24 68,40\" fill=\"#191629\"/>\n  <ellipse cx=\"60\" cy=\"62\" rx=\"28\" ry=\"22\" fill=\"#191629\"/>\n  <circle cx=\"50\" cy=\"61\" r=\"5\" fill=\"#FFFFFF\"/>\n  <circle cx=\"70\" cy=\"61\" r=\"5\" fill=\"#FFFFFF\"/>\n  <polygon points=\"60,67 57,64 63,64\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "org_briefcase",
    "name": "Briefcase Holding Enterprise",
    "types": [
      "ORGANIZATION"
    ],
    "category": "corporate",
    "label": "Corporate holding company with business briefcase",
    "path": "/static/assets/stickers/org_briefcase.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <rect x=\"32\" y=\"44\" width=\"56\" height=\"42\" rx=\"5\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 48 44 L 48 34 C 48 30, 72 30, 72 34 L 72 44\" stroke=\"#F5B18D\" stroke-width=\"3\" fill=\"none\"/>\n  <rect x=\"56\" y=\"60\" width=\"8\" height=\"10\" rx=\"1\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n  <line x1=\"32\" y1=\"64\" x2=\"88\" y2=\"64\" stroke=\"#191629\" stroke-width=\"2\"/>\n</svg>"
  },
  {
    "id": "org_handshake",
    "name": "Partnership Handshake",
    "types": [
      "ORGANIZATION"
    ],
    "category": "corporate",
    "label": "Contractual commercial joint venture partnership",
    "path": "/static/assets/stickers/org_handshake.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <circle cx=\"60\" cy=\"60\" r=\"34\" fill=\"#FFFFFF\" stroke=\"#F5B18D\" stroke-width=\"2\"/>\n  <path d=\"M 36 60 Q 52 50, 60 62 Q 68 74, 84 60\" stroke=\"#191629\" stroke-width=\"4.5\" stroke-linecap=\"round\" fill=\"none\"/>\n  <circle cx=\"56\" cy=\"56\" r=\"4\" fill=\"#F5B18D\"/>\n  <circle cx=\"64\" cy=\"66\" r=\"4\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "org_skyscraper_tower",
    "name": "Headquarters Skyscraper Tower",
    "types": [
      "ORGANIZATION"
    ],
    "category": "corporate",
    "label": "Major multinational headquarters skyscraper",
    "path": "/static/assets/stickers/org_skyscraper_tower.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <rect x=\"42\" y=\"24\" width=\"36\" height=\"74\" rx=\"3\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <line x1=\"60\" y1=\"12\" x2=\"60\" y2=\"24\" stroke=\"#F5B18D\" stroke-width=\"3\"/>\n  <!-- Windows -->\n  <rect x=\"48\" y=\"32\" width=\"6\" height=\"8\" rx=\"1\" fill=\"#FFFFFF\"/>\n  <rect x=\"66\" y=\"32\" width=\"6\" height=\"8\" rx=\"1\" fill=\"#FFFFFF\"/>\n  <rect x=\"48\" y=\"46\" width=\"6\" height=\"8\" rx=\"1\" fill=\"#F5B18D\"/>\n  <rect x=\"66\" y=\"46\" width=\"6\" height=\"8\" rx=\"1\" fill=\"#FFFFFF\"/>\n  <rect x=\"48\" y=\"60\" width=\"6\" height=\"8\" rx=\"1\" fill=\"#FFFFFF\"/>\n  <rect x=\"66\" y=\"60\" width=\"6\" height=\"8\" rx=\"1\" fill=\"#F5B18D\"/>\n  <rect x=\"48\" y=\"74\" width=\"6\" height=\"8\" rx=\"1\" fill=\"#FFFFFF\"/>\n  <rect x=\"66\" y=\"74\" width=\"6\" height=\"8\" rx=\"1\" fill=\"#FFFFFF\"/>\n</svg>"
  },
  {
    "id": "org_bank_vault",
    "name": "Financial Institution Vault",
    "types": [
      "ORGANIZATION"
    ],
    "category": "corporate",
    "label": "Banking institution financial intermediary with vault",
    "path": "/static/assets/stickers/org_bank_vault.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"60,26 28,42 92,42\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <rect x=\"32\" y=\"42\" width=\"56\" height=\"6\" fill=\"#F5B18D\"/>\n  <!-- Columns -->\n  <rect x=\"36\" y=\"48\" width=\"8\" height=\"36\" fill=\"#29243B\"/>\n  <rect x=\"56\" y=\"48\" width=\"8\" height=\"36\" fill=\"#29243B\"/>\n  <rect x=\"76\" y=\"48\" width=\"8\" height=\"36\" fill=\"#29243B\"/>\n  <rect x=\"28\" y=\"84\" width=\"64\" height=\"8\" rx=\"2\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2\"/>\n</svg>"
  },
  {
    "id": "org_factory_industry",
    "name": "Industrial Enterprise",
    "types": [
      "ORGANIZATION"
    ],
    "category": "corporate",
    "label": "Industrial manufacturing enterprise with facilities",
    "path": "/static/assets/stickers/org_factory_industry.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 30 88 L 30 52 L 48 64 L 48 52 L 66 64 L 66 38 L 90 38 L 90 88 Z\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <circle cx=\"44\" cy=\"74\" r=\"4\" fill=\"#F5B18D\"/>\n  <circle cx=\"60\" cy=\"74\" r=\"4\" fill=\"#FFFFFF\"/>\n  <circle cx=\"76\" cy=\"52\" r=\"4\" fill=\"#FFFFFF\"/>\n</svg>"
  },
  {
    "id": "org_globe_network",
    "name": "Global Conglomerate Network",
    "types": [
      "ORGANIZATION"
    ],
    "category": "corporate",
    "label": "Transnational corporate holding group network",
    "path": "/static/assets/stickers/org_globe_network.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <circle cx=\"60\" cy=\"60\" r=\"32\" fill=\"none\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <ellipse cx=\"60\" cy=\"60\" rx=\"14\" ry=\"32\" fill=\"none\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <line x1=\"28\" y1=\"60\" x2=\"92\" y2=\"60\" stroke=\"#F5B18D\" stroke-width=\"2.5\"/>\n  <circle cx=\"48\" cy=\"46\" r=\"3.5\" fill=\"#F5B18D\"/>\n  <circle cx=\"72\" cy=\"74\" r=\"3.5\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "org_holding_shield",
    "name": "Holding Group Crest",
    "types": [
      "ORGANIZATION"
    ],
    "category": "corporate",
    "label": "Parent holding corporate entity emblem",
    "path": "/static/assets/stickers/org_holding_shield.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 36 34 L 84 34 C 84 64, 60 88, 60 92 C 60 88, 36 64, 36 34 Z\" fill=\"#29243B\" stroke=\"#F5B18D\" stroke-width=\"2.5\"/>\n  <circle cx=\"60\" cy=\"56\" r=\"10\" fill=\"none\" stroke=\"#FFFFFF\" stroke-width=\"2\"/>\n  <circle cx=\"60\" cy=\"56\" r=\"4\" fill=\"#F5B18D\"/>\n</svg>"
  },
  {
    "id": "loc_courthouse",
    "name": "Judicial Courthouse",
    "types": [
      "LOCATION"
    ],
    "category": "location",
    "label": "Courthouse of jurisdiction and legal proceedings",
    "path": "/static/assets/stickers/loc_courthouse.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"60,26 26,44 94,44\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <rect x=\"30\" y=\"44\" width=\"60\" height=\"5\" fill=\"#F5B18D\"/>\n  <rect x=\"35\" y=\"49\" width=\"7\" height=\"34\" fill=\"#29243B\"/>\n  <rect x=\"50\" y=\"49\" width=\"7\" height=\"34\" fill=\"#29243B\"/>\n  <rect x=\"63\" y=\"49\" width=\"7\" height=\"34\" fill=\"#29243B\"/>\n  <rect x=\"78\" y=\"49\" width=\"7\" height=\"34\" fill=\"#29243B\"/>\n  <rect x=\"24\" y=\"83\" width=\"72\" height=\"9\" rx=\"2\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2\"/>\n</svg>"
  },
  {
    "id": "loc_headquarters",
    "name": "Commercial Office Facility",
    "types": [
      "LOCATION"
    ],
    "category": "location",
    "label": "Registered physical office premises",
    "path": "/static/assets/stickers/loc_headquarters.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <rect x=\"34\" y=\"32\" width=\"52\" height=\"64\" rx=\"4\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <rect x=\"42\" y=\"40\" width=\"10\" height=\"10\" rx=\"1\" fill=\"#FFFFFF\"/>\n  <rect x=\"68\" y=\"40\" width=\"10\" height=\"10\" rx=\"1\" fill=\"#FFFFFF\"/>\n  <rect x=\"42\" y=\"56\" width=\"10\" height=\"10\" rx=\"1\" fill=\"#F5B18D\"/>\n  <rect x=\"68\" y=\"56\" width=\"10\" height=\"10\" rx=\"1\" fill=\"#FFFFFF\"/>\n  <rect x=\"52\" y=\"76\" width=\"16\" height=\"20\" rx=\"1\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n</svg>"
  },
  {
    "id": "loc_warehouse",
    "name": "Logistics Depot Facility",
    "types": [
      "LOCATION"
    ],
    "category": "location",
    "label": "Storage warehouse and distribution hub",
    "path": "/static/assets/stickers/loc_warehouse.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 24 64 L 60 40 L 96 64 L 96 92 L 24 92 Z\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <rect x=\"44\" y=\"66\" width=\"32\" height=\"26\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"1.8\"/>\n  <line x1=\"44\" y1=\"72\" x2=\"76\" y2=\"72\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n  <line x1=\"44\" y1=\"78\" x2=\"76\" y2=\"78\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n  <line x1=\"44\" y1=\"84\" x2=\"76\" y2=\"84\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n</svg>"
  },
  {
    "id": "loc_shipping_port",
    "name": "Maritime Shipping Port",
    "types": [
      "LOCATION"
    ],
    "category": "location",
    "label": "International maritime cargo shipping hub",
    "path": "/static/assets/stickers/loc_shipping_port.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 20 86 Q 60 82, 100 86\" stroke=\"#191629\" stroke-width=\"3\" fill=\"none\"/>\n  <rect x=\"34\" y=\"60\" width=\"30\" height=\"22\" rx=\"2\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <line x1=\"74\" y1=\"86\" x2=\"74\" y2=\"38\" stroke=\"#29243B\" stroke-width=\"3\"/>\n  <line x1=\"50\" y1=\"38\" x2=\"94\" y2=\"38\" stroke=\"#29243B\" stroke-width=\"3\"/>\n  <line x1=\"56\" y1=\"38\" x2=\"56\" y2=\"56\" stroke=\"#191629\" stroke-width=\"1.8\"/>\n</svg>"
  },
  {
    "id": "loc_map_pinpoint",
    "name": "Geographic Survey Map",
    "types": [
      "LOCATION"
    ],
    "category": "location",
    "label": "Geocoded cartographic location pinpoint",
    "path": "/static/assets/stickers/loc_map_pinpoint.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <polygon points=\"30,46 48,38 72,46 90,38 90,88 72,96 48,88 30,96\" fill=\"#FFFFFF\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <!-- Map Pin -->\n  <path d=\"M 60 42 C 53 42, 48 47, 48 54 C 48 64, 60 76, 60 76 C 60 76, 72 64, 72 54 C 72 47, 67 42, 60 42 Z\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <circle cx=\"60\" cy=\"53\" r=\"3.5\" fill=\"#FFFFFF\"/>\n</svg>"
  },
  {
    "id": "loc_island_offshore",
    "name": "Offshore Jurisdiction Island",
    "types": [
      "LOCATION"
    ],
    "category": "location",
    "label": "Offshore financial jurisdiction haven island",
    "path": "/static/assets/stickers/loc_island_offshore.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 22 84 Q 60 74, 98 84 Z\" fill=\"#E8DEC8\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <!-- Palm tree -->\n  <path d=\"M 52 80 Q 56 56, 62 48\" stroke=\"#191629\" stroke-width=\"3\" fill=\"none\"/>\n  <path d=\"M 62 48 Q 50 40, 42 46\" stroke=\"#3EAE7C\" stroke-width=\"3\" fill=\"none\"/>\n  <path d=\"M 62 48 Q 66 36, 74 38\" stroke=\"#3EAE7C\" stroke-width=\"3\" fill=\"none\"/>\n  <path d=\"M 62 48 Q 74 46, 82 54\" stroke=\"#3EAE7C\" stroke-width=\"3\" fill=\"none\"/>\n  <circle cx=\"78\" cy=\"74\" r=\"6\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"1.8\"/>\n</svg>"
  },
  {
    "id": "evidence_document_seal",
    "name": "Official Document Wax Seal",
    "types": [
      "EVIDENCE",
      "UNKNOWN"
    ],
    "category": "evidence",
    "label": "Official notarized document with verification seal",
    "path": "/static/assets/stickers/evidence_document_seal.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <rect x=\"36\" y=\"24\" width=\"48\" height=\"66\" rx=\"3\" fill=\"#FFFFFF\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <line x1=\"44\" y1=\"36\" x2=\"76\" y2=\"36\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <line x1=\"44\" y1=\"44\" x2=\"76\" y2=\"44\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n  <line x1=\"44\" y1=\"52\" x2=\"68\" y2=\"52\" stroke=\"#191629\" stroke-width=\"1.5\"/>\n  <circle cx=\"70\" cy=\"74\" r=\"12\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <path d=\"M 66 74 L 69 77 L 75 71\" stroke=\"#FFFFFF\" stroke-width=\"2\" fill=\"none\"/>\n</svg>"
  },
  {
    "id": "evidence_folder_classified",
    "name": "Classified Evidence Folder",
    "types": [
      "EVIDENCE",
      "UNKNOWN"
    ],
    "category": "evidence",
    "label": "Confidential investigation evidence folder",
    "path": "/static/assets/stickers/evidence_folder_classified.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 42 L 52 42 L 60 48 L 92 48 L 92 88 L 28 88 Z\" fill=\"#E8DEC8\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <path d=\"M 28 54 L 92 54 L 92 88 L 28 88 Z\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <rect x=\"44\" y=\"64\" width=\"32\" height=\"12\" rx=\"2\" fill=\"#FFFFFF\" stroke=\"#191629\" stroke-width=\"1.2\"/>\n  <text x=\"60\" y=\"73\" font-family=\"'Plus Jakarta Sans', sans-serif\" font-size=\"7\" font-weight=\"800\" fill=\"#191629\" text-anchor=\"middle\">EVIDENCE</text>\n</svg>"
  },
  {
    "id": "evidence_network_nodes",
    "name": "Entity Relational Cluster",
    "types": [
      "EVIDENCE",
      "ORGANIZATION",
      "PERSON"
    ],
    "category": "evidence",
    "label": "Interconnected entity graph nodes cluster",
    "path": "/static/assets/stickers/evidence_network_nodes.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <line x1=\"42\" y1=\"46\" x2=\"78\" y2=\"46\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <line x1=\"42\" y1=\"46\" x2=\"60\" y2=\"82\" stroke=\"#F5B18D\" stroke-width=\"2.5\" stroke-dasharray=\"4,3\"/>\n  <line x1=\"78\" y1=\"46\" x2=\"60\" y2=\"82\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <circle cx=\"42\" cy=\"46\" r=\"12\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <circle cx=\"42\" cy=\"46\" r=\"4\" fill=\"#F5B18D\"/>\n  <circle cx=\"78\" cy=\"46\" r=\"12\" fill=\"#29243B\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <circle cx=\"78\" cy=\"46\" r=\"4\" fill=\"#FFFFFF\"/>\n  <circle cx=\"60\" cy=\"82\" r=\"12\" fill=\"#F5B18D\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <circle cx=\"60\" cy=\"82\" r=\"4\" fill=\"#191629\"/>\n</svg>"
  },
  {
    "id": "evidence_magnifier_fingerprint",
    "name": "Forensic Fingerprint Analysis",
    "types": [
      "EVIDENCE",
      "PERSON"
    ],
    "category": "evidence",
    "label": "Biometric forensic pattern analysis",
    "path": "/static/assets/stickers/evidence_magnifier_fingerprint.svg",
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">\n  <circle cx=\"60\" cy=\"60\" r=\"56\" fill=\"#F7F4F0\" stroke=\"#191629\" stroke-width=\"2.5\"/>\n  <ellipse cx=\"60\" cy=\"60\" rx=\"18\" ry=\"24\" fill=\"none\" stroke=\"#191629\" stroke-width=\"2\"/>\n  <ellipse cx=\"60\" cy=\"60\" rx=\"10\" ry=\"16\" fill=\"none\" stroke=\"#F5B18D\" stroke-width=\"2\"/>\n  <circle cx=\"56\" cy=\"54\" r=\"18\" fill=\"none\" stroke=\"#191629\" stroke-width=\"3\"/>\n  <line x1=\"68\" y1=\"68\" x2=\"86\" y2=\"86\" stroke=\"#191629\" stroke-width=\"4.5\" stroke-linecap=\"round\"/>\n</svg>"
  }
];

  const STICKER_MAP = new Map();
  STICKER_REGISTRY.forEach((s) => STICKER_MAP.set(s.id, s));

  // Fallback sticker
  const DEFAULT_STICKER = STICKER_MAP.get("cat_detective_deerstalker");
  const UNKNOWN_STICKER = STICKER_MAP.get("cat_mystery_question");
  const ORG_STICKER = STICKER_MAP.get("org_corporate_suit");
  const LOC_STICKER = STICKER_MAP.get("loc_headquarters");

  /**
   * Deterministic 32-bit FNV-1a Hash of string.
   */
  function hashEntityId(str) {
    if (!str) return 0;
    let hash = 2166136261;
    for (let i = 0; i < str.length; i++) {
      hash ^= str.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return Math.abs(hash >>> 0);
  }

  /**
   * Get deterministic sticker for an entity based on its ID and type.
   * Ensures the same entity always receives the same avatar across sessions and components.
   */
  function getStickerForEntity(entityId, entityType) {
    const typeUpper = (entityType || "UNKNOWN").toUpperCase();
    
    // Filter by type matching
    let pool = STICKER_REGISTRY.filter((s) => s.types.includes(typeUpper));
    if (pool.length === 0) {
      if (typeUpper === "ORGANIZATION") pool = STICKER_REGISTRY.filter((s) => s.types.includes("ORGANIZATION"));
      else if (typeUpper === "LOCATION") pool = STICKER_REGISTRY.filter((s) => s.types.includes("LOCATION"));
      else if (typeUpper === "PERSON") pool = STICKER_REGISTRY.filter((s) => s.types.includes("PERSON"));
      else pool = STICKER_REGISTRY;
    }

    if (!entityId) {
      if (typeUpper === "ORGANIZATION") return ORG_STICKER;
      if (typeUpper === "LOCATION") return LOC_STICKER;
      if (typeUpper === "UNKNOWN") return UNKNOWN_STICKER;
      return DEFAULT_STICKER;
    }

    const h = hashEntityId(String(entityId));
    return pool[h % pool.length] || DEFAULT_STICKER;
  }

  /**
   * Look up a sticker by exact ID.
   */
  function getStickerById(stickerId) {
    return STICKER_MAP.get(stickerId) || DEFAULT_STICKER;
  }

  /**
   * Render HTML string for an entity sticker image/avatar.
   */
  function renderEntitySticker(entityId, entityType, options = {}) {
    const size = options.size || "md"; // "sm" (28px), "md" (44px), "lg" (76px), "xl" (110px)
    const className = options.className || "";
    const sticker = options.stickerId 
      ? getStickerById(options.stickerId) 
      : getStickerForEntity(entityId, entityType);

    const sizeMap = {
      xs: 20,
      sm: 28,
      md: 44,
      lg: 76,
      xl: 110,
    };
    const px = sizeMap[size] || 44;

    return `
      <img src="${sticker.path}" 
           alt="${escapeHtml(sticker.label)}" 
           title="${escapeHtml(sticker.name)}"
           class="entity-sticker-img sticker-size-${size} ${className}"
           width="${px}" 
           height="${px}"
           loading="lazy" />
    `.trim();
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Public export
  window.SherlockStickers = {
    REGISTRY: STICKER_REGISTRY,
    MAP: STICKER_MAP,
    hashEntityId,
    getStickerForEntity,
    getStickerById,
    renderEntitySticker,
  };
})();
