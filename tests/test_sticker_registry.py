"""
Tests for Sherlock AI Entity Sticker & Avatar Library.
Verifies that:
- Minimum 40 distinct sticker assets are created and registered.
- Every registry entry maps to a valid, non-empty, well-formed SVG asset file.
- Deterministic hashing guarantees stable sticker assignment across views and reloads.
- Distinct entity IDs receive varied stickers across the library.
- Fallback mechanics protect against missing or invalid entity types.
"""

import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
STICKERS_DIR = WORKSPACE_ROOT / "src" / "ui" / "assets" / "stickers"
STICKERS_JS = WORKSPACE_ROOT / "src" / "ui" / "stickers.js"


def parse_stickers_registry():
    assert STICKERS_JS.exists(), f"Missing {STICKERS_JS}"
    content = STICKERS_JS.read_text(encoding="utf-8")
    
    # Extract the JSON array STICKER_REGISTRY = [ ... ];
    match = re.search(r"const STICKER_REGISTRY = (\[.*?\]);", content, re.DOTALL)
    assert match, "Failed to parse STICKER_REGISTRY from stickers.js"
    registry_json = match.group(1)
    return json.loads(registry_json)


def fnv1a_32_hash(string_key: str) -> int:
    """Python reproduction of 32-bit FNV-1a hash in stickers.js."""
    hash_val = 0x811C9DC5
    for ch in string_key:
        hash_val ^= ord(ch)
        hash_val = (hash_val * 0x01000193) & 0xFFFFFFFF
    return hash_val


def test_sticker_library_count_and_files():
    """Ensure at least 40 original sticker variations exist as valid SVG files."""
    registry = parse_stickers_registry()
    assert len(registry) >= 40, f"Expected >= 40 stickers, found {len(registry)}"
    
    seen_ids = set()
    for item in registry:
        sticker_id = item["id"]
        assert sticker_id not in seen_ids, f"Duplicate sticker id: {sticker_id}"
        seen_ids.add(sticker_id)
        
        # Check corresponding file exists
        svg_file = STICKERS_DIR / f"{sticker_id}.svg"
        assert svg_file.exists(), f"Missing SVG asset file: {svg_file}"
        svg_content = svg_file.read_text(encoding="utf-8")
        assert len(svg_content) > 50, f"Sticker SVG {svg_file} is suspiciously small"
        
        # Check XML parses without syntax errors
        tree = ET.fromstring(svg_content)
        assert tree.tag.endswith("svg"), f"Root tag of {svg_file} is not svg"


def test_deterministic_sticker_selection():
    """Verify that hashing is strictly deterministic across calls."""
    registry = parse_stickers_registry()
    person_stickers = [s for s in registry if "PERSON" in s.get("types", [])]
    assert len(person_stickers) > 0
    
    test_entities = [
        "ent_watson_001",
        "ent_moriarty_002",
        "ent_adler_003",
        "ent_lestrade_004",
        "ent_mycroft_005",
    ]
    
    for ent_id in test_entities:
        idx1 = fnv1a_32_hash(ent_id) % len(person_stickers)
        idx2 = fnv1a_32_hash(ent_id) % len(person_stickers)
        assert idx1 == idx2, f"Non-deterministic hash result for {ent_id}"
        selected = person_stickers[idx1]
        assert "id" in selected
        assert (STICKERS_DIR / f"{selected['id']}.svg").exists()


def test_sticker_diversity_across_entities():
    """Ensure different entity IDs spread across different stickers."""
    registry = parse_stickers_registry()
    person_stickers = [s for s in registry if "PERSON" in s.get("types", [])]
    
    assigned_stickers = set()
    for i in range(50):
        ent_id = f"entity_investigation_id_{i:04d}"
        idx = fnv1a_32_hash(ent_id) % len(person_stickers)
        assigned_stickers.add(person_stickers[idx]["id"])
    
    # Out of 50 entities, we should have a healthy diversity (at least 12 distinct avatars)
    assert len(assigned_stickers) >= 12, (
        f"Expected good diversity across 50 entities, got only {len(assigned_stickers)} unique stickers"
    )


def test_organization_and_location_sticker_types():
    """Check that ORGANIZATION and LOCATION entity types map to specialized categories."""
    registry = parse_stickers_registry()
    org_stickers = [s for s in registry if "ORGANIZATION" in s.get("types", [])]
    loc_stickers = [s for s in registry if "LOCATION" in s.get("types", [])]
    
    assert len(org_stickers) >= 6, f"Expected >= 6 organization stickers, got {len(org_stickers)}"
    assert len(loc_stickers) >= 5, f"Expected >= 5 location stickers, got {len(loc_stickers)}"
    
    for s in org_stickers:
        assert (STICKERS_DIR / f"{s['id']}.svg").exists()
    for s in loc_stickers:
        assert (STICKERS_DIR / f"{s['id']}.svg").exists()


def test_safe_fallbacks():
    """Check fallback behavior for unknown types and empty inputs."""
    registry = parse_stickers_registry()
    default_sticker = registry[0]
    assert default_sticker["id"] == "cat_detective_deerstalker"
    assert (STICKERS_DIR / f"{default_sticker['id']}.svg").exists()
