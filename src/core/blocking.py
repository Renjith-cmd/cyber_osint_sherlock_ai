"""
Candidate generation and blocking strategies for entity resolution.

This module provides modular, deterministic blocking strategies that index validated
Record models and emit deduplicated, canonically-ordered CandidatePair instances.

Core Principles:
1. Candidate Generation is not Matching: Blocking identifies pairs that share
   plausible identity signals for expensive downstream pairwise evaluation. It
   must optimize for retaining true matches (high recall) while aggressively pruning
   implausible comparisons (high reduction ratio).
2. Non-Destructive: Never mutates input records and never makes final match or merge decisions.
3. Canonical Ordering: Emits pairs where left_record_id < right_record_id, with no self-pairs
   or duplicate pairs.
4. Determinism: Output candidate pairs and their internal signals are strictly deterministic
   and invariant to the input record order.
5. Entity Type Safety: By default, rejects pairing records of incompatible entity types.
"""

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from src.core.models import CandidatePair, EntityType, Record
from src.core.normalization import (
    extract_initials,
    name_fingerprint,
    normalize_attribute_value,
    normalize_text,
    soundex,
    tokenize_name,
)


class BlockingRule(ABC):
    """
    Abstract base class for deterministic blocking rules.

    A blocking rule inspects a Record and extracts zero or more blocking keys.
    Records that share at least one blocking key will be proposed as candidate pairs.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier name for this blocking strategy."""
        pass

    @abstractmethod
    def extract_keys(self, record: Record) -> Set[str]:
        """
        Extracts a set of deterministic blocking keys for the given record.
        Must return an empty set if the record lacks required attributes.
        """
        pass


class ExactNameRule(BlockingRule):
    """
    Blocks on exact normalized raw_name.
    """

    @property
    def name(self) -> str:
        return "exact_name"

    def extract_keys(self, record: Record) -> Set[str]:
        norm = normalize_text(record.raw_name)
        if not norm:
            return set()
        return {f"exact_name:{norm}"}


class NameTokenRule(BlockingRule):
    """
    Blocks on individual normalized tokens from raw_name.
    Helps capture partial names, transposed names, and shared family names.
    """

    def __init__(self, min_token_length: int = 2):
        if min_token_length < 1:
            raise ValueError("min_token_length must be at least 1")
        self.min_token_length = min_token_length

    @property
    def name(self) -> str:
        return f"name_token_min_{self.min_token_length}"

    def extract_keys(self, record: Record) -> Set[str]:
        tokens = tokenize_name(record.raw_name, min_length=self.min_token_length)
        return {f"token:{tok}" for tok in tokens}


class NameFingerprintRule(BlockingRule):
    """
    Blocks on order-invariant token fingerprints (sorted unique tokens).
    Captures 'Lastname, Firstname' vs 'Firstname Lastname'.
    """

    @property
    def name(self) -> str:
        return "name_fingerprint"

    def extract_keys(self, record: Record) -> Set[str]:
        fp = name_fingerprint(record.raw_name)
        if not fp:
            return set()
        return {f"fingerprint:{fp}"}


class InitialsAcronymRule(BlockingRule):
    """
    Blocks on initials and acronyms.
    Captures organizations like 'International Business Machines' <-> 'IBM'
    as well as person initials like 'Bruce Wayne' <-> 'BW'.
    """

    def __init__(self, min_length: int = 2, max_length: int = 8):
        self.min_length = min_length
        self.max_length = max_length

    @property
    def name(self) -> str:
        return "initials_acronym"

    def extract_keys(self, record: Record) -> Set[str]:
        initials = extract_initials(record.raw_name)
        if not initials or len(initials) < self.min_length or len(initials) > self.max_length:
            return set()
        return {f"acronym:{initials}"}


class NameSoundexRule(BlockingRule):
    """
    Blocks on American Soundex codes of Latin name tokens.
    Captures minor spelling variations and typos in English/Latin names (e.g. 'Sarah' <-> 'Sara').
    """

    def __init__(self, min_token_length: int = 2):
        self.min_token_length = min_token_length

    @property
    def name(self) -> str:
        return "name_soundex"

    def extract_keys(self, record: Record) -> Set[str]:
        tokens = tokenize_name(record.raw_name, min_length=self.min_token_length)
        keys = set()
        for tok in tokens:
            code = soundex(tok)
            if code:
                keys.add(f"soundex:{code}")
        return keys


class StructuredAttributeRule(BlockingRule):
    """
    Blocks on values of specific structured attributes (e.g., 'dob', 'phone', 'city', 'org').
    Enables linking records with completely different names (e.g. aliases like 'Marshall Mathers'
    and 'Eminem' sharing city 'Detroit').
    """

    def __init__(self, attribute_name: str):
        if not attribute_name or not attribute_name.strip():
            raise ValueError("attribute_name must be a non-empty string")
        self.attribute_name = attribute_name.strip()

    @property
    def name(self) -> str:
        return f"attr_{self.attribute_name}"

    def extract_keys(self, record: Record) -> Set[str]:
        val = record.structured_attributes.get(self.attribute_name)
        if val is None:
            # Also check normalized_attributes fallback if present
            val = record.normalized_attributes.get(self.attribute_name)
        if val is None:
            return set()

        norm_val = normalize_attribute_value(val)
        if not norm_val:
            return set()
        return {f"attr:{self.attribute_name}:{norm_val}"}


def get_default_blocking_rules() -> List[BlockingRule]:
    """
    Returns a balanced set of complementary blocking rules:
    - Exact normalized name
    - Name tokens (length >= 2)
    - Name initials / acronyms
    - Phonetic Soundex on name tokens
    - Common structured attributes: 'dob', 'phone', 'city', 'org'
    """
    return [
        ExactNameRule(),
        NameTokenRule(min_token_length=2),
        InitialsAcronymRule(),
        NameSoundexRule(),
        StructuredAttributeRule("dob"),
        StructuredAttributeRule("phone"),
        StructuredAttributeRule("city"),
        StructuredAttributeRule("org"),
    ]


class CandidateGenerator:
    """
    Deterministic candidate generator that accepts validated Record instances
    and generates deduplicated, canonical CandidatePair objects.
    """

    def __init__(
        self,
        rules: Optional[Sequence[BlockingRule]] = None,
        allow_cross_entity_type: bool = False,
        max_block_size: Optional[int] = None,
        generation_method: str = "blocking",
    ):
        """
        rules: List of blocking rules to apply. Defaults to get_default_blocking_rules().
        allow_cross_entity_type: If False (default), records with different entity_type
                                 will never form candidate pairs.
        max_block_size: Optional cap on the maximum number of records sharing a single
                        blocking key. Blocks exceeding this threshold are ignored to
                        prevent combinatorial pair explosions.
        generation_method: Label assigned to CandidatePair.generation_method.
        """
        if rules is None:
            rules = get_default_blocking_rules()
        self.rules = list(rules)
        self.allow_cross_entity_type = allow_cross_entity_type
        self.max_block_size = max_block_size
        self.generation_method = generation_method

    def generate_candidates(self, records: Sequence[Record]) -> List[CandidatePair]:
        """
        Generates canonical, deduplicated CandidatePair instances from input records.

        Guarantees:
        - Never mutates input records.
        - Never creates self-pairs.
        - Never emits duplicate or reversed duplicate pairs.
        - Strictly deterministic output order regardless of input record ordering.
        - Rejects duplicate record IDs with ValueError.
        - Returns an empty list for empty or singleton inputs.
        """
        if not records or len(records) < 2:
            # Handle empty or singleton input
            if records and len(records) == 1:
                # Still validate record instance
                if not isinstance(records[0], Record):
                    raise TypeError("Expected input items to be Record instances")
            return []

        # Validate records and verify unique record IDs
        seen_ids: Set[str] = set()
        for rec in records:
            if not isinstance(rec, Record):
                raise TypeError(f"Expected Record instance, got {type(rec).__name__}")
            if rec.record_id in seen_ids:
                raise ValueError(
                    f"Duplicate record ID detected: '{rec.record_id}'. Input records must have unique IDs."
                )
            seen_ids.add(rec.record_id)

        # Sort records by record_id to ensure absolute determinism
        sorted_records = sorted(records, key=lambda r: r.record_id)
        records_by_id: Dict[str, Record] = {r.record_id: r for r in sorted_records}

        # Build inverted index: blocking_key -> set of record_ids
        # Also track: (key, record_id) -> list of rule names
        inverted_index: Dict[str, List[str]] = defaultdict(list)
        key_to_rules: Dict[str, Set[str]] = defaultdict(set)

        for rec in sorted_records:
            for rule in self.rules:
                keys = rule.extract_keys(rec)
                for key in sorted(keys):
                    inverted_index[key].append(rec.record_id)
                    key_to_rules[key].add(rule.name)

        # Pair candidate accumulator:
        # (left_id, right_id) -> {"strategies": set(), "matched_keys": set()}
        pair_signals: Dict[Tuple[str, str], Dict[str, Set[str]]] = defaultdict(
            lambda: {"strategies": set(), "matched_keys": set()}
        )

        for key, rec_ids in sorted(inverted_index.items()):
            # Optional block size guard
            if self.max_block_size is not None and len(rec_ids) > self.max_block_size:
                continue

            # Generate all pairs within this block
            num_ids = len(rec_ids)
            for i in range(num_ids):
                id_a = rec_ids[i]
                rec_a = records_by_id[id_a]
                for j in range(i + 1, num_ids):
                    id_b = rec_ids[j]
                    rec_b = records_by_id[id_b]

                    # Filter by entity type compatibility
                    if not self.allow_cross_entity_type and rec_a.entity_type != rec_b.entity_type:
                        continue

                    # Canonical order: id_a < id_b since rec_ids came from sorted_records
                    left_id, right_id = (id_a, id_b) if id_a < id_b else (id_b, id_a)
                    if left_id == right_id:
                        continue

                    signals = pair_signals[(left_id, right_id)]
                    signals["matched_keys"].add(key)
                    signals["strategies"].update(key_to_rules[key])

        # Construct CandidatePair objects in deterministic order
        candidate_pairs: List[CandidatePair] = []
        for (left_id, right_id), signals in sorted(pair_signals.items()):
            candidate_id = f"cp_{left_id}_{right_id}"
            blocking_signals = {
                "strategies": sorted(signals["strategies"]),
                "matched_keys": sorted(signals["matched_keys"]),
            }
            cand = CandidatePair(
                candidate_id=candidate_id,
                left_record_id=left_id,
                right_record_id=right_id,
                generation_method=self.generation_method,
                blocking_signals=blocking_signals,
            )
            candidate_pairs.append(cand)

        return candidate_pairs
