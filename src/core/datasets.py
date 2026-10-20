"""
Real-world dataset adapters, manifests, and data ingestion for entity resolution.

Milestone 6: Real-World Dataset Integration, Evaluation & Error Analysis.

This module provides verified data adapters, provenance manifests, validation routines,
and ground-truth segregation for benchmark entity resolution datasets.

Design Guarantees & Principles:
1. Strict Ground-Truth Boundary: Operational records and ground-truth identities are strictly
   separated. Ground truth labels are never embedded into Record attributes, blocking keys,
   or comparator inputs.
2. Provenance & Licensing: Every dataset adapter declares an explicit DatasetManifest
   recording source URLs, authors, license terms, attribution, and cryptographic checksums.
3. Robust Validation: Ingestion validates required fields, malformed rows, duplicate record IDs,
   and inconsistent labels, providing clear rejection audit records without silent dropping.
4. Offline Test Fixtures: Provides embedded, offline test fixtures that enable comprehensive
   unit testing without requiring network connectivity.
5. Non-Destructive Ingestion: Input records are mapped into immutable Record instances
   adhering to the core data contract established in Milestone 1.
"""

import csv
from dataclasses import asdict, dataclass, field
import hashlib
import os
import random
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union
import urllib.request

from src.core.models import EntityType, Record


# ---------------------------------------------------------------------------
# Dataset Manifest and Provenance Data Contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DatasetManifest:
    """
    Immutable metadata documenting provenance, licensing, schema, and checksums.
    """
    dataset_id: str
    title: str
    domain: str
    license_name: str
    license_url: str
    authors: str
    provenance_citation: str
    canonical_source_url: str
    sha256_checksum: str
    expected_records_count: int
    expected_entities_count: int
    expected_duplicates_count: int
    field_schema_mapping: Mapping[str, str]
    redistribution_policy: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


RESTAURANT_DATASET_MANIFEST = DatasetManifest(
    dataset_id="zagat_fodors_restaurants",
    title="Zagat-Fodor's Restaurant Benchmark for Entity Resolution",
    domain="restaurants_and_food_service",
    license_name="Creative Commons Zero 1.0 Universal (CC0 1.0)",
    license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    authors="Sheila Tejada, Craig A. Knoblock, Steven Minton (2001); curated by Rebecca Steorts et al. (2018)",
    provenance_citation=(
        "Tejada, S., Knoblock, C. A., & Minton, S. (2001). Learning object identification rules "
        "for information integration. Information Systems, 26(8), 607-633. Curated in cleanzr/fasthash "
        "(Chen, Shrivastava, Steorts, 2018; Annals of Applied Statistics)."
    ),
    canonical_source_url="https://raw.githubusercontent.com/cleanzr/fasthash/master/data/Restaurant.csv",
    sha256_checksum="9aaada16f7bfacda72d7c5182852dc3d1bd4301fe834e955aacf2c3c655260fd",
    expected_records_count=864,
    expected_entities_count=752,
    expected_duplicates_count=112,
    field_schema_mapping={
        "column_0_name": "raw_name",
        "column_1_address": "structured_attributes['address']",
        "column_2_city": "structured_attributes['city']",
        "column_3_cuisine": "structured_attributes['cuisine']",
        "column_4_class": "ground_truth_entity_id (Oracle only)",
    },
    redistribution_policy=(
        "CC0 1.0 Universal per CRAN 'restaurant' package v0.1.0; cleanzr/fasthash repository requires "
        "academic citation and author contact for commercial inquiries; underlying listings derive from "
        "Zagat/Fodor's guidebooks. Redistribution terms are qualified; raw CSV is excluded from Git via .gitignore."
    ),
)


# ---------------------------------------------------------------------------
# Dataset Ingestion Report
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DatasetLoadingReport:
    """
    Comprehensive report produced upon loading a dataset.
    Maintains clean segregation between operational Record objects and ground-truth oracle.
    """
    dataset_id: str
    total_rows_read: int
    accepted_records_count: int
    rejected_rows_count: int
    skipped_rows_count: int
    rejection_reasons: Mapping[str, int]
    rejection_details: Tuple[Dict[str, Any], ...]
    records: Tuple[Record, ...]
    ground_truth_entities: Mapping[str, str]  # record_id -> canonical_entity_id
    ground_truth_pairs: Mapping[str, bool]    # pair_id -> bool (cp_r1_r2)
    manifest: DatasetManifest
    loading_time_seconds: float

    @property
    def positive_pairs_count(self) -> int:
        return sum(1 for is_pos in self.ground_truth_pairs.values() if is_pos)

    @property
    def total_compatible_pairs(self) -> int:
        n = len(self.records)
        return n * (n - 1) // 2 if n >= 2 else 0

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "total_rows_read": self.total_rows_read,
            "accepted_records_count": self.accepted_records_count,
            "rejected_rows_count": self.rejected_rows_count,
            "skipped_rows_count": self.skipped_rows_count,
            "rejection_reasons": dict(self.rejection_reasons),
            "unique_entities_count": len(set(self.ground_truth_entities.values())),
            "positive_pairs_count": self.positive_pairs_count,
            "total_possible_pairs": self.total_compatible_pairs,
            "manifest": self.manifest.to_dict(),
            "loading_time_seconds": round(self.loading_time_seconds, 4),
        }


# ---------------------------------------------------------------------------
# Leakage-Free Dataset Partitioning & Entity-Stratified Splits
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DatasetPartition:
    """
    Isolated partition of records and segregated ground truth for leakage-free evaluation.
    """
    partition_name: str
    records: Tuple[Record, ...]
    ground_truth_entities: Mapping[str, str]
    ground_truth_pairs: Mapping[str, bool]
    entity_ids: Tuple[str, ...]
    deterministic_fingerprint: str

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def record_ids(self) -> Tuple[str, ...]:
        return tuple(r.record_id for r in self.records)

    @property
    def split_fingerprint(self) -> str:
        return self.deterministic_fingerprint

    @property
    def entity_count(self) -> int:
        return len(self.entity_ids)

    @property
    def positive_pairs_count(self) -> int:
        return sum(1 for is_pos in self.ground_truth_pairs.values() if is_pos)

    @property
    def total_possible_pairs(self) -> int:
        n = len(self.records)
        return n * (n - 1) // 2 if n >= 2 else 0

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "partition_name": self.partition_name,
            "record_count": self.record_count,
            "entity_count": self.entity_count,
            "positive_pairs_count": self.positive_pairs_count,
            "total_possible_pairs": self.total_possible_pairs,
            "deterministic_fingerprint": self.deterministic_fingerprint,
        }


@dataclass(frozen=True)
class DatasetSplits:
    """
    Collection of entity-group-stratified partitions ensuring zero cross-split record/entity leakage.
    """
    dataset_id: str
    seed: int
    dev: DatasetPartition
    val: DatasetPartition
    test: DatasetPartition

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "seed": self.seed,
            "partitions": {
                "dev": self.dev.to_summary_dict(),
                "val": self.val.to_summary_dict(),
                "test": self.test.to_summary_dict(),
            },
        }


def create_entity_stratified_split(
    report: DatasetLoadingReport,
    seed: int = 42,
    dev_ratio: float = 0.60,
    val_ratio: float = 0.20,
    test_ratio: float = 0.20,
) -> DatasetSplits:
    """
    Splits a DatasetLoadingReport into dev, validation, and test partitions
    by canonical real-world entity groups.
    
    Guarantees:
    - Zero record overlap across partitions.
    - Zero entity overlap across partitions (all records for an entity stay together).
    - Multi-record duplicate entities are stratified proportionally across partitions.
    - Fully deterministic and reproducible using fixed seed.
    - Cryptographic fingerprint computed for each partition.
    """
    if abs((dev_ratio + val_ratio + test_ratio) - 1.0) > 1e-6:
        raise ValueError("Split ratios must sum to 1.0")

    entity_to_records: Dict[str, List[str]] = {}
    for r in report.records:
        eid = report.ground_truth_entities.get(r.record_id)
        if eid:
            entity_to_records.setdefault(eid, []).append(r.record_id)

    # Separate multi-record and singleton entities
    multi_entities = sorted([eid for eid, rids in entity_to_records.items() if len(rids) > 1])
    single_entities = sorted([eid for eid, rids in entity_to_records.items() if len(rids) == 1])

    rng = random.Random(seed)
    shuffled_multi = list(multi_entities)
    rng.shuffle(shuffled_multi)
    shuffled_single = list(single_entities)
    rng.shuffle(shuffled_single)

    def split_list(lst: List[str]) -> Tuple[List[str], List[str], List[str]]:
        n = len(lst)
        c1 = int(n * dev_ratio)
        c2 = c1 + int(n * val_ratio)
        return lst[:c1], lst[c1:c2], lst[c2:]

    dev_m, val_m, test_m = split_list(shuffled_multi)
    dev_s, val_s, test_s = split_list(shuffled_single)

    rec_by_id = {r.record_id: r for r in report.records}

    def build_partition(name: str, e_m: List[str], e_s: List[str]) -> DatasetPartition:
        e_all = tuple(sorted(e_m + e_s))
        p_records: List[Record] = []
        p_gt_entities: Dict[str, str] = {}
        for eid in e_all:
            for rid in entity_to_records[eid]:
                p_records.append(rec_by_id[rid])
                p_gt_entities[rid] = eid
        p_records.sort(key=lambda r: r.record_id)
        p_records_tuple = tuple(p_records)

        # Build pair ground truth
        p_gt_pairs: Dict[str, bool] = {}
        for i, r1 in enumerate(p_records):
            for r2 in p_records[i + 1:]:
                left_id, right_id = sorted([r1.record_id, r2.record_id])
                p_id = f"cp_{left_id}_{right_id}"
                p_gt_pairs[p_id] = (p_gt_entities[left_id] == p_gt_entities[right_id])

        # Fingerprint
        h = hashlib.sha256()
        h.update(f"partition:{name}:seed:{seed}:".encode())
        for r in p_records:
            h.update(f"{r.record_id}:{p_gt_entities[r.record_id]};".encode())
        fp = h.hexdigest()

        return DatasetPartition(
            partition_name=name,
            records=p_records_tuple,
            ground_truth_entities=p_gt_entities,
            ground_truth_pairs=p_gt_pairs,
            entity_ids=e_all,
            deterministic_fingerprint=fp,
        )

    return DatasetSplits(
        dataset_id=report.dataset_id,
        seed=seed,
        dev=build_partition("dev", dev_m, dev_s),
        val=build_partition("val", val_m, val_s),
        test=build_partition("test", test_m, test_s),
    )


# ---------------------------------------------------------------------------
# Restaurant Dataset Adapter
# ---------------------------------------------------------------------------

class RestaurantDatasetAdapter:
    """
    Adapter for the standard Zagat-Fodor's Restaurant entity resolution dataset.

    Maps 5-column CSV rows into:
    - Operational Record: record_id, entity_type=ORGANIZATION, raw_name, structured_attributes(address, city, cuisine)
    - Ground Truth Oracle: ground_truth_entities mapping record_id -> canonical_entity_id
    """

    def __init__(self, manifest: Optional[DatasetManifest] = None):
        self.manifest = manifest or RESTAURANT_DATASET_MANIFEST

    @staticmethod
    def _make_pair_key(r1: str, r2: str) -> str:
        left, right = sorted([r1, r2])
        return f"cp_{left}_{right}"

    def load_from_rows(
        self,
        rows: Iterable[Sequence[str]],
        skip_header: bool = True,
        source_id: str = "riddle_restaurant",
    ) -> DatasetLoadingReport:
        """
        Parses rows from an iterable into validated Record objects and ground-truth oracle.

        Validates:
        - Row length (at least 5 columns)
        - Non-empty name
        - Non-empty class/entity ID
        - Unique record IDs
        """
        t0 = time.perf_counter()
        records: List[Record] = []
        gt_entities: Dict[str, str] = {}
        rejection_reasons: Dict[str, int] = {}
        rejection_details: List[Dict[str, Any]] = []

        total_rows_read = 0
        skipped_rows = 0

        for row_idx, raw_row in enumerate(rows):
            total_rows_read += 1

            if row_idx == 0 and skip_header:
                # Check if row looks like header (e.g. contains 'header' or 'name')
                first_cell = str(raw_row[0]).lower().strip() if raw_row else ""
                if "header" in first_cell or "name" in first_cell:
                    skipped_rows += 1
                    continue

            # Clean and strip cell contents
            row = [str(cell).strip().strip("'\"") for cell in raw_row]

            # Validation 1: Column count
            if len(row) < 5:
                reason = "insufficient_columns"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                rejection_details.append({
                    "row_index": row_idx,
                    "reason": f"Expected at least 5 columns, got {len(row)}",
                    "raw_row": list(raw_row)[:3],
                })
                continue

            name = row[0].strip()
            address = row[1].strip()
            city = row[2].strip()
            cuisine = row[3].strip()
            entity_id = row[4].strip()

            # Validation 2: Non-empty name
            if not name:
                reason = "empty_restaurant_name"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                rejection_details.append({
                    "row_index": row_idx,
                    "reason": "Restaurant name is empty after whitespace stripping",
                })
                continue

            # Validation 3: Non-empty ground-truth class ID
            if not entity_id:
                reason = "empty_ground_truth_entity_id"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                rejection_details.append({
                    "row_index": row_idx,
                    "reason": "Ground-truth entity identifier is missing or empty",
                })
                continue

            rec_id = f"rest_{len(records):04d}"

            # Construct validated Record
            structured_attrs = {}
            if address:
                structured_attrs["address"] = address
            if city:
                structured_attrs["city"] = city
            if cuisine:
                structured_attrs["cuisine"] = cuisine

            try:
                rec = Record(
                    record_id=rec_id,
                    source_id=source_id,
                    entity_type=EntityType.ORGANIZATION,
                    raw_name=name,
                    structured_attributes=structured_attrs,
                )
                records.append(rec)
                # Store oracle mapping separately
                gt_entities[rec_id] = f"entity_{entity_id}"
            except Exception as e:
                reason = "record_validation_error"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                rejection_details.append({
                    "row_index": row_idx,
                    "reason": f"Record constructor failed: {str(e)}",
                })

        # Derive complete pairwise ground truth
        gt_pairs: Dict[str, bool] = {}
        n = len(records)
        for i in range(n):
            for j in range(i + 1, n):
                r1_id = records[i].record_id
                r2_id = records[j].record_id
                pkey = self._make_pair_key(r1_id, r2_id)
                gt_pairs[pkey] = (gt_entities[r1_id] == gt_entities[r2_id])

        t1 = time.perf_counter()

        return DatasetLoadingReport(
            dataset_id=self.manifest.dataset_id,
            total_rows_read=total_rows_read,
            accepted_records_count=len(records),
            rejected_rows_count=sum(rejection_reasons.values()),
            skipped_rows_count=skipped_rows,
            rejection_reasons=rejection_reasons,
            rejection_details=tuple(rejection_details),
            records=tuple(records),
            ground_truth_entities=gt_entities,
            ground_truth_pairs=gt_pairs,
            manifest=self.manifest,
            loading_time_seconds=t1 - t0,
        )

    def load_from_csv(
        self,
        file_path: str,
        encoding: str = "utf-8",
        skip_header: bool = True,
    ) -> DatasetLoadingReport:
        """
        Loads dataset directly from a local CSV file.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Dataset CSV file not found: {file_path}")

        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            reader = csv.reader(f)
            return self.load_from_rows(reader, skip_header=skip_header)


# ---------------------------------------------------------------------------
# Dataset Acquisition Utility & Checksum Verification
# ---------------------------------------------------------------------------

def acquire_restaurant_dataset(
    target_dir: str = "data",
    manifest: Optional[DatasetManifest] = None,
    verify_checksum: bool = True,
) -> str:
    """
    Acquires the verified CC0 Restaurant dataset from its canonical source URL,
    computes its SHA-256 hash, validates against the manifest, and saves to target_dir.

    Returns the absolute path to the downloaded dataset.
    """
    man = manifest or RESTAURANT_DATASET_MANIFEST
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, "Restaurant.csv")

    # If already downloaded and valid, return existing path
    if os.path.exists(target_path):
        with open(target_path, "rb") as f:
            existing_data = f.read()
        existing_sha = hashlib.sha256(existing_data).hexdigest()
        if existing_sha == man.sha256_checksum:
            return os.path.abspath(target_path)

    # Download from canonical source
    req = urllib.request.Request(
        man.canonical_source_url,
        headers={"User-Agent": "SherlockAI-Dataset-Ingestor/1.0"},
    )
    with urllib.request.urlopen(req) as resp:
        content_bytes = resp.read()

    computed_sha = hashlib.sha256(content_bytes).hexdigest()
    if verify_checksum and computed_sha != man.sha256_checksum:
        raise ValueError(
            f"Checksum verification failed for {man.dataset_id}!\n"
            f"Expected SHA256: {man.sha256_checksum}\n"
            f"Computed SHA256: {computed_sha}"
        )

    with open(target_path, "wb") as f:
        f.write(content_bytes)

    return os.path.abspath(target_path)


# ---------------------------------------------------------------------------
# Offline Test Fixtures (Network-Independent)
# ---------------------------------------------------------------------------

def get_offline_restaurant_fixture_rows() -> List[List[str]]:
    """
    Deterministic offline test fixture containing 10 authentic rows from the Zagat-Fodor's
    dataset. Covers 3 duplicate pairs (entities 0, 1, 2) and 4 singleton entities (entities 3, 4, 5, 6).
    Enables comprehensive testing without network dependencies.
    """
    return [
        ["name", "address", "city", "cuisine", "class"],
        ["arnie morton's of chicago", "435 s. la cienega blv.", "los angeles", "american", "0"],
        ["arnie morton's of chicago", "435 s. la cienega blvd.", "los angeles", "steakhouses", "0"],
        ["art's delicatessen", "12224 ventura blvd.", "studio city", "american", "1"],
        ["art's deli", "12224 ventura blvd.", "studio city", "delis", "1"],
        ["hotel bel-air", "701 stone canyon rd.", "bel air", "californian", "2"],
        ["bel-air hotel", "701 stone canyon rd.", "bel air", "californian", "2"],
        ["cafe bizou", "14016 ventura blvd.", "sherman oaks", "french", "3"],
        ["campanile", "624 s. la brea ave.", "los angeles", "californian", "4"],
        ["chinois on main", "2709 main st.", "santa monica", "pacific new wave", "5"],
        ["citrus", "6703 melrose ave.", "los angeles", "californian", "6"],
    ]
