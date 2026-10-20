"""
Deterministic, explainable pairwise record comparison for entity resolution.

This module implements offline feature extractors and comparators that evaluate
a pair of Record objects and generate structured, immutable Evidence objects.

Key Guarantees:
1. Immutability: Does not mutate input records or candidate pairs.
2. Explicit Categorization: Explicitly distinguishes agreeing, conflicting,
   and missing attributes. Missing data is never conflated with contradiction.
3. Traceable Evidence: Generates Evidence objects adhering to the Milestone 1
   Evidence model contract with bounded strengths in [0.0, 1.0], explicit polarity
   (SUPPORTING, CONTRADICTING, NEUTRAL), and auditable descriptions.
4. Pure Python: Standard-library implementations of Jaro-Winkler, token overlap,
   acronym analysis, and attribute discrepancy checks with zero external dependencies.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from src.core.models import (
    CandidatePair,
    EntityType,
    Evidence,
    EvidencePolarity,
    Record,
)
from src.core.normalization import (
    extract_address_components,
    extract_initials,
    name_fingerprint,
    normalize_address,
    normalize_attribute_value,
    normalize_business_name,
    normalize_city,
    normalize_text,
    soundex,
    tokenize_name,
)



# ---------------------------------------------------------------------------
# Metropolitan Clusters & Venue Discriminators
# ---------------------------------------------------------------------------

METRO_CLUSTERS = {
    "los_angeles": {
        "los angeles", "beverly hills", "west hollywood", "hollywood", "santa monica",
        "studio city", "sherman oaks", "los feliz", "pasadena", "chinatown", "brentwood",
        "bel air", "encino", "marina del rey", "culver city", "glendale", "burbank",
    },
    "new_york": {
        "new york", "new york city", "brooklyn", "queens", "manhattan", "bronx", "staten island", "nyc",
    },
    "san_francisco": {
        "san francisco", "oakland", "berkeley", "san jose", "palo alto",
    },
    "atlanta": {
        "atlanta", "buckhead", "decatur", "midtown",
    },
}

VENUE_DISCRIMINATORS = {
    "cafe", "cafes", "coffee",
    "dining room",
    "bar", "bars",
    "grill", "grille", "grill room",
    "lounge",
    "bistro", "brasserie",
    "bakery",
    "pizzeria",
    "steakhouse",
    "pub", "tavern",
    "patio", "terrace",
}


def detect_venue_discriminator_conflict(name1: str, name2: str) -> bool:
    """
    Detects if two venue names at the same physical facility or address contain
    conflicting sub-venue keywords (e.g., 'cafe' vs 'dining room'),
    indicating separate business operations operating in the same facility.
    """
    n1, n2 = name1.lower(), name2.lower()
    t1, t2 = set(tokenize_name(n1)), set(tokenize_name(n2))
    v1 = {v for v in VENUE_DISCRIMINATORS if v in t1 or f"({v})" in n1}
    v2 = {v for v in VENUE_DISCRIMINATORS if v in t2 or f"({v})" in n2}
    if "dining room" in n1 or ("dining" in t1 and "room" in t1):
        v1.add("dining room")
    if "dining room" in n2 or ("dining" in t2 and "room" in t2):
        v2.add("dining room")
    if "grill room" in n1 or ("grill" in t1 and "room" in t1):
        v1.add("grill room")
    if "grill room" in n2 or ("grill" in t2 and "room" in t2):
        v2.add("grill room")
    return bool(v1 and v2 and not (v1 & v2))


# ---------------------------------------------------------------------------
# String Similarity Algorithms (Standard Library / Pure Python)
# ---------------------------------------------------------------------------

def jaro_similarity(s1: str, s2: str) -> float:
    """
    Computes the standard Jaro string similarity between two strings.
    Returns a float between 0.0 (no similarity) and 1.0 (exact match).
    """
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j]:
                continue
            if s1[i] == s2[j]:
                s1_matches[i] = True
                s2_matches[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    k = 0
    transpositions = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    t = transpositions / 2.0
    return (matches / len1 + matches / len2 + (matches - t) / matches) / 3.0


def jaro_winkler_similarity(s1: str, s2: str, prefix_weight: float = 0.1, max_prefix: int = 4) -> float:
    """
    Computes Jaro-Winkler similarity, adjusting Jaro score for common initial prefixes.
    Ideal for person and organization names with minor typographical errors.
    """
    j = jaro_similarity(s1, s2)
    if j < 0.7:
        return j

    prefix = 0
    for c1, c2 in zip(s1[:max_prefix], s2[:max_prefix]):
        if c1 == c2:
            prefix += 1
        else:
            break

    return min(1.0, j + prefix * prefix_weight * (1.0 - j))


def token_jaccard_similarity(tokens1: Sequence[str], tokens2: Sequence[str]) -> float:
    """Computes Jaccard similarity across unique token sets: |A ∩ B| / |A ∪ B|."""
    set1, set2 = set(tokens1), set(tokens2)
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def token_containment(tokens1: Sequence[str], tokens2: Sequence[str]) -> float:
    """Computes token containment: |A ∩ B| / min(|A|, |B|)."""
    set1, set2 = set(tokens1), set(tokens2)
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    min_len = min(len(set1), len(set2))
    return intersection / min_len if min_len > 0 else 0.0


# ---------------------------------------------------------------------------
# Structured Comparison Results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ComparisonResult:
    """
    Immutable container capturing all pairwise comparison signals and evidence items.
    """
    candidate_pair_id: str
    left_record_id: str
    right_record_id: str
    entity_type_compatible: bool
    name_similarity: float
    attribute_agreement_score: float
    attribute_contradiction_score: float
    has_fatal_contradiction: bool
    evidence_items: Tuple[Evidence, ...] = field(default_factory=tuple)
    summary_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_pair_key(self) -> str:
        left, right = sorted([self.left_record_id, self.right_record_id])
        return f"{left}::{right}"

    @property
    def has_venue_discriminator_conflict(self) -> bool:
        return bool(self.summary_metadata.get("has_venue_discriminator_conflict", False))



# ---------------------------------------------------------------------------
# Pairwise Record Comparator
# ---------------------------------------------------------------------------

class PairwiseComparator:
    """
    Deterministic comparison engine that inspects a pair of Record objects,
    measures feature similarities, and produces evidence-backed ComparisonResult instances.
    """

    IMMUTABLE_IDENTIFIERS = {
        "dob",
        "ssn",
        "tax_id",
        "passport_number",
        "national_id",
        "registration_id",
    }

    CONTACT_IDENTIFIERS = {
        "email",
        "phone",
    }

    HIGH_VALUE_ATTRIBUTES = IMMUTABLE_IDENTIFIERS | CONTACT_IDENTIFIERS

    CONTEXTUAL_ATTRIBUTES = {
        "city": 0.25,
        "country": 0.15,
        "org": 0.35,
        "occupation": 0.30,
        "role": 0.30,
        "region": 0.15,
        "state": 0.15,
    }

    def __init__(
        self,
        known_aliases: Optional[Mapping[str, Sequence[str]]] = None,
        provenance: str = "sherlock_comparison_engine_v1",
        enable_advanced_normalization: bool = False,
        detect_venue_conflicts: bool = False,
    ):
        """
        known_aliases: Optional dictionary mapping canonical entity names to known aliases.
        provenance: Audit provenance string populated into all Evidence objects.
        enable_advanced_normalization: When True, applies intelligent address normalization,
            metropolitan cluster reasoning, and business name normalization.
        detect_venue_conflicts: When True, checks for conflicting sub-venue discriminators
            (e.g. cafe vs dining room) operating at a shared address or facility.
        """
        self.provenance = provenance
        self.enable_advanced_normalization = enable_advanced_normalization
        self.detect_venue_conflicts = detect_venue_conflicts
        self.known_aliases: Dict[str, Set[str]] = {}
        if known_aliases:
            for k, aliases in known_aliases.items():
                norm_k = normalize_text(k)
                norm_vals = {normalize_text(a) for a in aliases if normalize_text(a)}
                if norm_k:
                    self.known_aliases.setdefault(norm_k, set()).update(norm_vals)
                    for a in norm_vals:
                        self.known_aliases.setdefault(a, set()).add(norm_k)

    @classmethod
    def create_production_comparator(
        cls,
        known_aliases: Optional[Mapping[str, Sequence[str]]] = None,
        provenance: str = "sherlock_comparison_engine_v2_production",
    ) -> "PairwiseComparator":
        """
        Creates a production-grade comparator equipped with address normalization,
        metropolitan cluster reasoning, and sub-venue conflict discrimination.
        """
        return cls(
            known_aliases=known_aliases,
            provenance=provenance,
            enable_advanced_normalization=True,
            detect_venue_conflicts=True,
        )

    def compare(
        self,
        left: Record,
        right: Record,
        candidate_pair: Optional[CandidatePair] = None,
    ) -> ComparisonResult:
        """
        Performs comprehensive, deterministic comparison of two Record objects.
        """
        # Ensure canonical pair ID and validate candidate pair consistency
        l_id, r_id = left.record_id, right.record_id
        if candidate_pair:
            cp_ids = {candidate_pair.left_record_id, candidate_pair.right_record_id}
            if cp_ids != {l_id, r_id}:
                raise ValueError(
                    f"CandidatePair record IDs {sorted(list(cp_ids))} do not match "
                    f"supplied Record IDs {sorted([l_id, r_id])}."
                )
            pair_id = candidate_pair.candidate_id
        else:
            canon_l, canon_r = sorted([l_id, r_id])
            pair_id = f"cp_{canon_l}_{canon_r}"

        record_ref = f"{l_id}::{r_id}"
        source_ref = f"{left.source_id}::{right.source_id}"
        evidence_list: List[Evidence] = []
        ev_counter = 0

        def add_evidence(
            ev_type: str,
            polarity: EvidencePolarity,
            desc: str,
            strength: float,
            meta: Optional[Dict[str, Any]] = None,
        ) -> Evidence:
            nonlocal ev_counter
            ev_counter += 1
            ev_id = f"ev_{pair_id}_{ev_type}_{ev_counter:03d}"
            bounded_strength = max(0.0, min(1.0, float(strength)))
            ev = Evidence(
                evidence_id=ev_id,
                evidence_type=ev_type,
                polarity=polarity,
                value_description=desc,
                source_reference=source_ref,
                record_reference=record_ref,
                provenance=self.provenance,
                strength=bounded_strength,
                metadata=meta or {},
            )
            evidence_list.append(ev)
            return ev

        # -------------------------------------------------------------------
        # 1. Entity Type Compatibility Check
        # -------------------------------------------------------------------
        has_fatal_contradiction = False
        if left.entity_type != right.entity_type:
            has_fatal_contradiction = True
            add_evidence(
                ev_type="entity_type_conflict",
                polarity=EvidencePolarity.CONTRADICTING,
                desc=f"Incompatible entity types: left is '{left.entity_type.value}', right is '{right.entity_type.value}'",
                strength=1.0,
                meta={"left_entity_type": left.entity_type.value, "right_entity_type": right.entity_type.value},
            )
            return ComparisonResult(
                candidate_pair_id=pair_id,
                left_record_id=l_id,
                right_record_id=r_id,
                entity_type_compatible=False,
                name_similarity=0.0,
                attribute_agreement_score=0.0,
                attribute_contradiction_score=1.0,
                has_fatal_contradiction=True,
                evidence_items=tuple(evidence_list),
                summary_metadata={"reason": "Incompatible entity types"},
            )
        else:
            add_evidence(
                ev_type="entity_type_agreement",
                polarity=EvidencePolarity.SUPPORTING,
                desc=f"Compatible entity type: both records are '{left.entity_type.value}'",
                strength=0.20,
                meta={"entity_type": left.entity_type.value},
            )

        # -------------------------------------------------------------------
        # 2. Textual Name Similarity & Aliases
        # -------------------------------------------------------------------
        raw_l = left.raw_name
        raw_r = right.raw_name
        norm_l = normalize_text(raw_l)
        norm_r = normalize_text(raw_r)

        name_sim, is_alias, has_discrim = self._compare_names(left, right, norm_l, norm_r, add_evidence)

        # -------------------------------------------------------------------
        # 3. Structured Attributes Comparison
        # -------------------------------------------------------------------
        attr_agreement, attr_conflict, has_attr_fatal, has_venue_conflict = self._compare_attributes(
            left, right, add_evidence
        )
        if has_attr_fatal:
            has_fatal_contradiction = True

        # -------------------------------------------------------------------
        # 4. Contextual Candidate Generation Blocking Signals
        # -------------------------------------------------------------------
        if candidate_pair and candidate_pair.blocking_signals:
            matched_keys = candidate_pair.blocking_signals.get("matched_keys", [])
            strategies = candidate_pair.blocking_signals.get("strategies", [])
            if matched_keys:
                add_evidence(
                    ev_type="blocking_context",
                    polarity=EvidencePolarity.NEUTRAL,
                    desc=f"Candidate generated via blocking rules: {list(strategies)} with shared keys {list(matched_keys)[:3]} (indexing context, not proof of identity)",
                    strength=0.0,
                    meta={"strategies": list(strategies), "matched_keys": list(matched_keys)},
                )

        summary_meta = {
            "left_name": raw_l,
            "right_name": raw_r,
            "normalized_name": norm_l if norm_l == norm_r else f"{norm_l} / {norm_r}",
            "name_similarity": round(name_sim, 4),
            "attribute_agreement": round(attr_agreement, 4),
            "attribute_contradiction": round(attr_conflict, 4),
            "is_alias_match": is_alias,
            "has_discriminator_conflict": has_discrim,
            "has_venue_discriminator_conflict": has_venue_conflict,
            "has_fatal_contradiction": has_fatal_contradiction,
        }

        return ComparisonResult(
            candidate_pair_id=pair_id,
            left_record_id=l_id,
            right_record_id=r_id,
            entity_type_compatible=True,
            name_similarity=name_sim,
            attribute_agreement_score=attr_agreement,
            attribute_contradiction_score=attr_conflict,
            has_fatal_contradiction=has_fatal_contradiction,
            evidence_items=tuple(evidence_list),
            summary_metadata=summary_meta,
        )

    def _compare_names(
        self,
        left: Record,
        right: Record,
        norm_l: str,
        norm_r: str,
        add_evidence,
    ) -> Tuple[float, bool, bool]:
        """Compares names using exact, permutation, acronym, fuzzy, discriminator, and alias signals."""
        raw_l = left.raw_name
        raw_r = right.raw_name

        # 1. Alias check (from known_aliases or record payload)
        is_alias = self._check_alias(left, right, norm_l, norm_r)
        if is_alias:
            add_evidence(
                ev_type="name_alias_match",
                polarity=EvidencePolarity.SUPPORTING,
                desc=f"Known alias link recognized between '{raw_l}' and '{raw_r}'",
                strength=0.95,
                meta={"left_name": raw_l, "right_name": raw_r},
            )
            return 0.95, True, False

        # 2. Exact normalized match
        if norm_l == norm_r:
            add_evidence(
                ev_type="name_exact_match",
                polarity=EvidencePolarity.SUPPORTING,
                desc=f"Exact normalized name match: '{norm_l}'",
                strength=1.0,
                meta={"name": norm_l},
            )
            return 1.0, False, False

        # 2b. Organization / business name normalization match
        biz_l = normalize_business_name(raw_l)
        biz_r = normalize_business_name(raw_r)
        if (left.entity_type == EntityType.ORGANIZATION or right.entity_type == EntityType.ORGANIZATION) and biz_l and biz_r:
            if biz_l == biz_r:
                add_evidence(
                    ev_type="name_business_normalized_match",
                    polarity=EvidencePolarity.SUPPORTING,
                    desc=f"Business-normalized name match: '{biz_l}'",
                    strength=0.98,
                    meta={"business_name": biz_l},
                )
                return 0.98, False, False

        # 3. Name order fingerprint match
        fp_l = name_fingerprint(norm_l)
        fp_r = name_fingerprint(norm_r)
        if fp_l and fp_r and fp_l == fp_r:
            add_evidence(
                ev_type="name_order_match",
                polarity=EvidencePolarity.SUPPORTING,
                desc=f"Name token order permutation match: '{norm_l}' and '{norm_r}' share fingerprint '{fp_l}'",
                strength=0.92,
                meta={"fingerprint": fp_l},
            )
            return 0.92, False, False

        if biz_l and biz_r:
            fp_biz_l = name_fingerprint(biz_l)
            fp_biz_r = name_fingerprint(biz_r)
            if fp_biz_l and fp_biz_r and fp_biz_l == fp_biz_r:
                add_evidence(
                    ev_type="name_order_match",
                    polarity=EvidencePolarity.SUPPORTING,
                    desc=f"Business name token order permutation match: '{biz_l}' and '{biz_r}' share fingerprint '{fp_biz_l}'",
                    strength=0.92,
                    meta={"fingerprint": fp_biz_l},
                )
                return 0.92, False, False

        # 4. Acronym / abbreviation match (e.g. IBM <-> International Business Machines)
        init_l = extract_initials(norm_l)
        init_r = extract_initials(norm_r)
        if (init_l and len(init_l) >= 2 and init_l == norm_r) or (init_r and len(init_r) >= 2 and init_r == norm_l):
            add_evidence(
                ev_type="name_acronym_match",
                polarity=EvidencePolarity.SUPPORTING,
                desc=f"Acronym / initials match between '{raw_l}' and '{raw_r}'",
                strength=0.95,
                meta={"left_initials": init_l, "right_initials": init_r},
            )
            return 0.95, False, False

        # 5. Discriminator conflict detection (e.g. Employee A vs Employee B)
        all_toks_l = tokenize_name(norm_l, min_length=1)
        all_toks_r = tokenize_name(norm_r, min_length=1)
        diff_l = [t for t in all_toks_l if t not in set(all_toks_r)]
        diff_r = [t for t in all_toks_r if t not in set(all_toks_l)]

        discrim_set = {"jr", "sr", "ii", "iii", "iv", "v"}
        def is_discrim(tok: str) -> bool:
            return len(tok) == 1 or tok.isdigit() or tok in discrim_set

        if diff_l and diff_r:
            discrims_l = [t for t in diff_l if is_discrim(t)]
            discrims_r = [t for t in diff_r if is_discrim(t)]
            if discrims_l and discrims_r:
                is_initial_expansion = any(
                    (len(dl) == 1 and dr.startswith(dl)) or (len(dr) == 1 and dl.startswith(dr))
                    for dl in discrims_l for dr in diff_r
                )
                if not is_initial_expansion:
                    add_evidence(
                        ev_type="name_discriminator_conflict",
                        polarity=EvidencePolarity.CONTRADICTING,
                        desc=f"Conflicting discriminator identifiers in name: '{discrims_l}' vs '{discrims_r}'",
                        strength=0.90,
                        meta={"left_discriminators": discrims_l, "right_discriminators": discrims_r},
                    )
                    return 0.20, False, True

        # 6. Initial + Surname match (e.g. Bruce Wayne vs B. Wayne)
        if len(all_toks_l) >= 2 and len(all_toks_r) >= 2:
            shared = set(all_toks_l) & set(all_toks_r)
            if len(shared) >= 1:
                rem_l = [t for t in all_toks_l if t not in shared]
                rem_r = [t for t in all_toks_r if t not in shared]
                if rem_l and rem_r and len(rem_l) == 1 and len(rem_r) == 1:
                    tl, tr = rem_l[0], rem_r[0]
                    if tl[0] == tr[0] and (len(tl) == 1 or len(tr) == 1):
                        add_evidence(
                            ev_type="name_initial_surname_match",
                            polarity=EvidencePolarity.SUPPORTING,
                            desc=f"Initial and surname agreement: '{norm_l}' and '{norm_r}' share token '{list(shared)[0]}' and initial '{tl[0]}'",
                            strength=0.92,
                            meta={"shared_tokens": list(shared), "initial": tl[0]},
                        )
                        return 0.92, False, False

        # 7. Token containment and overlap
        toks_l = tokenize_name(norm_l, min_length=2)
        toks_r = tokenize_name(norm_r, min_length=2)
        containment = token_containment(toks_l, toks_r)
        jaccard = token_jaccard_similarity(toks_l, toks_r)

        # Also evaluate business-normalized tokens if available
        biz_toks_l = tokenize_name(biz_l, min_length=2) if biz_l else []
        biz_toks_r = tokenize_name(biz_r, min_length=2) if biz_r else []
        biz_containment = token_containment(biz_toks_l, biz_toks_r) if biz_toks_l and biz_toks_r else 0.0
        effective_containment = max(containment, biz_containment)

        # 8. Character-level Jaro-Winkler similarity
        jw_sim = jaro_winkler_similarity(norm_l, norm_r)
        if biz_l and biz_r:
            jw_sim = max(jw_sim, jaro_winkler_similarity(biz_l, biz_r))

        # 9. Phonetic Soundex check
        soundex_l = {soundex(t) for t in toks_l if soundex(t)}
        soundex_r = {soundex(t) for t in toks_r if soundex(t)}
        soundex_shared = soundex_l & soundex_r

        # Determine composite name score
        if jw_sim >= 0.92:
            add_evidence(
                ev_type="name_spelling_similarity",
                polarity=EvidencePolarity.SUPPORTING,
                desc=f"High character-level name similarity (Jaro-Winkler: {jw_sim:.3f}): '{norm_l}' vs '{norm_r}'",
                strength=jw_sim * 0.90,
                meta={"jaro_winkler": round(jw_sim, 4), "soundex_shared": list(soundex_shared)},
            )
            return jw_sim, False, False

        if effective_containment >= 0.80 and (
            (len(toks_l) >= 1 and len(toks_r) >= 1) or (len(biz_toks_l) >= 1 and len(biz_toks_r) >= 1)
        ):
            effective_sim = max(
                jw_sim,
                0.88 if effective_containment >= 0.80 and (len(toks_l) >= 2 or len(biz_toks_l) >= 2) else 0.85
            )
            add_evidence(
                ev_type="name_token_containment",
                polarity=EvidencePolarity.SUPPORTING,
                desc=f"Significant token overlap / containment ({effective_containment:.2f}): '{norm_l}' vs '{norm_r}'",
                strength=effective_sim * 0.85,
                meta={"containment": effective_containment, "jaccard": jaccard, "shared_tokens": list(set(toks_l) & set(toks_r))},
            )
            return effective_sim, False, False

        if jw_sim >= 0.75:
            add_evidence(
                ev_type="name_moderate_similarity",
                polarity=EvidencePolarity.SUPPORTING,
                desc=f"Moderate name similarity (Jaro-Winkler: {jw_sim:.3f}): '{norm_l}' vs '{norm_r}'",
                strength=jw_sim * 0.60,
                meta={"jaro_winkler": round(jw_sim, 4)},
            )
            return jw_sim, False, False

        # Low similarity: contradictory evidence
        add_evidence(
            ev_type="name_dissimilarity",
            polarity=EvidencePolarity.CONTRADICTING,
            desc=f"Low name similarity (Jaro-Winkler: {jw_sim:.3f}): '{norm_l}' vs '{norm_r}'",
            strength=(1.0 - jw_sim) * 0.75,
            meta={"jaro_winkler": round(jw_sim, 4)},
        )
        return jw_sim, False, False

    def _check_alias(self, left: Record, right: Record, norm_l: str, norm_r: str) -> bool:
        """Inspects configured known_aliases and record payload alias structures."""
        # Check configured alias dictionary
        if norm_l in self.known_aliases and norm_r in self.known_aliases[norm_l]:
            return True
        if norm_r in self.known_aliases and norm_l in self.known_aliases[norm_r]:
            return True

        # Check structured_attributes / raw_payload 'aliases' fields
        for rec, target_norm in [(left, norm_r), (right, norm_l)]:
            raw_aliases = rec.structured_attributes.get("aliases") or rec.raw_payload.get("aliases")
            if raw_aliases:
                if isinstance(raw_aliases, str):
                    raw_aliases = [raw_aliases]
                if isinstance(raw_aliases, (list, tuple, set)):
                    for a in raw_aliases:
                        if normalize_text(str(a)) == target_norm:
                            return True
        return False

    def _compare_attributes(self, left: Record, right: Record, add_evidence) -> Tuple[float, float, bool, bool]:
        """
        Compares structured attributes, calculating agreement, contradiction, and fatal conflicts.
        """
        agreement_points = 0.0
        contradiction_points = 0.0
        has_fatal_conflict = False
        has_same_address = False
        has_venue_conflict = False

        left_attrs = dict(left.structured_attributes)
        right_attrs = dict(right.structured_attributes)

        # Merge in any normalized_attributes not in structured
        for k, v in left.normalized_attributes.items():
            left_attrs.setdefault(k, v)
        for k, v in right.normalized_attributes.items():
            right_attrs.setdefault(k, v)

        all_keys = set(left_attrs.keys()) | set(right_attrs.keys())

        for attr in sorted(all_keys):
            has_l = attr in left_attrs and left_attrs[attr] is not None
            has_r = attr in right_attrs and right_attrs[attr] is not None

            # 1. Missing attributes
            if not has_l or not has_r:
                present_side = "left" if has_l else "right"
                add_evidence(
                    ev_type="attribute_missing",
                    polarity=EvidencePolarity.NEUTRAL,
                    desc=f"Attribute '{attr}' is missing on the {'right' if has_l else 'left'} record",
                    strength=0.0,
                    meta={"attribute": attr, "present_on": present_side},
                )
                continue

            val_l_norm = normalize_attribute_value(left_attrs[attr])
            val_r_norm = normalize_attribute_value(right_attrs[attr])

            if not val_l_norm or not val_r_norm:
                add_evidence(
                    ev_type="attribute_empty",
                    polarity=EvidencePolarity.NEUTRAL,
                    desc=f"Attribute '{attr}' evaluates to empty value after normalization",
                    strength=0.0,
                    meta={"attribute": attr},
                )
                continue

            is_match = (val_l_norm == val_r_norm)

            # 2. Immutable biographical / legal identifiers (DOB, SSN, Tax ID, National ID)
            if attr in self.IMMUTABLE_IDENTIFIERS:
                if is_match:
                    strength = 0.90 if attr == "dob" else 0.95
                    agreement_points += strength
                    add_evidence(
                        ev_type=f"high_value_agreement_{attr}",
                        polarity=EvidencePolarity.SUPPORTING,
                        desc=f"High-value identifier '{attr}' matches exactly: '{val_l_norm}'",
                        strength=strength,
                        meta={"attribute": attr, "value": val_l_norm},
                    )
                else:
                    strength = 0.95
                    contradiction_points += strength
                    has_fatal_conflict = True
                    add_evidence(
                        ev_type=f"high_value_conflict_{attr}",
                        polarity=EvidencePolarity.CONTRADICTING,
                        desc=f"Conflicting high-value identifier '{attr}': '{val_l_norm}' vs '{val_r_norm}'",
                        strength=strength,
                        meta={"attribute": attr, "left_value": val_l_norm, "right_value": val_r_norm},
                    )
                continue

            # 3. Contact identifiers (phone, email)
            if attr in self.CONTACT_IDENTIFIERS:
                if is_match:
                    strength = 0.85
                    agreement_points += strength
                    add_evidence(
                        ev_type=f"contact_agreement_{attr}",
                        polarity=EvidencePolarity.SUPPORTING,
                        desc=f"Contact identifier '{attr}' matches: '{val_l_norm}'",
                        strength=strength,
                        meta={"attribute": attr, "value": val_l_norm},
                    )
                else:
                    strength = 0.35
                    contradiction_points += strength
                    add_evidence(
                        ev_type=f"contact_divergence_{attr}",
                        polarity=EvidencePolarity.CONTRADICTING,
                        desc=f"Contact identifier '{attr}' differs: '{val_l_norm}' vs '{val_r_norm}' (may reflect multiple contact channels)",
                        strength=strength,
                        meta={"attribute": attr, "left_value": val_l_norm, "right_value": val_r_norm},
                    )
                continue

            # 4. Advanced Attribute Reasoning (Enabled in Production Mode)
            if self.enable_advanced_normalization:
                # Address attributes
                if attr in {"address", "street_address", "addr"}:
                    na_l = normalize_address(val_l_norm)
                    na_r = normalize_address(val_r_norm)
                    num_l, st_l = extract_address_components(na_l)
                    num_r, st_r = extract_address_components(na_r)

                    if num_l and num_r and num_l != num_r:
                        strength = 0.55
                        contradiction_points += strength
                        add_evidence(
                            ev_type=f"address_building_conflict_{attr}",
                            polarity=EvidencePolarity.CONTRADICTING,
                            desc=f"Conflicting building number in address '{attr}': '{num_l}' vs '{num_r}'",
                            strength=strength,
                            meta={"attribute": attr, "left_building": num_l, "right_building": num_r},
                        )
                    elif na_l == na_r:
                        strength = 0.50
                        agreement_points += strength
                        has_same_address = True
                        add_evidence(
                            ev_type=f"context_agreement_{attr}",
                            polarity=EvidencePolarity.SUPPORTING,
                            desc=f"Normalized street address matches exactly: '{na_l}'",
                            strength=strength,
                            meta={"attribute": attr, "address": na_l},
                        )
                    elif num_l and num_r and num_l == num_r and st_l and st_r and (st_l == st_r or st_l in st_r or st_r in st_l):
                        strength = 0.40
                        agreement_points += strength
                        has_same_address = True
                        add_evidence(
                            ev_type=f"context_agreement_{attr}",
                            polarity=EvidencePolarity.SUPPORTING,
                            desc=f"Matching building number '{num_l}' with compatible street '{st_l}' / '{st_r}'",
                            strength=strength,
                            meta={"attribute": attr, "building": num_l, "left_street": st_l, "right_street": st_r},
                        )
                    else:
                        asim = jaro_winkler_similarity(na_l, na_r)
                        if asim >= 0.85:
                            strength = 0.30
                            agreement_points += strength
                            has_same_address = True
                            add_evidence(
                                ev_type=f"context_agreement_{attr}",
                                polarity=EvidencePolarity.SUPPORTING,
                                desc=f"Similar street address (Jaro-Winkler {asim:.2f}): '{na_l}' vs '{na_r}'",
                                strength=strength,
                                meta={"attribute": attr, "left_address": na_l, "right_address": na_r, "similarity": asim},
                            )
                        else:
                            strength = 0.25
                            contradiction_points += strength
                            add_evidence(
                                ev_type=f"context_divergence_{attr}",
                                polarity=EvidencePolarity.CONTRADICTING,
                                desc=f"Conflicting street address: '{na_l}' vs '{na_r}'",
                                strength=strength,
                                meta={"attribute": attr, "left_address": na_l, "right_address": na_r},
                            )
                    continue

                # City attribute
                if attr == "city":
                    nc_l = normalize_city(val_l_norm)
                    nc_r = normalize_city(val_r_norm)
                    if nc_l == nc_r:
                        strength = 0.25
                        agreement_points += strength
                        add_evidence(
                            ev_type="context_agreement_city",
                            polarity=EvidencePolarity.SUPPORTING,
                            desc=f"City matches: '{nc_l}'",
                            strength=strength,
                            meta={"attribute": "city", "value": nc_l},
                        )
                    else:
                        is_metro = any(nc_l in cluster and nc_r in cluster for cluster in METRO_CLUSTERS.values())
                        if is_metro:
                            strength = 0.15
                            agreement_points += strength
                            add_evidence(
                                ev_type="context_agreement_city_metro",
                                polarity=EvidencePolarity.SUPPORTING,
                                desc=f"Cities '{nc_l}' and '{nc_r}' belong to the same metropolitan cluster",
                                strength=strength,
                                meta={"attribute": "city", "left_city": nc_l, "right_city": nc_r},
                            )
                        else:
                            strength = 0.25
                            contradiction_points += strength
                            add_evidence(
                                ev_type="context_divergence_city",
                                polarity=EvidencePolarity.CONTRADICTING,
                                desc=f"Conflicting city: '{nc_l}' vs '{nc_r}'",
                                strength=strength,
                                meta={"attribute": "city", "left_city": nc_l, "right_city": nc_r},
                            )
                    continue

                # Subjective directory taxonomy (cuisine, type, category)
                if attr in {"cuisine", "type", "category"}:
                    if val_l_norm == val_r_norm:
                        strength = 0.20
                        agreement_points += strength
                        add_evidence(
                            ev_type=f"context_agreement_{attr}",
                            polarity=EvidencePolarity.SUPPORTING,
                            desc=f"Directory classification '{attr}' matches: '{val_l_norm}'",
                            strength=strength,
                            meta={"attribute": attr, "value": val_l_norm},
                        )
                    elif set(tokenize_name(val_l_norm)) & set(tokenize_name(val_r_norm)):
                        strength = 0.15
                        agreement_points += strength
                        add_evidence(
                            ev_type=f"taxonomy_overlap_{attr}",
                            polarity=EvidencePolarity.SUPPORTING,
                            desc=f"Directory classification '{attr}' shares keywords: '{val_l_norm}' vs '{val_r_norm}'",
                            strength=strength,
                            meta={"attribute": attr, "left_value": val_l_norm, "right_value": val_r_norm},
                        )
                    else:
                        strength = 0.05
                        contradiction_points += strength
                        add_evidence(
                            ev_type=f"taxonomy_divergence_{attr}",
                            polarity=EvidencePolarity.CONTRADICTING,
                            desc=f"Directory classification '{attr}' differs: '{val_l_norm}' vs '{val_r_norm}' (subjective directory taxonomy)",
                            strength=strength,
                            meta={"attribute": attr, "left_value": val_l_norm, "right_value": val_r_norm},
                        )
                    continue

            # Standard Contextual attributes (fallback or default mode)
            weight = self.CONTEXTUAL_ATTRIBUTES.get(attr, 0.20)
            if is_match:
                agreement_points += weight
                if attr in {"address", "street_address", "addr"}:
                    has_same_address = True
                add_evidence(
                    ev_type=f"context_agreement_{attr}",
                    polarity=EvidencePolarity.SUPPORTING,
                    desc=f"Contextual attribute '{attr}' matches: '{val_l_norm}'",
                    strength=weight,
                    meta={"attribute": attr, "value": val_l_norm},
                )
            else:
                divergence_strength = 0.60 if attr in {"occupation", "role"} else weight
                contradiction_points += divergence_strength
                add_evidence(
                    ev_type=f"context_divergence_{attr}",
                    polarity=EvidencePolarity.CONTRADICTING,
                    desc=f"Contextual attribute '{attr}' differs: '{val_l_norm}' vs '{val_r_norm}'",
                    strength=divergence_strength,
                    meta={"attribute": attr, "left_value": val_l_norm, "right_value": val_r_norm},
                )

        # Check sub-venue conflict if addresses match and enabled
        if self.detect_venue_conflicts and has_same_address and detect_venue_discriminator_conflict(left.raw_name, right.raw_name):
            has_venue_conflict = True
            strength = 0.70
            contradiction_points += strength
            add_evidence(
                ev_type="venue_discriminator_conflict",
                polarity=EvidencePolarity.CONTRADICTING,
                desc=f"Distinct sub-venues operating at shared address/facility: '{left.raw_name}' vs '{right.raw_name}'",
                strength=strength,
                meta={"left_name": left.raw_name, "right_name": right.raw_name},
            )

        return agreement_points, contradiction_points, has_fatal_conflict, has_venue_conflict
