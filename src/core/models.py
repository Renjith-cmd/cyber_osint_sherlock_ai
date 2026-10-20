from enum import Enum
from types import MappingProxyType
from typing import List, Optional, Any, Dict, Mapping, Tuple, Set
from datetime import datetime, date, time, timezone
from uuid import UUID
from pydantic import BaseModel, Field, model_validator, field_validator, model_serializer, ConfigDict

class EntityType(str, Enum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"
    POLITICAL_PARTY = "POLITICAL_PARTY"
    GOVERNMENT_BODY = "GOVERNMENT_BODY"
    CONCEPT = "CONCEPT"
    EVENT = "EVENT"
    PRODUCT = "PRODUCT"
    LAW_STATUTE = "LAW_STATUTE"
    LEGAL_CASE = "LEGAL_CASE"
    FINANCIAL_INSTRUMENT = "FINANCIAL_INSTRUMENT"
    DATE = "DATE"
    MONEY = "MONEY"

class EvidencePolarity(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    NEUTRAL = "NEUTRAL"

class DecisionType(str, Enum):
    MATCH = "MATCH"
    NON_MATCH = "NON_MATCH"
    REVIEW = "REVIEW"

class SourceType(str, Enum):
    URL = "URL"
    DOCUMENT = "DOCUMENT"
    API = "API"
    USER = "USER"
    OTHER = "OTHER"

class ClusterStatus(str, Enum):
    ACTIVE = "active"
    PROVISIONAL = "provisional"
    MERGED = "merged"
    SPLIT = "split"
    ARCHIVED = "archived"

class ReviewStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"

class RelationshipEpistemicTier(str, Enum):
    ASSERTED = "ASSERTED"
    DENIED = "DENIED"
    QUOTED = "QUOTED"
    INFERRED = "INFERRED"
    DISPUTED = "DISPUTED"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"

class ConfidenceSemantics(str, Enum):
    HEURISTIC_SCORE = "HEURISTIC_SCORE"
    UNCALIBRATED_MODEL = "UNCALIBRATED_MODEL"
    CALIBRATED_PROBABILITY = "CALIBRATED_PROBABILITY"
    HUMAN_AFFIRMED = "HUMAN_AFFIRMED"

# ---------------------------------------------------------------------------
# Maintainable Deep Immutability via Python Standard Library Types
# ---------------------------------------------------------------------------

SUPPORTED_PRIMITIVES = (str, int, float, bool, type(None), datetime, date, time, bytes, UUID, Enum, BaseModel)

def freeze(val: Any, seen: Optional[Set[int]] = None) -> Any:
    """
    Recursively converts mutable mappings and sequences to standard immutable types:
    - dict / Mapping / MappingProxyType -> types.MappingProxyType (fresh copy)
    - list / tuple                      -> tuple (immutable sequence)
    - set / frozenset                   -> frozenset (immutable set)

    Guarantees:
    1. Input aliasing protection: Always deep-copies mapping contents, even if
       the input is already a MappingProxyType, ensuring externally retained
       underlying dictionaries cannot bypass immutability.
    2. Cycle protection: Detects cyclic container references and raises ValueError.
    3. Strict payload validation: Unsupported mutable objects (custom classes,
       bytearrays, etc.) raise TypeError to prevent unverified mutable state.
    """
    if isinstance(val, SUPPORTED_PRIMITIVES):
        return val

    if seen is None:
        seen = set()

    val_id = id(val)
    if val_id in seen:
        raise ValueError("Cyclic reference detected in payload; payloads must be acyclic.")

    # Mappings (including dict, Mapping, and MappingProxyType)
    if isinstance(val, (dict, Mapping)):
        seen.add(val_id)
        try:
            frozen_dict = {
                k: freeze(v, seen)
                for k, v in val.items()
            }
            return MappingProxyType(frozen_dict)
        finally:
            seen.remove(val_id)

    # Sequences (list, tuple)
    elif isinstance(val, (list, tuple)):
        seen.add(val_id)
        try:
            return tuple(freeze(v, seen) for v in val)
        finally:
            seen.remove(val_id)

    # Sets (set, frozenset)
    elif isinstance(val, (set, frozenset)):
        seen.add(val_id)
        try:
            return frozenset(freeze(v, seen) for v in val)
        finally:
            seen.remove(val_id)

    raise TypeError(
        f"Unsupported payload value of type {type(val).__name__}: "
        "only JSON-compatible primitives, datetimes, enums, and container types (mappings, sequences, sets) are allowed."
    )

def unfreeze(val: Any) -> Any:
    """
    Recursively converts immutable views back to standard JSON-compatible Python structures:
    - MappingProxyType -> dict
    - tuple            -> list
    - frozenset        -> list
    """
    if isinstance(val, (MappingProxyType, dict, Mapping)):
        return {k: unfreeze(v) for k, v in val.items()}
    elif isinstance(val, (tuple, list)):
        return [unfreeze(v) for v in val]
    elif isinstance(val, (frozenset, set)):
        return [unfreeze(v) for v in sorted(val, key=str)]
    elif isinstance(val, BaseModel):
        return unfreeze(val.model_dump())
    return val

def _validate_non_empty_str(val: str, field_name: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"{field_name} must be a non-empty, non-whitespace string")
    return val

class ImmutableBaseModel(BaseModel):
    """
    Base model enforcing:
    1. Top-level field immutability via ConfigDict(frozen=True).
    2. Deep nested immutability via MappingProxyType and tuple conversion.
    3. Input aliasing protection by deep-converting incoming data.
    4. Plain JSON-compatible serialization via @model_serializer(mode="plain").
    """
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    @model_validator(mode="after")
    def _deep_freeze(self) -> "ImmutableBaseModel":
        for field_name in self.__class__.model_fields:
            val = getattr(self, field_name)
            frozen_val = freeze(val)
            if frozen_val is not val:
                object.__setattr__(self, field_name, frozen_val)
        return self

    @model_serializer(mode="plain")
    def _serialize_model(self) -> Dict[str, Any]:
        """Ensures dumped dictionaries and JSON strings output clean native containers."""
        return {k: unfreeze(getattr(self, k)) for k in self.__class__.model_fields}

# ---------------------------------------------------------------------------
# Domain Models
# ---------------------------------------------------------------------------

class Source(ImmutableBaseModel):
    source_id: str
    source_type: SourceType
    source_name: str
    source_uri: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    reliability_metadata: Dict[str, Any] = Field(default_factory=dict)
    provenance_metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id", "source_name")
    @classmethod
    def _validate_ids(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

class Record(ImmutableBaseModel):
    record_id: str
    source_id: str
    entity_type: EntityType
    raw_name: str
    normalized_attributes: Dict[str, Any] = Field(default_factory=dict)
    structured_attributes: Dict[str, Any] = Field(default_factory=dict)
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    observed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("record_id", "source_id", "raw_name")
    @classmethod
    def _validate_ids(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

    @property
    def identifiers(self) -> Dict[str, Any]:
        if "_identifiers_dict" not in self.__dict__:
            object.__setattr__(self, "_identifiers_dict", dict(self.structured_attributes.get("identifiers") or {}))
        return self.__dict__["_identifiers_dict"]

    @property
    def document_id(self) -> str:
        doc_id = self.raw_payload.get("document_id") or self.structured_attributes.get("document_id")
        if doc_id:
            return str(doc_id)
        if self.source_id.startswith("doc_"):
            return self.source_id[4:]
        return self.source_id



class CandidatePair(ImmutableBaseModel):
    candidate_id: str
    left_record_id: str
    right_record_id: str
    generation_method: str
    blocking_signals: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_pair(cls, data: Any) -> Any:
        if isinstance(data, dict):
            left = data.get("left_record_id")
            right = data.get("right_record_id")
            if isinstance(left, str) and isinstance(right, str):
                if left.strip() > right.strip():
                    data["left_record_id"], data["right_record_id"] = right, left
        return data

    @field_validator("candidate_id", "left_record_id", "right_record_id", "generation_method")
    @classmethod
    def _validate_ids(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

    @model_validator(mode="after")
    def check_not_self_pair(self):
        if self.left_record_id == self.right_record_id:
            raise ValueError("CandidatePair cannot contain identical record IDs")
        return self

    @property
    def canonical_pair_key(self) -> str:
        return f"{self.left_record_id}::{self.right_record_id}"

class Evidence(ImmutableBaseModel):
    evidence_id: str
    evidence_type: str
    polarity: EvidencePolarity = EvidencePolarity.SUPPORTING
    value_description: str = ""
    content: Optional[str] = None
    content_reference: Optional[str] = None
    source_id: Optional[str] = None
    source_record_id: Optional[str] = None
    source_reference: Optional[str] = None
    record_reference: Optional[str] = None
    source_uri: Optional[str] = None
    document_reference: Optional[str] = None
    publication_time: Optional[datetime] = None
    observed_at: Optional[datetime] = None
    ingested_at: Optional[datetime] = None
    extraction_method: Optional[str] = None
    extractor_version: Optional[str] = None
    text_span: Optional[str] = None
    page_number: Optional[int] = None
    char_offsets: Optional[Tuple[int, int]] = None
    field_path: Optional[str] = None
    content_hash: Optional[str] = None
    provenance_links: List[str] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    provenance: str = ""
    strength: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_evidence_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync source_id and source_reference
            src_ref = data.get("source_reference")
            src_id = data.get("source_id")
            if src_ref and not src_id:
                data["source_id"] = src_ref
            elif src_id and not src_ref:
                data["source_reference"] = src_id

            # Sync record_reference and source_record_id
            rec_ref = data.get("record_reference")
            rec_id = data.get("source_record_id")
            if rec_ref and not rec_id:
                data["source_record_id"] = rec_ref
            elif rec_id and not rec_ref:
                data["record_reference"] = rec_id

            # Sync value_description and content
            content = data.get("content")
            val_desc = data.get("value_description")
            if not val_desc:
                if content:
                    data["value_description"] = str(content)
                elif "evidence_type" in data:
                    data["value_description"] = str(data["evidence_type"])
            elif not content:
                data["content"] = val_desc

            # Normalize polarity strings like 'positive' / 'negative'
            pol = data.get("polarity")
            if isinstance(pol, str):
                p_norm = pol.strip().upper()
                if p_norm in ("POSITIVE", "SUPPORTING", "CONFIRMING"):
                    data["polarity"] = EvidencePolarity.SUPPORTING
                elif p_norm in ("NEGATIVE", "CONTRADICTING", "DENYING", "REFUTING"):
                    data["polarity"] = EvidencePolarity.CONTRADICTING
                elif p_norm in ("NEUTRAL", "UNCERTAIN"):
                    data["polarity"] = EvidencePolarity.NEUTRAL


            # Derive provenance if missing but contextual source metadata exists
            prov = data.get("provenance")
            if prov is None:
                if data.get("extraction_method"):
                    data["provenance"] = f"extraction:{data['extraction_method']}"
                elif data.get("source_uri"):
                    data["provenance"] = f"source:{data['source_uri']}"
                elif data.get("source_id"):
                    data["provenance"] = f"source:{data['source_id']}"
                elif data.get("document_reference"):
                    data["provenance"] = f"document:{data['document_reference']}"
        return data

    @field_validator("evidence_id", "evidence_type", "value_description")
    @classmethod
    def _validate_strings(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

    @field_validator("strength")
    @classmethod
    def _validate_strength(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("Evidence strength must be between 0.0 and 1.0")
        return v

    @model_validator(mode="after")
    def check_provenance(self):
        if not self.provenance or not self.provenance.strip():
            raise ValueError("Evidence must have provenance")
        return self

class MatchDecision(ImmutableBaseModel):
    candidate_pair_id: str
    decision: DecisionType
    score: Optional[float] = None
    threshold: Optional[float] = None
    model_version: str
    evidence_references: List[str] = Field(default_factory=list)
    explanation_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("candidate_pair_id", "model_version")
    @classmethod
    def _validate_strings(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

    @field_validator("score", "threshold")
    @classmethod
    def _validate_scores(cls, v: Optional[float], info) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"{info.field_name} must be between 0.0 and 1.0")
        return v

class EntityCluster(ImmutableBaseModel):
    entity_cluster_id: str
    entity_type: EntityType
    member_record_ids: List[str]
    status: ClusterStatus
    quality_confidence_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    derivation_version: str

    @field_validator("entity_cluster_id", "derivation_version")
    @classmethod
    def _validate_strings(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status_str(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_lower = v.strip().lower()
            for cs in ClusterStatus:
                if cs.value == v_lower:
                    return cs
            raise ValueError(f"Invalid cluster status: {v}. Must be one of {[s.value for s in ClusterStatus]}")
        return v

    @model_validator(mode="after")
    def check_cluster_members(self):
        if not self.member_record_ids or len(self.member_record_ids) == 0:
            raise ValueError("EntityCluster must contain at least one member record ID")
        for mid in self.member_record_ids:
            _validate_non_empty_str(mid, "member_record_id")
        if len(self.member_record_ids) != len(set(self.member_record_ids)):
            raise ValueError("EntityCluster cannot contain duplicate record IDs")
        return self

class InvestigationEntity(ImmutableBaseModel):
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    member_record_ids: List[str] = Field(default_factory=list)
    cluster_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("entity_id", "canonical_name")
    @classmethod
    def _validate_ids(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

class ClaimCorrection(ImmutableBaseModel):
    correction_id: str
    corrected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    corrected_by: str
    previous_status: ReviewStatus
    new_status: ReviewStatus
    rationale: str
    previous_claim_id: Optional[str] = None
    replacement_claim_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("correction_id", "corrected_by", "rationale")
    @classmethod
    def _validate_strings(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

class Claim(ImmutableBaseModel):
    claim_id: str
    subject_id: str
    predicate: str
    object_id: str
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    location: Optional[str] = None
    qualifiers: Dict[str, Any] = Field(default_factory=dict)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    contradicting_evidence_ids: List[str] = Field(default_factory=list)
    extraction_method: str = "manual"
    extractor_version: Optional[str] = None
    confidence: Optional[float] = None
    confidence_semantics: ConfidenceSemantics = ConfidenceSemantics.HEURISTIC_SCORE
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    superseded_by_claim_id: Optional[str] = None
    retraction_reason: Optional[str] = None
    correction_history: List[ClaimCorrection] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("claim_id", "subject_id", "predicate", "object_id")
    @classmethod
    def _validate_strings(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("Claim confidence must be between 0.0 and 1.0")
        return v

    @model_validator(mode="after")
    def _validate_lifecycle_consistency(self):
        if self.review_status == ReviewStatus.SUPERSEDED and not self.superseded_by_claim_id:
            raise ValueError("SUPERSEDED claim must specify superseded_by_claim_id")
        if self.review_status == ReviewStatus.RETRACTED and not self.retraction_reason:
            raise ValueError("RETRACTED claim must specify retraction_reason")
        return self

class Relationship(ImmutableBaseModel):
    relationship_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    is_directed: bool = True
    epistemic_tier: RelationshipEpistemicTier = RelationshipEpistemicTier.ASSERTED
    supporting_claim_ids: List[str] = Field(default_factory=list)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    contradicting_claim_ids: List[str] = Field(default_factory=list)
    contradicting_evidence_ids: List[str] = Field(default_factory=list)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    provenance: str = "derived_from_claims"
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    confidence: Optional[float] = None
    confidence_semantics: ConfidenceSemantics = ConfidenceSemantics.HEURISTIC_SCORE
    polarity: str = "POSITIVE"
    attribution: Optional[str] = None
    unique_source_hashes: List[str] = Field(default_factory=list)
    duplicate_evidence_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("relationship_id", "source_entity_id", "target_entity_id", "relationship_type")
    @classmethod
    def _validate_strings(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("Relationship confidence must be between 0.0 and 1.0")
        return v
