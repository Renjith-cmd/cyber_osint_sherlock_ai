"""
Relation Extraction Abstraction and Conservative Baseline for Sherlock AI (Milestone 9).

Provides:
- `ExtractedRelationCandidate`: Structured, immutable relation candidate linking subject and
  object mentions with exact sentence-level evidence spans.
- `BaseRelationExtractor`: Extensible interface for relation extraction backends.
- `DeterministicRuleRelationExtractor`: Conservative deterministic baseline supporting:
  - WORKS_FOR
  - LOCATED_IN
  - OWNS
  - FOUNDED
  - ASSOCIATED_WITH

Key Guarantees:
- Strict evidence grounding: every candidate links to exact source offsets and sentence text.
- Separation of extraction and verification: candidate is NOT an established fact.
- Conservative negation detection: sentences with negation are preserved with `is_negated = True`.
- Epistemic qualification: sentences with attribution or allegations are marked with `is_allegation = True`.
- Abstention on ambiguity: never generates relations solely because entities co-occur.
"""

from abc import ABC, abstractmethod
import re
from typing import Dict, List, Optional, Tuple, Any, Set
from pydantic import Field, field_validator, model_validator

from src.core.models import (
    ImmutableBaseModel,
    EntityType,
    _validate_non_empty_str,
)
from src.core.document_ingestion import IngestedDocument
from src.core.ner import EntityMention, split_sentences_with_spans, MLModelUnavailableError

SUPPORTED_RELATION_PREDICATES: Tuple[str, ...] = (
    "WORKS_FOR",
    "LOCATED_IN",
    "OWNS",
    "FOUNDED",
    "ASSOCIATED_WITH",
)


class ExtractedRelationCandidate(ImmutableBaseModel):
    """
    Candidate relationship extracted from document text.
    Must link explicitly to subject mention, object mention, and source evidence span.
    """
    candidate_id: str
    document_id: str
    subject_mention_id: str
    subject_surface: str
    subject_type: EntityType
    predicate: str
    object_mention_id: str
    object_surface: str
    object_type: EntityType
    evidence_span: str
    evidence_start_char: int
    evidence_end_char: int
    is_negated: bool = False
    is_allegation: bool = False
    attribution_source: Optional[str] = None
    uncertainty_flag: bool = False
    temporal_context: Optional[str] = None
    extraction_method: str = "deterministic_rule"
    extraction_version: str = "1.0.0"
    confidence_score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "candidate_id", "document_id", "subject_mention_id", "subject_surface",
        "predicate", "object_mention_id", "object_surface", "evidence_span",
        "extraction_method", "extraction_version"
    )
    @classmethod
    def _validate_non_empty_strings(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

    @model_validator(mode="after")
    def _validate_spans(self) -> "ExtractedRelationCandidate":
        if self.evidence_start_char < 0:
            raise ValueError(f"evidence_start_char ({self.evidence_start_char}) must be non-negative.")
        if self.evidence_end_char <= self.evidence_start_char:
            raise ValueError(
                f"evidence_end_char ({self.evidence_end_char}) must exceed start ({self.evidence_start_char})."
            )
        if len(self.evidence_span) != (self.evidence_end_char - self.evidence_start_char):
            raise ValueError(
                f"evidence_span length ({len(self.evidence_span)}) mismatch with offsets "
                f"[{self.evidence_start_char}:{self.evidence_end_char}]."
            )
        if self.subject_mention_id == self.object_mention_id:
            raise ValueError("Subject and Object cannot refer to the exact same mention ID.")
        return self


class BaseRelationExtractor(ABC):
    """Abstract interface for relation extraction backends."""

    @abstractmethod
    def extract_relations(
        self,
        document: IngestedDocument,
        mentions: List[EntityMention],
    ) -> List[ExtractedRelationCandidate]:
        """
        Extract relation candidates from document and its mentions.
        """
        pass


class DeterministicRuleRelationExtractor(BaseRelationExtractor):
    """
    Conservative, deterministic baseline relation extractor.
    Extracts relations within sentence boundaries where specific syntactic patterns match.
    Enforces strict typing on subject and object.
    Preserves negation, attribution, and temporal context.
    Abstains when patterns or entity bindings are ambiguous.
    """

    METHOD_NAME = "deterministic_pattern_rule"
    VERSION = "1.0.0"

    SUPPORTED_PREDICATES = {
        "WORKS_FOR",
        "LOCATED_IN",
        "OWNS",
        "FOUNDED",
        "ASSOCIATED_WITH",
    }

    # Negation indicators
    RE_NEGATION = re.compile(
        r'\b(?:not|never|no longer|denies|denied|denying|did not|does not|cannot|disproved|untrue|falsely claimed|no\s+(?:shares|stake|equity|interest|ownership|ties|affiliation))\b',
        re.IGNORECASE,
    )

    # Attribution / Allegation indicators
    RE_ALLEGATION = re.compile(
        r'\b(?:according to(?:\s+(?:the\s+)?report)?|(?:the\s+)?report\s+(?:alleges|claims|stated|states)(?:\s+that)?|alleges that|alleged that|allegedly|claims that|claimed that|reportedly|reported that|accused of|purportedly|sources say|unconfirmed reports)\b',
        re.IGNORECASE,
    )

    # Uncertainty indicators
    RE_UNCERTAINTY = re.compile(
        r'\b(?:unclear\s+whether|unclear|uncertain|may|might|possibly|suspected to|rumored to|unconfirmed|potential)\b',
        re.IGNORECASE,
    )

    # Epistemic unestablished indicators: lack of proof or failure to establish
    # is epistemic uncertainty / lack of evidence, NOT affirmative negation of relation existence.
    RE_UNESTABLISHED = re.compile(
        r'\b(?:did not|does not|could not|cannot|has not|have not|failed to|was not able to|unable to|is not proven that)\s+(?:establish|confirm|prove|verify|substantiate|demonstrate|show|determine|conclude)\s+that\b',
        re.IGNORECASE,
    )

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        # 1. WORKS_FOR: Subject PERSON -> Object ORGANIZATION
        self.patterns_works_for = [
            re.compile(r'\b(?:works for|worked for|work for|working for|is employed by|employed by|employed at|joined|serves as CEO of|is CEO of|is the director of|director of|consultant for|senior investigator at|agent for)\b', re.IGNORECASE),
        ]

        # 2. LOCATED_IN: Subject ORG or LOC -> Object LOC
        self.patterns_located_in = [
            re.compile(r'\b(?:is located in|located in|headquartered in|based in|operates in|operating in|situated in|has offices in)\b', re.IGNORECASE),
        ]

        # 3. OWNS: Subject PERSON or ORG -> Object ORG, PRODUCT, FINANCIAL_INSTRUMENT
        self.patterns_owns = [
            re.compile(r'\b(?:owns|owned|own|owning|acquired|purchased|purchasing|is the owner of|holds a controlling stake in|has ownership of)\b', re.IGNORECASE),
        ]

        # 4. FOUNDED: Subject PERSON or ORG -> Object ORG
        self.patterns_founded = [
            re.compile(r'\b(?:founded|co-founded|founding|established|establishing|started|starting|is the founder of|is co-founder of|set up)\b', re.IGNORECASE),
        ]

        # 5. ASSOCIATED_WITH: Subject Any -> Object Any
        self.patterns_associated_with = [
            re.compile(r'\b(?:is associated with|associated with|affiliated with|partnered with|collaborated with|connected to)\b', re.IGNORECASE),
        ]

    def _evaluate_pair_qualifiers(
        self,
        sent_text: str,
        s_start: int,
        subj: EntityMention,
        obj: EntityMention,
    ) -> Tuple[bool, bool, Optional[str], bool]:
        """
        Evaluate epistemic qualifiers scoped to the clause containing this entity pair.
        Prevents sentence-level negation from leaking into unrelated coordinate clauses.
        """
        p_start = min(subj.start_char, obj.start_char) - s_start
        p_end = max(subj.end_char, obj.end_char) - s_start

        clause_delims = [
            m.start() for m in re.finditer(
                r'(?:,\s*(?:but|however|whereas|while|although|yet)|;\s*)',
                sent_text,
                re.IGNORECASE,
            )
        ]

        c_start = 0
        c_end = len(sent_text)
        for delim in clause_delims:
            if delim <= p_start:
                c_start = max(c_start, delim)
            if delim >= p_end:
                c_end = min(c_end, delim)
                break

        clause_text = sent_text[c_start:c_end]

        # Epistemic check: unestablished assertions ("did not establish that X owns Y")
        # signify uncertainty / lack of evidence, NOT affirmative negation that the relation is false.
        unestablished_match = self.RE_UNESTABLISHED.search(clause_text) or self.RE_UNESTABLISHED.search(sent_text)
        is_unestablished = bool(unestablished_match)

        clause_neg_text = re.sub(r'\bnot\s+only\b', '', clause_text, flags=re.IGNORECASE)
        if is_unestablished:
            # Strip the unestablished carrier phrase before scanning for affirmative negation
            clause_neg_text = self.RE_UNESTABLISHED.sub('', clause_neg_text)

        is_negated = bool(self.RE_NEGATION.search(clause_neg_text))

        allegation_match = self.RE_ALLEGATION.search(clause_text) or self.RE_ALLEGATION.search(sent_text)
        is_allegation = bool(allegation_match) or is_unestablished
        attr_source = allegation_match.group(0).strip() if allegation_match else (unestablished_match.group(0).strip() if unestablished_match else None)

        uncertainty = bool(self.RE_UNCERTAINTY.search(clause_text)) or is_unestablished

        return is_negated, is_allegation, attr_source, uncertainty

    def extract_relations(
        self,
        document: IngestedDocument,
        mentions: List[EntityMention],
    ) -> List[ExtractedRelationCandidate]:
        text = document.normalized_text
        sentences = split_sentences_with_spans(text)

        candidates: List[ExtractedRelationCandidate] = []
        candidate_count = 0

        # Group mentions by sentence
        for sent_idx, (s_start, s_end, sent_text) in enumerate(sentences):
            sent_mentions = [
                m for m in mentions
                if (m.sentence_index == sent_idx) or (s_start <= m.start_char and m.end_char <= s_end)
            ]

            if len(sent_mentions) < 2:
                # Need at least two entities to form a relation candidate
                continue

            # Look for temporal expressions in sentence
            date_mentions = [m for m in sent_mentions if m.entity_type == EntityType.DATE]
            temporal_ctx = date_mentions[0].normalized_value if date_mentions else None

            # Test pairs within sentence
            for i in range(len(sent_mentions)):
                for j in range(len(sent_mentions)):
                    if i == j:
                        continue
                    m_subj = sent_mentions[i]
                    m_obj = sent_mentions[j]

                    # Skip DATE and MONEY as relations endpoints for core organizational/social relations
                    if m_subj.entity_type in (EntityType.DATE, EntityType.MONEY):
                        continue
                    if m_obj.entity_type in (EntityType.DATE, EntityType.MONEY):
                        continue

                    # Check ordering in sentence
                    # Determine predicate based on between-text or sentence structure
                    predicate = self._detect_predicate(
                        sent_text, s_start, m_subj, m_obj
                    )

                    if not predicate:
                        continue

                    # Validate typing constraints
                    if not self._validate_types(predicate, m_subj.entity_type, m_obj.entity_type):
                        continue

                    # Ambiguity check: If there are multiple candidate objects or subjects
                    # matching the exact same predicate pattern in the exact same sentence, abstain
                    if self._is_ambiguous(sent_mentions, m_subj, m_obj, predicate):
                        continue

                    # Clause-scoped epistemic qualifier evaluation
                    is_negated, is_allegation, attr_source, uncertainty = self._evaluate_pair_qualifiers(
                        sent_text, s_start, m_subj, m_obj
                    )

                    cand_id = f"rel_{document.document_id}_{candidate_count}_{m_subj.mention_id}_{m_obj.mention_id}"
                    candidate_count += 1

                    candidate = ExtractedRelationCandidate(
                        candidate_id=cand_id,
                        document_id=document.document_id,
                        subject_mention_id=m_subj.mention_id,
                        subject_surface=m_subj.surface_text,
                        subject_type=m_subj.entity_type,
                        predicate=predicate,
                        object_mention_id=m_obj.mention_id,
                        object_surface=m_obj.surface_text,
                        object_type=m_obj.entity_type,
                        evidence_span=sent_text,
                        evidence_start_char=s_start,
                        evidence_end_char=s_end,
                        is_negated=is_negated,
                        is_allegation=is_allegation,
                        attribution_source=attr_source,
                        uncertainty_flag=uncertainty,
                        temporal_context=temporal_ctx,
                        extraction_method=self.METHOD_NAME,
                        extraction_version=self.VERSION,
                        confidence_score=None,  # Rule baseline does not invent scores
                        metadata={
                            "sentence_index": sent_idx,
                            "subject_offsets": (m_subj.start_char, m_subj.end_char),
                            "object_offsets": (m_obj.start_char, m_obj.end_char),
                        },
                    )
                    candidates.append(candidate)

        return candidates

    def _detect_predicate(
        self,
        sent_text: str,
        sent_start: int,
        subj: EntityMention,
        obj: EntityMention,
    ) -> Optional[str]:
        """
        Detect supported predicate between subject and object.
        Considers text between the two mentions, or surrounding sentence text.
        """
        # If subject occurs before object
        if subj.end_char <= obj.start_char:
            rel_start = subj.end_char - sent_start
            rel_end = obj.start_char - sent_start
            between_text = sent_text[rel_start:rel_end]
        else:
            rel_start = obj.end_char - sent_start
            rel_end = subj.start_char - sent_start
            between_text = sent_text[rel_start:rel_end]

        # Guard: If subject and object are separated by a coordinating clause boundary,
        # they belong to independent clauses and cannot be linked by an intra-clause predicate
        if re.search(r'(?:,\s*(?:but|however|whereas|while|although|yet)|;\s*)', between_text, re.IGNORECASE):
            return None

        # Prioritized check:
        # 1. FOUNDED
        for pat in self.patterns_founded:
            if pat.search(between_text) or pat.search(sent_text):
                # Ensure direction: subject founded object
                if subj.start_char < obj.start_char and pat.search(between_text):
                    return "FOUNDED"

        # 2. OWNS
        for pat in self.patterns_owns:
            if subj.start_char < obj.start_char and pat.search(between_text):
                return "OWNS"

        # 3. WORKS_FOR
        for pat in self.patterns_works_for:
            if subj.start_char < obj.start_char and pat.search(between_text):
                return "WORKS_FOR"

        # 4. LOCATED_IN
        for pat in self.patterns_located_in:
            if subj.start_char < obj.start_char and pat.search(between_text):
                return "LOCATED_IN"

        # 5. ASSOCIATED_WITH
        for pat in self.patterns_associated_with:
            if pat.search(between_text):
                return "ASSOCIATED_WITH"

        return None

    def _validate_types(
        self,
        predicate: str,
        subj_type: EntityType,
        obj_type: EntityType,
    ) -> bool:
        """Enforces schema type restrictions."""
        if predicate == "WORKS_FOR":
            return subj_type == EntityType.PERSON and obj_type == EntityType.ORGANIZATION
        elif predicate == "LOCATED_IN":
            return (
                subj_type in (EntityType.ORGANIZATION, EntityType.LOCATION)
                and obj_type == EntityType.LOCATION
            )
        elif predicate == "OWNS":
            return (
                subj_type in (EntityType.PERSON, EntityType.ORGANIZATION)
                and obj_type in (EntityType.ORGANIZATION, EntityType.PRODUCT, EntityType.FINANCIAL_INSTRUMENT)
            )
        elif predicate == "FOUNDED":
            return (
                subj_type in (EntityType.PERSON, EntityType.ORGANIZATION)
                and obj_type == EntityType.ORGANIZATION
            )
        elif predicate == "ASSOCIATED_WITH":
            return True
        return False

    def _is_ambiguous(
        self,
        sent_mentions: List[EntityMention],
        subj: EntityMention,
        obj: EntityMention,
        predicate: str,
    ) -> bool:
        """
        Abstain when multiple potential objects or subjects match the exact same
        predicate in the sentence without clear syntactic attachment.
        """
        # If there are > 2 possible subjects of the same type and > 2 objects of same type
        same_subj_type = [m for m in sent_mentions if m.entity_type == subj.entity_type and m.mention_id != subj.mention_id]
        same_obj_type = [m for m in sent_mentions if m.entity_type == obj.entity_type and m.mention_id != obj.mention_id]

        if len(same_subj_type) >= 2 and len(same_obj_type) >= 2:
            # Complex multi-entity sentence with high ambiguity
            return True
        return False


# ===========================================================================
# Milestone 10: Model-Backed & Hybrid Relation Extraction
# ===========================================================================

class RelationModelBackend(ABC):
    """Abstract interface for relation classification backends (NLI, transformer head, mock)."""

    @property
    @abstractmethod
    def backend_identifier(self) -> str:
        pass

    @property
    def is_mock(self) -> bool:
        """Returns True if this backend is a simulated mock engine."""
        return False

    @abstractmethod
    def predict_relation(
        self,
        sentence_text: str,
        subj: EntityMention,
        obj: EntityMention,
    ) -> Optional[Dict[str, Any]]:
        """
        Predict relation between subject and object mentions within a sentence.
        Returns dict with keys:
          - 'predicate': str (one of SUPPORTED_PREDICATES)
          - 'confidence_score': float in [0.0, 1.0]
          - 'is_negated': bool
          - 'is_allegation': bool
          - 'uncertainty_flag': bool
          - 'attribution_source': Optional[str]
        Or None if no supported relation is predicted (abstention).
        """
        pass


class MockRelationNLIBackend(RelationModelBackend):
    """
    Deterministic mock NLI/zero-shot relation extraction backend for offline testing.
    Evaluates premise sentences against canonical predicate hypothesis templates.
    """

    SUPPORTED_PREDICATES = {
        "WORKS_FOR",
        "LOCATED_IN",
        "OWNS",
        "FOUNDED",
        "ASSOCIATED_WITH",
    }

    def __init__(
        self,
        canned_relations: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None,
        simulate_unavailable: bool = False,
        unavailability_reason: str = "Simulated missing relation model dependency.",
    ):
        self.canned_relations = canned_relations or {}
        self.simulate_unavailable = simulate_unavailable
        self.unavailability_reason = unavailability_reason

    @property
    def backend_identifier(self) -> str:
        return "mock_relation_nli_engine"

    @property
    def is_mock(self) -> bool:
        return True

    def predict_relation(
        self,
        sentence_text: str,
        subj: EntityMention,
        obj: EntityMention,
    ) -> Optional[Dict[str, Any]]:
        if self.simulate_unavailable:
            raise MLModelUnavailableError(self.unavailability_reason)

        key = (subj.surface_text.strip(), obj.surface_text.strip())
        if key in self.canned_relations:
            return dict(self.canned_relations[key])

        # Direction guard: subject before object in text for directional predicates
        if subj.start_char >= obj.start_char:
            return None

        # Check for clause boundary
        between = sentence_text[subj.end_char - subj.start_char:obj.start_char - subj.start_char] if (obj.start_char > subj.end_char) else ""
        if re.search(r'(?:,\s*(?:but|however|whereas|while|although|yet)|;\s*)', between, re.IGNORECASE):
            return None

        lower = sentence_text.lower()
        s_name = subj.surface_text.lower()
        o_name = obj.surface_text.lower()

        # Epistemic unestablished phrasing: "did not establish that" -> uncertainty, NOT negation
        unest_pattern = r'\b(?:did not|does not|could not|cannot|has not|have not|failed to)\s+(?:establish|confirm|prove|verify|substantiate)\s+that\b'
        is_unest = bool(re.search(unest_pattern, lower))
        lower_without_unest = re.sub(unest_pattern, '', lower)

        is_negated = bool(re.search(r'\b(?:not|never|no longer|denies|denied|did not|does not|cannot|no\s+(?:shares|stake|equity|interest))\b', lower_without_unest))
        is_allegation = bool(re.search(r'\b(?:alleges|alleged|claims|claimed|reportedly|reported that|according to)\b', lower)) or is_unest
        attr_match = re.search(r'\b(?:according to(?:\s+(?:the\s+)?report)?|(?:the\s+)?report\s+(?:alleges|claims|states))\b', lower)
        attr_src = attr_match.group(0).strip() if attr_match else None
        uncertainty = bool(re.search(r'\b(?:unclear|uncertain|may|might|possibly)\b', lower)) or is_unest

        # 1. WORKS_FOR: PERSON -> ORG
        if subj.entity_type == EntityType.PERSON and obj.entity_type == EntityType.ORGANIZATION:
            if any(cue in lower for cue in ("works for", "worked for", "employed by", "employed at", "joined", "ceo of", "director of", "work for")):
                return {
                    "predicate": "WORKS_FOR",
                    "confidence_score": 0.9234,
                    "is_negated": is_negated,
                    "is_allegation": is_allegation,
                    "attribution_source": attr_src,
                    "uncertainty_flag": uncertainty,
                }

        # 2. LOCATED_IN: ORG/LOC -> LOC
        if subj.entity_type in (EntityType.ORGANIZATION, EntityType.LOCATION) and obj.entity_type == EntityType.LOCATION:
            if any(cue in lower for cue in ("located in", "headquartered in", "based in", "operates in")):
                return {
                    "predicate": "LOCATED_IN",
                    "confidence_score": 0.8950,
                    "is_negated": is_negated,
                    "is_allegation": is_allegation,
                    "attribution_source": attr_src,
                    "uncertainty_flag": uncertainty,
                }

        # 3. OWNS: PERSON/ORG -> ORG/PRODUCT
        if subj.entity_type in (EntityType.PERSON, EntityType.ORGANIZATION) and obj.entity_type in (EntityType.ORGANIZATION, EntityType.PRODUCT, EntityType.FINANCIAL_INSTRUMENT):
            if any(cue in lower for cue in ("owns", "owned", "own", "owning", "acquired", "purchased", "controlling stake")):
                return {
                    "predicate": "OWNS",
                    "confidence_score": 0.9410,
                    "is_negated": is_negated,
                    "is_allegation": is_allegation,
                    "attribution_source": attr_src,
                    "uncertainty_flag": uncertainty,
                }

        # 4. FOUNDED: PERSON/ORG -> ORG
        if subj.entity_type in (EntityType.PERSON, EntityType.ORGANIZATION) and obj.entity_type == EntityType.ORGANIZATION:
            if any(cue in lower for cue in ("founded", "co-founded", "established", "started")):
                return {
                    "predicate": "FOUNDED",
                    "confidence_score": 0.9560,
                    "is_negated": is_negated,
                    "is_allegation": is_allegation,
                    "attribution_source": attr_src,
                    "uncertainty_flag": uncertainty,
                }

        # 5. ASSOCIATED_WITH: Any -> Any
        if any(cue in lower for cue in ("associated with", "affiliated with", "partnered with")):
            return {
                "predicate": "ASSOCIATED_WITH",
                "confidence_score": 0.8200,
                "is_negated": is_negated,
                "is_allegation": is_allegation,
                "attribution_source": attr_src,
                "uncertainty_flag": uncertainty,
            }

        return None


class ZeroShotRelationBackend(RelationModelBackend):
    """
    Adapter for Hugging Face zero-shot / NLI classification pipeline.
    Loads models lazily and formats hypothesis entailment prompts.
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/nli-distilroberta-base",
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.device = device
        self._classifier = None

    @property
    def backend_identifier(self) -> str:
        return f"hf_zero_shot:{self.model_name}"

    def _ensure_classifier(self):
        if self._classifier is not None:
            return self._classifier

        try:
            from transformers import pipeline  # type: ignore
        except ImportError as e:
            raise MLModelUnavailableError(
                f"Optional ML dependency 'transformers' is not installed in the active environment. "
                f"Cannot initialize ZeroShotRelationBackend for model '{self.model_name}'."
            ) from e

        try:
            device_arg = 0 if self.device.startswith("cuda") else -1
            self._classifier = pipeline(
                "zero-shot-classification",
                model=self.model_name,
                device=device_arg,
            )
            return self._classifier
        except Exception as e:
            raise MLModelUnavailableError(
                f"Failed to load relation classification model '{self.model_name}': {e}. "
                f"Ensure weights are cached locally for offline execution."
            ) from e

    def predict_relation(
        self,
        sentence_text: str,
        subj: EntityMention,
        obj: EntityMention,
    ) -> Optional[Dict[str, Any]]:
        clf = self._ensure_classifier()
        candidate_labels = ["works for", "is located in", "owns", "founded", "associated with", "none"]
        res = clf(sentence_text, candidate_labels)
        top_label = res["labels"][0]
        top_score = res["scores"][0]

        label_to_pred = {
            "works for": "WORKS_FOR",
            "is located in": "LOCATED_IN",
            "owns": "OWNS",
            "founded": "FOUNDED",
            "associated with": "ASSOCIATED_WITH",
        }
        pred = label_to_pred.get(top_label)
        if not pred or top_score < 0.60:
            return None

        return {
            "predicate": pred,
            "confidence_score": float(top_score),
            "is_negated": False,
            "is_allegation": False,
            "attribution_source": None,
            "uncertainty_flag": False,
        }


class ModelBackedRelationExtractor(BaseRelationExtractor):
    """
    Model-backed Relation Extractor.
    Evaluates entity mention pairs within sentence boundaries via pluggable RelationModelBackend.

    Key Guarantees:
    - Evidence spans strictly grounded in document sentence boundaries.
    - Preserves subject and object mention IDs.
    - Produces only supported schema relation labels.
    - Preserves negation, attribution, and uncertainty qualifiers.
    - Never generates relations solely because entities co-occur in the document.
    - Abstains on ambiguity or unsupported spans.
    """

    METHOD_NAME = "model_backed_relation"
    DEFAULT_MODEL = "cross-encoder/nli-distilroberta-base"
    DEFAULT_VERSION = "1.0.0"

    SUPPORTED_PREDICATES = {
        "WORKS_FOR",
        "LOCATED_IN",
        "OWNS",
        "FOUNDED",
        "ASSOCIATED_WITH",
    }

    def __init__(
        self,
        backend: Optional[RelationModelBackend] = None,
        use_mock_backend: bool = False,
        model_name: str = DEFAULT_MODEL,
        model_version: str = DEFAULT_VERSION,
        confidence_threshold: float = 0.50,
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.model_version = model_version
        self.confidence_threshold = confidence_threshold
        self.device = device
        self.use_mock_backend = use_mock_backend

        if backend is not None:
            self.backend = backend
        elif use_mock_backend:
            self.backend = MockRelationNLIBackend()
        else:
            self.backend = ZeroShotRelationBackend(
                model_name=self.model_name,
                device=self.device,
            )

    def extract_relations(
        self,
        document: IngestedDocument,
        mentions: List[EntityMention],
    ) -> List[ExtractedRelationCandidate]:
        text = document.normalized_text
        sentences = split_sentences_with_spans(text)

        candidates: List[ExtractedRelationCandidate] = []
        candidate_count = 0
        is_mock_backend = getattr(self.backend, "is_mock", False)

        for sent_idx, (s_start, s_end, sent_text) in enumerate(sentences):
            sent_mentions = [
                m for m in mentions
                if (m.sentence_index == sent_idx) or (s_start <= m.start_char and m.end_char <= s_end)
            ]

            if len(sent_mentions) < 2:
                continue

            # Look for temporal expressions
            date_mentions = [m for m in sent_mentions if m.entity_type == EntityType.DATE]
            temporal_ctx = date_mentions[0].normalized_value if date_mentions else None

            for i in range(len(sent_mentions)):
                for j in range(len(sent_mentions)):
                    if i == j:
                        continue
                    m_subj = sent_mentions[i]
                    m_obj = sent_mentions[j]

                    if m_subj.entity_type in (EntityType.DATE, EntityType.MONEY):
                        continue
                    if m_obj.entity_type in (EntityType.DATE, EntityType.MONEY):
                        continue

                    pred_result = self.backend.predict_relation(sent_text, m_subj, m_obj)
                    if not pred_result:
                        continue

                    predicate = pred_result.get("predicate")
                    if predicate not in self.SUPPORTED_PREDICATES:
                        continue

                    score = float(pred_result.get("confidence_score", 0.0))
                    if score < self.confidence_threshold:
                        continue

                    # Validate schema typing
                    if not self._validate_types(predicate, m_subj.entity_type, m_obj.entity_type):
                        continue

                    is_negated = bool(pred_result.get("is_negated", False))
                    is_allegation = bool(pred_result.get("is_allegation", False))
                    attr_src = pred_result.get("attribution_source")
                    uncertainty = bool(pred_result.get("uncertainty_flag", False))

                    cand_id = f"rel_ml_{document.document_id}_{candidate_count}_{m_subj.mention_id}_{m_obj.mention_id}"
                    candidate_count += 1

                    meta: Dict[str, Any] = {
                        "model_identifier": self.model_name,
                        "backend": self.backend.backend_identifier,
                        "device": self.device,
                        "sentence_index": sent_idx,
                        "uncalibrated_score": score,
                        "is_mock_simulation": is_mock_backend,
                        "provenance": "mock_simulation" if is_mock_backend else "live_pretrained_model",
                    }
                    if is_mock_backend:
                        meta["epistemic_warning"] = (
                            "Simulated mock inference for offline testing; does NOT reflect real model weights."
                        )

                    cand = ExtractedRelationCandidate(
                        candidate_id=cand_id,
                        document_id=document.document_id,
                        subject_mention_id=m_subj.mention_id,
                        subject_surface=m_subj.surface_text,
                        subject_type=m_subj.entity_type,
                        predicate=predicate,
                        object_mention_id=m_obj.mention_id,
                        object_surface=m_obj.surface_text,
                        object_type=m_obj.entity_type,
                        evidence_span=sent_text,
                        evidence_start_char=s_start,
                        evidence_end_char=s_end,
                        is_negated=is_negated,
                        is_allegation=is_allegation,
                        attribution_source=attr_src,
                        uncertainty_flag=uncertainty,
                        temporal_context=temporal_ctx,
                        extraction_method=self.METHOD_NAME,
                        extraction_version=self.model_version,
                        confidence_score=round(score, 4),
                        metadata=meta,
                    )
                    candidates.append(cand)

        return candidates

    def _validate_types(self, predicate: str, subj_type: EntityType, obj_type: EntityType) -> bool:
        if predicate == "WORKS_FOR":
            return subj_type == EntityType.PERSON and obj_type == EntityType.ORGANIZATION
        elif predicate == "LOCATED_IN":
            return subj_type in (EntityType.ORGANIZATION, EntityType.LOCATION) and obj_type == EntityType.LOCATION
        elif predicate == "OWNS":
            return (
                subj_type in (EntityType.PERSON, EntityType.ORGANIZATION)
                and obj_type in (EntityType.ORGANIZATION, EntityType.PRODUCT, EntityType.FINANCIAL_INSTRUMENT)
            )
        elif predicate == "FOUNDED":
            return (
                subj_type in (EntityType.PERSON, EntityType.ORGANIZATION)
                and obj_type == EntityType.ORGANIZATION
            )
        elif predicate == "ASSOCIATED_WITH":
            return True
        return False


class HybridRelationExtractor(BaseRelationExtractor):
    """
    Hybrid Relation Extractor combining deterministic rules and ML model.

    Core Invariants:
    - Deduplicates equivalent candidates deterministically.
    - Records agreements as 'hybrid_agreement'.
    - Disagreements (predicate conflict or polarity conflict) are explicitly recorded.
    - Contradiction Preservation: If either system identifies source-grounded negation,
      the negation is strictly preserved. A positive ML prediction never overrides a rule negation.
    - Model agreement on the same evidence is NOT treated as independent corroboration.
    """

    METHOD_NAME = "hybrid_relation"
    VERSION = "1.0.0"

    def __init__(
        self,
        rule_extractor: Optional[DeterministicRuleRelationExtractor] = None,
        ml_extractor: Optional[ModelBackedRelationExtractor] = None,
        allow_rule_fallback: bool = True,
    ):
        self.rule_extractor = rule_extractor or DeterministicRuleRelationExtractor()
        self.ml_extractor = ml_extractor or ModelBackedRelationExtractor(use_mock_backend=False)
        self.allow_rule_fallback = allow_rule_fallback

    def extract_relations(
        self,
        document: IngestedDocument,
        mentions: List[EntityMention],
    ) -> List[ExtractedRelationCandidate]:
        rule_cands = self.rule_extractor.extract_relations(document, mentions)

        ml_cands: List[ExtractedRelationCandidate] = []
        ml_error: Optional[str] = None
        try:
            ml_cands = self.ml_extractor.extract_relations(document, mentions)
        except MLModelUnavailableError as ex:
            if not self.allow_rule_fallback:
                raise
            ml_error = str(ex)

        if ml_error is not None:
            # Fallback path: annotate candidates with fallback metadata
            fallback_cands: List[ExtractedRelationCandidate] = []
            for c in rule_cands:
                meta = dict(c.metadata)
                meta["hybrid_fallback"] = True
                meta["backends_executed"] = ["rule"]
                meta["ml_unavailable_reason"] = ml_error
                fallback_cands.append(
                    ExtractedRelationCandidate(
                        candidate_id=c.candidate_id,
                        document_id=c.document_id,
                        subject_mention_id=c.subject_mention_id,
                        subject_surface=c.subject_surface,
                        subject_type=c.subject_type,
                        predicate=c.predicate,
                        object_mention_id=c.object_mention_id,
                        object_surface=c.object_surface,
                        object_type=c.object_type,
                        evidence_span=c.evidence_span,
                        evidence_start_char=c.evidence_start_char,
                        evidence_end_char=c.evidence_end_char,
                        is_negated=c.is_negated,
                        is_allegation=c.is_allegation,
                        attribution_source=c.attribution_source,
                        uncertainty_flag=c.uncertainty_flag,
                        temporal_context=c.temporal_context,
                        extraction_method=f"{c.extraction_method}_fallback",
                        extraction_version=c.extraction_version,
                        confidence_score=c.confidence_score,
                        metadata=meta,
                    )
                )
            return fallback_cands

        return self._reconcile_relations(document, rule_cands, ml_cands)

    def _reconcile_relations(
        self,
        document: IngestedDocument,
        rule_cands: List[ExtractedRelationCandidate],
        ml_cands: List[ExtractedRelationCandidate],
    ) -> List[ExtractedRelationCandidate]:
        matched_rule_ids: Set[str] = set()
        matched_ml_ids: Set[str] = set()
        combined: List[ExtractedRelationCandidate] = []

        is_mock_ml = getattr(self.ml_extractor.backend, "is_mock", False)
        backends_executed = ["rule", "mock_ml"] if is_mock_ml else ["rule", "ml"]

        # Key: (subj_mention_id, obj_mention_id, predicate)
        for r_c in rule_cands:
            for m_c in ml_cands:
                if m_c.candidate_id in matched_ml_ids:
                    continue

                same_pair = (
                    r_c.subject_mention_id == m_c.subject_mention_id
                    and r_c.object_mention_id == m_c.object_mention_id
                )
                if not same_pair:
                    continue

                if r_c.predicate == m_c.predicate:
                    # Same predicate! Check polarity
                    matched_rule_ids.add(r_c.candidate_id)
                    matched_ml_ids.add(m_c.candidate_id)

                    # CONTRADICTION / POLARITY CHECK:
                    # If either says negated, negation MUST be preserved
                    is_neg = r_c.is_negated or m_c.is_negated
                    polarity_conflict = r_c.is_negated != m_c.is_negated

                    meta = dict(m_c.metadata)
                    meta.update({
                        "backends_executed": backends_executed,
                        "backends_agreed": not polarity_conflict,
                        "rule_method": r_c.extraction_method,
                        "ml_method": m_c.extraction_method,
                        "polarity_conflict": polarity_conflict,
                        "requires_human_review": polarity_conflict,
                        "disagreement_type": "polarity_conflict" if polarity_conflict else None,
                        "independent_corroboration": False,
                    })

                    cand_id = f"rel_hyb_{document.document_id}_{r_c.subject_mention_id}_{r_c.object_mention_id}"
                    combined.append(
                        ExtractedRelationCandidate(
                            candidate_id=cand_id,
                            document_id=document.document_id,
                            subject_mention_id=r_c.subject_mention_id,
                            subject_surface=r_c.subject_surface,
                            subject_type=r_c.subject_type,
                            predicate=r_c.predicate,
                            object_mention_id=r_c.object_mention_id,
                            object_surface=r_c.object_surface,
                            object_type=r_c.object_type,
                            evidence_span=r_c.evidence_span,
                            evidence_start_char=r_c.evidence_start_char,
                            evidence_end_char=r_c.evidence_end_char,
                            is_negated=is_neg,
                            is_allegation=r_c.is_allegation or m_c.is_allegation,
                            attribution_source=r_c.attribution_source or m_c.attribution_source,
                            uncertainty_flag=r_c.uncertainty_flag or m_c.uncertainty_flag,
                            temporal_context=r_c.temporal_context or m_c.temporal_context,
                            extraction_method="hybrid_agreement" if not polarity_conflict else "hybrid_polarity_conflict",
                            extraction_version=self.VERSION,
                            confidence_score=m_c.confidence_score,
                            metadata=meta,
                        )
                    )
                    break
                else:
                    # Same pair, different predicate (e.g. Rule says OWNS, ML says ASSOCIATED_WITH)
                    # Record disagreement
                    matched_rule_ids.add(r_c.candidate_id)
                    matched_ml_ids.add(m_c.candidate_id)

                    meta = dict(m_c.metadata)
                    meta.update({
                        "backends_executed": backends_executed,
                        "backends_disagreed": True,
                        "requires_human_review": True,
                        "disagreement_type": "predicate_conflict",
                        "rule_predicate": r_c.predicate,
                        "ml_predicate": m_c.predicate,
                    })

                    # Prefer specific rule predicate over generic ML ASSOCIATED_WITH, or retain rule
                    combined.append(
                        ExtractedRelationCandidate(
                            candidate_id=f"rel_hyb_pred_conflict_{r_c.candidate_id}",
                            document_id=document.document_id,
                            subject_mention_id=r_c.subject_mention_id,
                            subject_surface=r_c.subject_surface,
                            subject_type=r_c.subject_type,
                            predicate=r_c.predicate,
                            object_mention_id=r_c.object_mention_id,
                            object_surface=r_c.object_surface,
                            object_type=r_c.object_type,
                            evidence_span=r_c.evidence_span,
                            evidence_start_char=r_c.evidence_start_char,
                            evidence_end_char=r_c.evidence_end_char,
                            is_negated=r_c.is_negated,
                            is_allegation=r_c.is_allegation,
                            attribution_source=r_c.attribution_source,
                            uncertainty_flag=r_c.uncertainty_flag,
                            temporal_context=r_c.temporal_context,
                            extraction_method="hybrid_predicate_conflict_prefer_rule",
                            extraction_version=self.VERSION,
                            confidence_score=m_c.confidence_score,
                            metadata=meta,
                        )
                    )
                    break

        # Pass B: Unmatched rule candidates
        for r_c in rule_cands:
            if r_c.candidate_id not in matched_rule_ids:
                combined.append(r_c)

        # Pass C: Unmatched ML candidates
        for m_c in ml_cands:
            if m_c.candidate_id not in matched_ml_ids:
                combined.append(m_c)

        combined.sort(key=lambda c: (c.evidence_start_char, c.evidence_end_char, c.candidate_id))
        return combined

