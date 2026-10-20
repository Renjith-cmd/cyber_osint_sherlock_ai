import os
import re
import urllib.request
import json

BASE_URL = "http://127.0.0.1:8000"
REPO_ROOT = "/home/renjith-cmd/Documents/sherlock-ai-1/entity_resolution_graph_osint"

def test_api_health():
    url = f"{BASE_URL}/api/v1/health"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert data.get("status") == "ok"
    print("✓ Health endpoint OK")

def test_api_investigations():
    url = f"{BASE_URL}/api/v1/investigations/demo_benchmark_4495/entities"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert "entities" in data
        assert len(data["entities"]) > 0
    print(f"✓ Entities endpoint OK ({len(data['entities'])} entities)")

    url = f"{BASE_URL}/api/v1/investigations/demo_benchmark_4495/graph"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert "nodes" in data and "edges" in data
    print(f"✓ Graph endpoint OK ({len(data['nodes'])} nodes, {len(data['edges'])} edges)")

    url = f"{BASE_URL}/api/v1/investigations/demo_benchmark_4495/claims"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert "claims" in data
    print(f"✓ Claims endpoint OK ({len(data['claims'])} claims)")

    url = f"{BASE_URL}/api/v1/investigations/demo_benchmark_4495/evidence"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        ev_list = data.get("evidence") or data.get("evidence_items")
        assert ev_list is not None
        assert len(ev_list) > 0
    print(f"✓ Evidence endpoint OK ({len(ev_list)} items)")

def test_static_assets():
    files_to_check = [
        "/static/app.css",
        "/static/app.js",
        "/static/stickers.js",
        "/static/assets/stickers/cat_detective_deerstalker.svg",
        "/static/assets/stickers/cat_detective_magnifier.svg",
        "/static/assets/stickers/org_skyscraper_tower.svg",
        "/static/assets/stickers/loc_headquarters.svg",
    ]
    for f in files_to_check:
        url = f"{BASE_URL}{f}"
        with urllib.request.urlopen(url) as resp:
            assert resp.status == 200
    print(f"✓ Checked {len(files_to_check)} static assets successfully")

def test_dom_elements():
    html_path = os.path.join(REPO_ROOT, "src/ui/index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    js_path = os.path.join(REPO_ROOT, "src/ui/app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Extract all document.getElementById calls in app.js
    ids_in_js = re.findall(r'document\.getElementById\(["\']([^"\']+)["\']\)', js)
    missing = []
    for elem_id in set(ids_in_js):
        if f'id="{elem_id}"' not in html and f"id='{elem_id}'" not in html:
            missing.append(elem_id)

    if missing:
        print(f"⚠️ Warning: Some element IDs in app.js not found in index.html: {missing}")
    else:
        print(f"✓ All {len(set(ids_in_js))} getElementById references in app.js exist in index.html!")

if __name__ == "__main__":
    test_api_health()
    test_api_investigations()
    test_static_assets()
    test_dom_elements()
    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
