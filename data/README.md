# Sherlock AI Real-World Dataset Manifest & Provenance

This directory contains metadata, provenance manifests, and acquisition guides for real-world entity resolution benchmark datasets evaluated in Sherlock AI (Milestone 6).

---

## Selected Dataset: Zagat-Fodor's Restaurant Benchmark

### 1. Dataset Overview & Provenance
The **Zagat-Fodor's Restaurant Benchmark** is an empirical, real-world entity resolution dataset compiled from two prominent online restaurant directories: **Fodor's** and **Zagat**.
- **Domain:** Commercial restaurant listings across US metropolitan regions.
- **Original Research Compilation:** Sheila Tejada, Craig A. Knoblock, Steven Minton (2001) in *"Learning Object Identification Rules for Information Integration"*, *Information Systems*, Vol. 26, No. 8, pp. 607–633.
- **Curated Distribution:** Rebecca Steorts, Andee Kaplan, Srini Sunil in CRAN package `restaurant` (v0.1.0) and Chen, Shrivastava, Steorts (2018) in `cleanzr/fasthash` (*Annals of Applied Statistics*).
- **Canonical Download URL:** `https://raw.githubusercontent.com/cleanzr/fasthash/master/data/Restaurant.csv`
- **SHA-256 Checksum:** `9aaada16f7bfacda72d7c5182852dc3d1bd4301fe834e955aacf2c3c655260fd`

### 2. Licensing, Attribution & Privacy
- **License Status:** **Qualified Research Use / Unverified Commercial Redistribution**.
  - **CRAN Package:** The `restaurant` package v0.1.0 on CRAN states **CC0 1.0 Universal**.
  - **Source Repository:** `cleanzr/fasthash` (Chen, Shrivastava, Steorts 2018) requires academic citation and directs commercial/proprietary inquiries to the authors.
  - **Underlying Lineage:** Records originate from late-1990s Zagat Survey and Fodor's commercial travel guides (Sheila Tejada et al., 2001).
- **Redistribution Policy:** Redistribution terms are not unconditionally unrestricted for commercial redistribution. In compliance with project policy, raw CSV dataset files are **strictly excluded from Git** via `.gitignore` and acquired locally for benchmarking.
- **Privacy & Ethical Safeguards:**
  - All records represent commercial business establishments (restaurant name, street address, city, cuisine).
  - Contains **zero personal data, zero private contact details, and no individual PII**.
  - No web scraping or surveillance data is involved.

### 3. Quantitative Characteristics
- **Total Records:** 864 records (533 from Fodor's, 331 from Zagat).
- **Unique Canonical Entities:** 752 distinct real-world restaurants.
- **Duplicate Entity Groups:** 112 entities represented by 2 records each (224 records total).
- **Singleton Entities:** 640 restaurants represented by a single record.
- **Ground-Truth Positive Pairs:** 112 true matching pairs.
- **Total Possible Pairs (Cartesian Baseline):**
  $$\frac{864 \times 863}{2} = 372,816 \text{ pairs}$$
- **Entity-Type Compatible Pairs:** All 372,816 pairs belong to `EntityType.ORGANIZATION`.

### 4. Schema Mapping to Sherlock AI Core Model

| Source Column | Field Description | Sherlock AI Target Contract | Role in Evaluation |
| :--- | :--- | :--- | :--- |
| **Column 0** | Restaurant Name | `Record.raw_name` | Operational candidate blocking & pairwise comparison |
| **Column 1** | Street Address | `Record.structured_attributes["address"]` | Auxiliary attribute comparison |
| **Column 2** | City | `Record.structured_attributes["city"]` | Operational candidate blocking (`city`) & comparison |
| **Column 3** | Cuisine Type | `Record.structured_attributes["cuisine"]` | Auxiliary attribute comparison |
| **Column 4** | Class / Entity ID | `ground_truth_entities[record_id]` | **Oracle Ground Truth ONLY** (Strictly segregated from Record) |

### 5. Acquisition & Reproduction Instructions

#### Automated Acquisition via Python API
```python
from src.core.datasets import acquire_restaurant_dataset, RestaurantDatasetAdapter

# 1. Download and verify SHA-256 checksum
dataset_path = acquire_restaurant_dataset(target_dir="data")

# 2. Ingest into immutable Record models with segregated ground truth
adapter = RestaurantDatasetAdapter()
report = adapter.load_from_csv(dataset_path)

print(f"Loaded {report.accepted_records_count} records and {len(report.ground_truth_entities)} entity labels.")
```

#### CLI Benchmark Execution
```bash
# Evaluate the real-world dataset end-to-end with all 4 baselines:
.venv/bin/python -m src.core.benchmark --real-world --output artifacts/benchmarks/real_world/restaurant_benchmark_results.json
```
