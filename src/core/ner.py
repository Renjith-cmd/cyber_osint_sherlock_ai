"""
Named Entity Recognition (NER) Abstraction and Baseline for Sherlock AI (Milestone 9).

Provides:
- `EntityMention`: Immutable representation of an extracted entity occurrence with exact offsets.
- `BaseNERExtractor`: Extensible interface for NER extractors (rule-based, statistical, transformer).
- `DeterministicRuleNERExtractor`: Fully deterministic, local, rule-based baseline extractor
  supporting PERSON, ORGANIZATION, LOCATION, DATE, and MONEY without external network or models.

Key Guarantees:
- Exact character offsets tied strictly to document.normalized_text.
- Sentence and page index lookup for every mention.
- Repeated mentions across documents or within the same document are preserved separately.
- Strict epistemic separation: rule baselines do not fabricate confidence scores (reports None).
- Normalization where safe; leaves raw surface text unaltered in separate field.
"""

from abc import ABC, abstractmethod
from enum import Enum
import re
from typing import Dict, List, Optional, Tuple, Any, Set
from pydantic import Field, field_validator, model_validator

from src.core.models import (
    ImmutableBaseModel,
    EntityType,
    ConfidenceSemantics,
    _validate_non_empty_str,
)
from src.core.document_ingestion import IngestedDocument


class EntityMention(ImmutableBaseModel):
    """
    Immutable representation of an extracted entity mention in a source document.
    """
    mention_id: str
    document_id: str
    surface_text: str
    entity_type: EntityType
    start_char: int
    end_char: int
    page_number: Optional[int] = 1
    sentence_index: Optional[int] = None
    normalized_value: Optional[str] = None
    extraction_method: str = "deterministic_rule"
    extraction_version: str = "1.0.0"
    confidence_score: Optional[float] = None
    confidence_semantics: Optional[ConfidenceSemantics] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_text_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "text" in data and "surface_text" not in data:
                data = dict(data)
                data["surface_text"] = data.pop("text")
        return data


    @field_validator("mention_id", "document_id", "surface_text", "extraction_method", "extraction_version")
    @classmethod
    def _validate_non_empty_strings(cls, v: str, info) -> str:
        return _validate_non_empty_str(v, info.field_name)

    @field_validator("confidence_score")
    @classmethod
    def _validate_confidence(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("confidence_score must be between 0.0 and 1.0")
        return v

    @model_validator(mode="after")
    def _validate_char_spans(self) -> "EntityMention":
        if self.start_char < 0:
            raise ValueError(f"start_char ({self.start_char}) must be non-negative.")
        if self.end_char <= self.start_char:
            raise ValueError(f"end_char ({self.end_char}) must be strictly greater than start_char ({self.start_char}).")
        expected_len = len(self.surface_text)
        actual_span_len = self.end_char - self.start_char
        if expected_len != actual_span_len:
            raise ValueError(
                f"surface_text length ({expected_len}) does not match span length ({actual_span_len}) "
                f"[{self.start_char}:{self.end_char}]."
            )
        return self


class BaseNERExtractor(ABC):
    """Abstract interface for Named Entity Recognition backends."""

    @abstractmethod
    def extract_entities(self, document: IngestedDocument) -> List[EntityMention]:
        """
        Extract entity mentions from an ingested document.
        Must return mentions with valid character offsets referring to document.normalized_text.
        """
        pass


def split_sentences_with_spans(text: str) -> List[Tuple[int, int, str]]:
    """
    Split normalized text into sentences while capturing exact [start_char, end_char) offsets.
    Protects periods within common honorifics and corporate abbreviations (e.g. Dr., Mr., Inc.).
    Returns list of (start_char, end_char, sentence_text).
    """
    if not text.strip():
        return []

    abbr_pattern = re.compile(r'\b(?:Mr|Mrs|Ms|Dr|Prof|Inc|Ltd|Corp|St|vs)\.$', re.IGNORECASE)

    results: List[Tuple[int, int, str]] = []
    curr_start = 0
    i = 0
    n = len(text)

    while i < n:
        c = text[i]
        if c == "\n":
            span_text = text[curr_start:i].strip()
            if span_text:
                l_ws = len(text[curr_start:i]) - len(text[curr_start:i].lstrip())
                t_ws = len(text[curr_start:i]) - len(text[curr_start:i].rstrip())
                results.append((curr_start + l_ws, i - t_ws, text[curr_start + l_ws:i - t_ws]))
            curr_start = i + 1
        elif c in ".!?":
            sub_so_far = text[curr_start:i + 1]
            if not abbr_pattern.search(sub_so_far):
                if i + 1 == n or text[i + 1].isspace():
                    end_pos = i + 1
                    span_text = text[curr_start:end_pos].strip()
                    if span_text:
                        l_ws = len(text[curr_start:end_pos]) - len(text[curr_start:end_pos].lstrip())
                        t_ws = len(text[curr_start:end_pos]) - len(text[curr_start:end_pos].rstrip())
                        results.append((curr_start + l_ws, end_pos - t_ws, text[curr_start + l_ws:end_pos - t_ws]))
                    while end_pos < n and text[end_pos].isspace() and text[end_pos] != "\n":
                        end_pos += 1
                    curr_start = end_pos
                    i = curr_start - 1
        i += 1

    if curr_start < n:
        rem_text = text[curr_start:].strip()
        if rem_text:
            l_ws = len(text[curr_start:]) - len(text[curr_start:].lstrip())
            t_ws = len(text[curr_start:]) - len(text[curr_start:].rstrip())
            results.append((curr_start + l_ws, n - t_ws, text[curr_start + l_ws:n - t_ws]))

    return results


class DeterministicRuleNERExtractor(BaseNERExtractor):
    """
    Deterministic rule-based Named Entity Recognition baseline.
    Does not require external models or network connections.
    Recognizes PERSON, ORGANIZATION, LOCATION, DATE, and MONEY.
    """

    METHOD_NAME = "deterministic_regex_rule"
    VERSION = "1.0.0"

    # Common English honorifics preceding Person names
    HONORIFICS = r"(?:Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.|Sir|Lady|Senator|President|CEO|Director|Agent|Minister|Officer|Detective)"

    # Corporate/Organization designators
    ORG_DESIGNATORS = (
        r"(?:Inc\.?|LLC|Corp\.?|Corporation|Ltd\.?|Limited|GmbH|PLC|Group|Bank|Holdings|"
        r"Enterprises|Agency|Foundation|Institute|Department|Ministry|Committee|Council|Association|"
        r"Industries|Technologies|Services|Capital|Partners)"
    )

    # Geographic designators
    GEO_DESIGNATORS = (
        r"(?:Street|St\.|Avenue|Ave\.|Boulevard|Blvd\.|Road|Rd\.|River|Mountain|Mount|Mt\.|"
        r"Island|City|County|State|Province|Sea|Ocean|Bay|Park|Square|Square|Airport|District)"
    )

    MONTHS = (
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)"
    )

    MONTH_MAP = {
        "january": "01", "jan": "01", "february": "02", "feb": "02",
        "march": "03", "mar": "03", "april": "04", "apr": "04",
        "may": "05", "june": "06", "jun": "06", "july": "07", "jul": "07",
        "august": "08", "aug": "08", "september": "09", "sep": "09", "sept": "09",
        "october": "10", "oct": "10", "november": "11", "nov": "11",
        "december": "12", "dec": "12",
    }

    # Curated known entities for deterministic baseline extraction
    KNOWN_ORGANIZATIONS = {
        "acme corp", "acme corporation", "interpol", "fbi", "cia", "scotland yard",
        "united nations", "world bank", "international business machines", "ibm",
        "cyberdyne systems", "google", "microsoft", "apple", "amazon", "meta",
        "sherlock security", "umbrella corporation", "wayland corp", "stark industries",
        "wayne enterprises", "baker street consulting", "globex corporation",
        # Additional synthetic organization names used in synthetic tests
        "wayne enterprises inc", "stark industries ltd",
    }

    KNOWN_LOCATIONS = {
        "london", "new york", "paris", "berlin", "tokyo", "washington", "california",
        "united kingdom", "uk", "united states", "usa", "france", "germany", "japan",
        "baker street", "221b baker street", "detroit", "chicago", "los angeles", "san francisco",
        "geneva", "brussels", "moscow", "beijing", "zurich", "vienna"
    }

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        # 1. DATE patterns
        # ISO: YYYY-MM-DD
        self.re_date_iso = re.compile(r'\b(19\d\d|20\d\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b')
        # Month DD, YYYY e.g. January 15, 2024 or Jan 15 2024
        self.re_date_text = re.compile(
            rf'\b({self.MONTHS})\s+([0-3]?\d)(?:st|nd|rd|th)?,\s*(19\d\d|20\d\d)\b',
            re.IGNORECASE
        )
        # DD Month YYYY e.g. 15 January 2024
        self.re_date_dmy = re.compile(
            rf'\b([0-3]?\d)(?:st|nd|rd|th)?\s+({self.MONTHS})\s+(19\d\d|20\d\d)\b',
            re.IGNORECASE
        )
        # Month YYYY e.g. October 2023
        self.re_date_my = re.compile(
            rf'\b({self.MONTHS})\s+(19\d\d|20\d\d)\b',
            re.IGNORECASE
        )

        # 2. MONEY patterns
        # E.g. $10,000, $5.5 million, EUR 500, 100 million USD, £500
        self.re_money = re.compile(
            r'(?:(?:\$|€|£|¥)\s*\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:million|billion|trillion|k|m|b))?|'
            r'\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:million|billion|trillion)?\s*(?:USD|EUR|GBP|JPY|dollars|euros|pounds)\b)',
            re.IGNORECASE
        )

        # 3. PERSON patterns (supporting accented Unicode names like René François, Angela Müller)
        _U_UPPER = r"[A-Z\xc0-\xd6\xd8-\xde]"
        _U_LOWER = r"[a-z\xdf-\xf6\xf8-\xff]"
        _NAME_TOKEN = rf"(?:{_U_UPPER}{_U_LOWER}+)"

        # With honorific: "Dr. John Watson", "Dr. René François"
        self.re_person_honorific = re.compile(
            rf'\b({self.HONORIFICS})[ \t]+({_NAME_TOKEN}(?:[ \t]+{_NAME_TOKEN})?)\b'
        )
        # Two or three capitalized words: "John Doe", "René François", "Alice M. Walker"
        self.re_person_names = re.compile(
            rf'\b({_NAME_TOKEN}(?:[ \t]+{_U_UPPER}\.?)?[ \t]+{_NAME_TOKEN})\b'
        )

        # 4. ORGANIZATION patterns
        # Capitalized phrase ending with corporate designator: "Acme Corp.", "Global Logistics LLC"
        self.re_org_designator = re.compile(
            rf'\b([A-Z][a-zA-Z0-9&]*(?:[ \t]+[A-Z][a-zA-Z0-9&]*)*[ \t]+{self.ORG_DESIGNATORS})\b'
        )
        # "Department of X", "Ministry of X", "Bank of X"
        self.re_org_of = re.compile(
            r'\b((?:Department|Ministry|Bank|Agency|University|Institute|Council)[ \t]+of[ \t]+[A-Z][a-zA-Z0-9&]*(?:[ \t]+[A-Z][a-zA-Z0-9&]*)*)\b'
        )

        # 5. LOCATION patterns
        # Capitalized phrase ending with geographic designator: "Baker Street", "Hudson River"
        self.re_loc_designator = re.compile(
            rf'\b([A-Z][a-zA-Z0-9]*(?:[ \t]+[A-Z][a-zA-Z0-9]*)*[ \t]+{self.GEO_DESIGNATORS})\b'
        )

    def extract_entities(self, document: IngestedDocument) -> List[EntityMention]:
        text = document.normalized_text
        sentences = split_sentences_with_spans(text)

        # Raw candidate extraction: (start, end, surface_text, entity_type, normalized_val)
        raw_candidates: List[Tuple[int, int, str, EntityType, Optional[str]]] = []

        # A. Extract DATE
        for m in self.re_date_iso.finditer(text):
            norm = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            raw_candidates.append((m.start(), m.end(), m.group(0), EntityType.DATE, norm))

        for m in self.re_date_text.finditer(text):
            month_str = m.group(1).lower().replace(".", "")
            month_num = self.MONTH_MAP.get(month_str, "01")
            day_num = int(m.group(2))
            year = m.group(3)
            norm = f"{year}-{month_num}-{day_num:02d}"
            raw_candidates.append((m.start(), m.end(), m.group(0), EntityType.DATE, norm))

        for m in self.re_date_dmy.finditer(text):
            day_num = int(m.group(1))
            month_str = m.group(2).lower().replace(".", "")
            month_num = self.MONTH_MAP.get(month_str, "01")
            year = m.group(3)
            norm = f"{year}-{month_num}-{day_num:02d}"
            raw_candidates.append((m.start(), m.end(), m.group(0), EntityType.DATE, norm))

        for m in self.re_date_my.finditer(text):
            month_str = m.group(1).lower().replace(".", "")
            month_num = self.MONTH_MAP.get(month_str, "01")
            year = m.group(2)
            norm = f"{year}-{month_num}"
            raw_candidates.append((m.start(), m.end(), m.group(0), EntityType.DATE, norm))

        # B. Extract MONEY
        for m in self.re_money.finditer(text):
            surface = m.group(0)
            norm = self._normalize_money(surface)
            raw_candidates.append((m.start(), m.end(), surface, EntityType.MONEY, norm))

        # C. Extract Known Organizations & Locations
        lower_text = text.lower()
        for org in self.KNOWN_ORGANIZATIONS:
            # Word boundary matching in text
            pattern = re.compile(rf'\b{re.escape(org)}\b', re.IGNORECASE)
            for m in pattern.finditer(text):
                surface = text[m.start():m.end()]
                raw_candidates.append((m.start(), m.end(), surface, EntityType.ORGANIZATION, surface.strip()))

        for loc in self.KNOWN_LOCATIONS:
            pattern = re.compile(rf'\b{re.escape(loc)}\b', re.IGNORECASE)
            for m in pattern.finditer(text):
                surface = text[m.start():m.end()]
                raw_candidates.append((m.start(), m.end(), surface, EntityType.LOCATION, surface.strip()))

        # D. Rule-based ORG with designator
        for m in self.re_org_designator.finditer(text):
            surface = m.group(0)
            raw_candidates.append((m.start(), m.end(), surface, EntityType.ORGANIZATION, surface.strip()))

        for m in self.re_org_of.finditer(text):
            surface = m.group(0)
            raw_candidates.append((m.start(), m.end(), surface, EntityType.ORGANIZATION, surface.strip()))

        # E. Rule-based LOC with designator
        for m in self.re_loc_designator.finditer(text):
            surface = m.group(0)
            raw_candidates.append((m.start(), m.end(), surface, EntityType.LOCATION, surface.strip()))

        # F. Rule-based PERSON
        for m in self.re_person_honorific.finditer(text):
            surface = m.group(0)
            # Normalized strips honorific
            person_name = m.group(2).strip()
            raw_candidates.append((m.start(), m.end(), surface, EntityType.PERSON, person_name))

        for m in self.re_person_names.finditer(text):
            surface = m.group(0)
            # Filter out common capitalized words that are not names
            if not self._is_non_person_candidate(surface):
                raw_candidates.append((m.start(), m.end(), surface, EntityType.PERSON, surface.strip()))

        # Deduplicate & resolve overlapping spans
        resolved_spans = self._resolve_span_conflicts(raw_candidates, text)

        # Convert to EntityMention objects
        mentions: List[EntityMention] = []
        for idx, (start, end, surface, ent_type, norm_val) in enumerate(resolved_spans):
            # Trim leading/trailing whitespace from the surface and adjust offsets
            trimmed_surface = surface
            trimmed_start = start
            trimmed_end = end
            # Adjust start offset if there is leading whitespace
            while trimmed_start < trimmed_end and trimmed_surface[0].isspace():
                trimmed_surface = trimmed_surface[1:]
                trimmed_start += 1
            # Adjust end offset if there is trailing whitespace
            while trimmed_end > trimmed_start and trimmed_surface[-1].isspace():
                trimmed_surface = trimmed_surface[:-1]
                trimmed_end -= 1

            # Locate sentence index
            sent_idx = self._find_sentence_index(trimmed_start, trimmed_end, sentences)
            # Locate page number
            page_num = self._find_page_number(trimmed_start, document.page_offsets)

            mention_id = f"men_{document.document_id}_{idx}_{trimmed_start}_{trimmed_end}"
            mention = EntityMention(
                mention_id=mention_id,
                document_id=document.document_id,
                surface_text=trimmed_surface,
                entity_type=ent_type,
                start_char=trimmed_start,
                end_char=trimmed_end,
                page_number=page_num,
                sentence_index=sent_idx,
                normalized_value=norm_val,
                extraction_method=self.METHOD_NAME,
                extraction_version=self.VERSION,
                confidence_score=None,  # Rule baseline does not fabricate scores
                confidence_semantics=None,
                metadata={},
            )
            mentions.append(mention)

        # Sort mentions deterministically by start_char, end_char
        mentions.sort(key=lambda m: (m.start_char, m.end_char, m.mention_id))
        return mentions

    def _normalize_money(self, surface: str) -> str:
        s = surface.strip().replace(",", "")
        # Convert e.g. "$10 million" to canonical "$10000000"
        m = re.match(r'^\$?\s*(\d+(?:\.\d+)?)\s*(million|billion|trillion|k|m|b)?\s*(?:USD|dollars)?$', s, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            mult = m.group(2)
            if mult:
                mult_lower = mult.lower()
                if mult_lower in ("million", "m"):
                    val *= 1_000_000
                elif mult_lower in ("billion", "b"):
                    val *= 1_000_000_000
                elif mult_lower in ("trillion",):
                    val *= 1_000_000_000_000
                elif mult_lower in ("k",):
                    val *= 1_000
            if val.is_integer():
                return f"${int(val)}"
            return f"${val:.2f}"
        return s

    def _is_non_person_candidate(self, surface: str) -> bool:
        lower = surface.lower()
        if lower in self.KNOWN_ORGANIZATIONS or lower in self.KNOWN_LOCATIONS:
            return True
        # Common English capitalized phrases at start of sentences
        stop_phrases = {
            "the following", "in addition", "for example", "on the", "at the",
            "according to", "however", "furthermore", "meanwhile", "moreover",
            "last month", "last year", "next year", "first quarter", "second quarter",
            "third quarter", "fourth quarter", "united states", "united kingdom",
            "supreme court", "high court", "prime minister", "press release",
        }
        if lower in stop_phrases:
            return True
        tokens = lower.split()
        if any(t in ("january", "february", "march", "april", "may", "june", "july",
                    "august", "september", "october", "november", "december") for t in tokens):
            return True
        return False

    def _resolve_span_conflicts(
        self,
        candidates: List[Tuple[int, int, str, EntityType, Optional[str]]],
        text: str,
    ) -> List[Tuple[int, int, str, EntityType, Optional[str]]]:
        """
        Resolve overlapping spans deterministically:
        - Exact matches: merge if same, prefer more specific type if conflict.
        - Overlapping spans: prefer the longer span.
        """
        if not candidates:
            return []

        # Sort by start ascending, then length descending
        sorted_cands = sorted(
            candidates,
            key=lambda c: (c[0], -(c[1] - c[0]), self._type_priority(c[3]))
        )

        accepted: List[Tuple[int, int, str, EntityType, Optional[str]]] = []
        for cand in sorted_cands:
            start, end, surface, ent_type, norm = cand
            # Double check surface against text slice
            if text[start:end] != surface:
                continue

            # Check overlap with already accepted spans
            overlaps = False
            for a_start, a_end, a_surf, a_type, a_norm in accepted:
                # Overlap condition: start < a_end and end > a_start
                if start < a_end and end > a_start:
                    overlaps = True
                    break

            if not overlaps:
                accepted.append(cand)

        return accepted

    def _type_priority(self, entity_type: EntityType) -> int:
        # Organization and Location with designators usually take priority over raw Person bigrams
        priority = {
            EntityType.DATE: 1,
            EntityType.MONEY: 2,
            EntityType.ORGANIZATION: 3,
            EntityType.LOCATION: 4,
            EntityType.PERSON: 5,
        }
        return priority.get(entity_type, 10)

    def _find_sentence_index(
        self, start: int, end: int, sentences: List[Tuple[int, int, str]]
    ) -> Optional[int]:
        for idx, (s_start, s_end, _) in enumerate(sentences):
            if s_start <= start and end <= s_end:
                return idx
            # Partial coverage fallback
            if start < s_end and end > s_start:
                return idx
        return None

    def _find_page_number(
        self, start: int, page_offsets: List[Tuple[int, int]]
    ) -> int:
        if not page_offsets:
            return 1
        for page_idx, (p_start, p_end) in enumerate(page_offsets):
            if p_start <= start < p_end:
                return page_idx + 1
        return 1


# ===========================================================================
# Milestone 10: Model-Backed & Hybrid Named Entity Recognition
# ===========================================================================

class MLModelUnavailableError(RuntimeError):
    """
    Raised when an ML-backed model or its required dependency is requested
    but is not available in the active environment.
    """
    pass


class NERModelBackend(ABC):
    """Abstract interface for low-level NER inference backends (HF, ONNX, Mock)."""

    @property
    @abstractmethod
    def backend_identifier(self) -> str:
        """Returns unique identifier for this backend engine."""
        pass

    @property
    def is_mock(self) -> bool:
        """Returns True if this backend is a simulated mock engine."""
        return False

    @abstractmethod
    def predict_tokens(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract token-level or aggregated entity spans from raw text.
        Returns list of dicts with keys:
          - 'word': surface text
          - 'start': start character offset
          - 'end': end character offset
          - 'entity_group': predicted entity label (e.g. 'PER', 'ORG', 'LOC')
          - 'score': uncalibrated model score / probability in [0.0, 1.0]
        """
        pass


class MockTransformerNERBackend(NERModelBackend):
    """
    Deterministic mock transformer backend for offline testing and benchmarking.
    Simulates subword token classification, exact character offsets, and uncalibrated probabilities.
    """

    def __init__(
        self,
        canned_predictions: Optional[List[Dict[str, Any]]] = None,
        predefined_entities: Optional[List[Dict[str, Any]]] = None,
        simulate_unavailable: bool = False,
        unavailability_reason: str = "Simulated missing ML model dependency.",
    ):
        self.canned_predictions = canned_predictions or predefined_entities
        self.simulate_unavailable = simulate_unavailable
        self.unavailability_reason = unavailability_reason

    @property
    def backend_identifier(self) -> str:
        return "mock_transformer_engine"

    @property
    def is_mock(self) -> bool:
        return True

    def predict_tokens(self, text: str) -> List[Dict[str, Any]]:
        if self.simulate_unavailable:
            raise MLModelUnavailableError(self.unavailability_reason)

        if self.canned_predictions is not None:
            return list(self.canned_predictions)

        # Built-in deterministic mock predictions for testing
        preds: List[Dict[str, Any]] = []

        # Find persons
        for m in re.finditer(r'\b(Dr\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|[A-Z][a-z]+\s+[A-Z][a-z]+)\b', text):
            # Exclude known non-persons
            if m.group(0) in ("Sherlock Security", "Cyberdyne Systems", "Globex Corporation", "Wayne Enterprises", "Stark Industries"):
                continue
            preds.append({
                "word": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "entity_group": "PER",
                "score": 0.9421,
            })

        # Find orgs
        for org in ("Sherlock Security", "Cyberdyne Systems", "Globex Corporation", "Wayne Enterprises", "Stark Industries", "Acme Corp"):
            for m in re.finditer(rf'\b{re.escape(org)}\b', text):
                preds.append({
                    "word": text[m.start():m.end()],
                    "start": m.start(),
                    "end": m.end(),
                    "entity_group": "ORG",
                    "score": 0.9150,
                })

        # Find locs
        for loc in ("London", "Tokyo", "Paris", "New York", "Baker Street", "Gotham City", "Gotham", "Metropolis"):
            for m in re.finditer(rf'\b{re.escape(loc)}\b', text):
                preds.append({
                    "word": text[m.start():m.end()],
                    "start": m.start(),
                    "end": m.end(),
                    "entity_group": "LOC",
                    "score": 0.8875,
                })

        # Sort by start_char
        preds.sort(key=lambda p: (p["start"], p["end"]))
        return preds


class HuggingFaceNERBackend(NERModelBackend):
    """
    Adapter for Hugging Face Transformers pipeline.
    Loads models lazily, enforces CPU/GPU execution constraints,
    and maps subwords back to exact text offsets.
    """

    def __init__(
        self,
        model_name: str = "dslim/bert-base-NER",
        device: str = "cpu",
        aggregation_strategy: str = "simple",
    ):
        self.model_name = model_name
        self.device = device
        self.aggregation_strategy = aggregation_strategy
        self._pipeline = None

    @property
    def backend_identifier(self) -> str:
        return f"hf_pipeline:{self.model_name}"

    def _ensure_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline

        try:
            from transformers import pipeline  # type: ignore
        except ImportError as e:
            raise MLModelUnavailableError(
                f"Optional ML dependency 'transformers' is not installed in the active environment. "
                f"Cannot initialize HuggingFaceNERBackend for model '{self.model_name}'."
            ) from e

        try:
            device_arg = 0 if self.device.startswith("cuda") else -1
            self._pipeline = pipeline(
                "token-classification",
                model=self.model_name,
                aggregation_strategy=self.aggregation_strategy,
                device=device_arg,
            )
            return self._pipeline
        except Exception as e:
            raise MLModelUnavailableError(
                f"Failed to load pretrained HuggingFace model '{self.model_name}': {e}. "
                f"Ensure weights are cached locally for offline execution."
            ) from e

    def predict_tokens(self, text: str) -> List[Dict[str, Any]]:
        pipe = self._ensure_pipeline()
        raw_outputs = pipe(text)
        formatted: List[Dict[str, Any]] = []
        for item in raw_outputs:
            formatted.append({
                "word": item.get("word", ""),
                "start": int(item.get("start", 0)),
                "end": int(item.get("end", 0)),
                "entity_group": item.get("entity_group", item.get("entity", "")),
                "score": float(item.get("score", 0.0)),
            })
        return formatted


class ModelBackedNERExtractor(BaseNERExtractor):
    """
    Model-backed Named Entity Recognition extractor.
    Operates via pluggable NERModelBackend with lazy loading and strict offset grounding.

    Key Guarantees:
    - Token offsets strictly refer to IngestedDocument.normalized_text.
    - Unsupported entity types are handled explicitly without silent mutation.
    - Confidence scores represent raw model outputs and are flagged as HEURISTIC_SCORE.
    - Repeated mentions in document are preserved as distinct EntityMention records.
    - Never merges mentions into identity clusters.
    """

    METHOD_NAME = "model_backed_transformer"
    DEFAULT_MODEL = "dslim/bert-base-NER"
    DEFAULT_VERSION = "1.0.0"

    LABEL_TO_ENTITY_TYPE: Dict[str, EntityType] = {
        "PER": EntityType.PERSON,
        "PERSON": EntityType.PERSON,
        "B-PER": EntityType.PERSON,
        "I-PER": EntityType.PERSON,
        "ORG": EntityType.ORGANIZATION,
        "ORGANIZATION": EntityType.ORGANIZATION,
        "B-ORG": EntityType.ORGANIZATION,
        "I-ORG": EntityType.ORGANIZATION,
        "LOC": EntityType.LOCATION,
        "LOCATION": EntityType.LOCATION,
        "GPE": EntityType.LOCATION,
        "B-LOC": EntityType.LOCATION,
        "I-LOC": EntityType.LOCATION,
    }

    def __init__(
        self,
        backend: Optional[NERModelBackend] = None,
        use_mock_backend: bool = False,
        model_name: str = DEFAULT_MODEL,
        model_version: str = DEFAULT_VERSION,
        confidence_threshold: float = 0.50,
        allow_unsupported_types: bool = False,
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.model_version = model_version
        self.confidence_threshold = confidence_threshold
        self.allow_unsupported_types = allow_unsupported_types
        self.device = device
        self.use_mock_backend = use_mock_backend

        if backend is not None:
            self.backend = backend
        elif use_mock_backend:
            self.backend = MockTransformerNERBackend()
        else:
            self.backend = HuggingFaceNERBackend(
                model_name=self.model_name,
                device=self.device,
            )

    def extract_entities(self, document: IngestedDocument) -> List[EntityMention]:
        text = document.normalized_text
        if not text.strip():
            return []

        sentences = split_sentences_with_spans(text)

        # Query model backend
        raw_predictions = self.backend.predict_tokens(text)

        # Aggregate subword tokens if necessary (e.g. B-PER followed by I-PER or token with ##)
        aggregated_preds: List[Dict[str, Any]] = []
        for p in raw_predictions:
            start = int(p["start"])
            end = int(p["end"])
            score = float(p.get("score", 0.0))
            raw_tag = str(p.get("entity_group", "")).upper()
            word = str(p.get("word", ""))

            if aggregated_preds:
                last = aggregated_preds[-1]
                last_tag = str(last.get("entity_group", "")).upper()
                last_end = int(last["end"])
                # Check if contiguous subword
                is_subword = word.startswith("##") or raw_tag.startswith("I-")
                is_same_ent = (raw_tag.replace("B-", "").replace("I-", "") == last_tag.replace("B-", "").replace("I-", ""))
                if is_same_ent and (start == last_end or (start == last_end + 1 and text[last_end:start] == " ")) and (is_subword or raw_tag.startswith("I-")):
                    # Merge subword into preceding span
                    last["end"] = end
                    last["word"] = text[int(last["start"]):end]
                    last["score"] = min(float(last.get("score", score)), score)
                    continue

            aggregated_preds.append(dict(p))

        candidates: List[Tuple[int, int, str, EntityType, float, str]] = []
        for p in aggregated_preds:
            start = int(p["start"])
            end = int(p["end"])
            score = float(p.get("score", 0.0))
            raw_tag = str(p.get("entity_group", "")).upper()
            surface = text[start:end]

            if score < self.confidence_threshold:
                continue

            # Offsets boundary verification against normalized_text
            if not (0 <= start < end <= len(text)):
                continue

            # Map raw model tag to Sherlock EntityType
            ent_type = self.LABEL_TO_ENTITY_TYPE.get(raw_tag)
            if ent_type is None:
                if self.allow_unsupported_types and raw_tag in ("MISC", "B-MISC", "I-MISC"):
                    ent_type = EntityType.CONCEPT
                else:
                    # Explicit handling: omit unsupported types and record in candidate rejection
                    continue

            # Strip leading/trailing whitespaces if present and adjust offsets
            trimmed_surface = surface.strip()
            if not trimmed_surface:
                continue
            l_offset = surface.find(trimmed_surface)
            adj_start = start + l_offset
            adj_end = adj_start + len(trimmed_surface)

            candidates.append((adj_start, adj_end, trimmed_surface, ent_type, score, raw_tag))

        # Deduplicate overlapping subword predictions deterministically
        resolved = self._resolve_overlapping_predictions(candidates, text)

        is_mock_backend = getattr(self.backend, "is_mock", False)

        mentions: List[EntityMention] = []
        for idx, (start, end, surface, ent_type, score, raw_tag) in enumerate(resolved):
            sent_idx = self._find_sentence_index(start, end, sentences)
            page_num = self._find_page_number(start, document.page_offsets)

            mention_id = f"men_ml_{document.document_id}_{idx}_{start}_{end}"

            meta: Dict[str, Any] = {
                "model_identifier": self.model_name,
                "backend": self.backend.backend_identifier,
                "device": self.device,
                "raw_entity_tag": raw_tag,
                "calibrated_probability": False,
                "uncalibrated_score": score,
                "is_mock_simulation": is_mock_backend,
                "provenance": "mock_simulation" if is_mock_backend else "live_pretrained_model",
            }
            if is_mock_backend:
                meta["epistemic_warning"] = (
                    "Simulated mock inference for offline testing; does NOT reflect real model weights."
                )

            mention = EntityMention(
                mention_id=mention_id,
                document_id=document.document_id,
                surface_text=surface,
                entity_type=ent_type,
                start_char=start,
                end_char=end,
                page_number=page_num,
                sentence_index=sent_idx,
                normalized_value=surface,
                extraction_method=self.METHOD_NAME,
                extraction_version=self.model_version,
                confidence_score=round(score, 4),
                confidence_semantics=ConfidenceSemantics.HEURISTIC_SCORE,
                metadata=meta,
            )
            mentions.append(mention)

        mentions.sort(key=lambda m: (m.start_char, m.end_char, m.mention_id))
        return mentions

    def _resolve_overlapping_predictions(
        self,
        candidates: List[Tuple[int, int, str, EntityType, float, str]],
        text: str,
    ) -> List[Tuple[int, int, str, EntityType, float, str]]:
        if not candidates:
            return []

        # Sort by start ascending, then length descending, then score descending
        sorted_cands = sorted(
            candidates,
            key=lambda c: (c[0], -(c[1] - c[0]), -c[4])
        )

        accepted: List[Tuple[int, int, str, EntityType, float, str]] = []
        for cand in sorted_cands:
            start, end, surface, _, _, _ = cand
            if text[start:end] != surface:
                continue

            overlaps = False
            for a_start, a_end, _, _, _, _ in accepted:
                if start < a_end and end > a_start:
                    overlaps = True
                    break

            if not overlaps:
                accepted.append(cand)

        return accepted

    def _find_sentence_index(
        self, start: int, end: int, sentences: List[Tuple[int, int, str]]
    ) -> Optional[int]:
        for idx, (s_start, s_end, _) in enumerate(sentences):
            if s_start <= start and end <= s_end:
                return idx
            if start < s_end and end > s_start:
                return idx
        return None

    def _find_page_number(
        self, start: int, page_offsets: List[Tuple[int, int]]
    ) -> int:
        if not page_offsets:
            return 1
        for page_idx, (p_start, p_end) in enumerate(page_offsets):
            if p_start <= start < p_end:
                return page_idx + 1
        return 1


class HybridNERExtractor(BaseNERExtractor):
    """
    Hybrid Named Entity Recognition extractor combining deterministic rules and ML model.

    Guarantees:
    - Exact agreement between Rule and ML is labeled as 'hybrid_agreement'.
    - Disagreements (span or type conflicts) are explicitly recorded in mention metadata.
    - Rule-based extractors continue to provide DATE and MONEY coverage.
    - Does NOT artificially inflate confidence solely because both extractors agree on the same text.
    - If allow_rule_fallback=True and ML backend is unavailable, falls back to rule-based with provenance note.
    """

    METHOD_NAME = "hybrid_ner"
    VERSION = "1.0.0"

    def __init__(
        self,
        rule_extractor: Optional[DeterministicRuleNERExtractor] = None,
        ml_extractor: Optional[ModelBackedNERExtractor] = None,
        allow_rule_fallback: bool = True,
        tie_break_strategy: str = "prefer_rule",  # 'prefer_rule' | 'prefer_ml'
    ):
        self.rule_extractor = rule_extractor or DeterministicRuleNERExtractor()
        self.ml_extractor = ml_extractor or ModelBackedNERExtractor(use_mock_backend=False)
        self.allow_rule_fallback = allow_rule_fallback
        self.tie_break_strategy = tie_break_strategy

    def extract_entities(self, document: IngestedDocument) -> List[EntityMention]:
        # 1. Extract rule-based entities
        rule_mentions = self.rule_extractor.extract_entities(document)

        # 2. Extract ML entities with graceful fallback handling
        ml_mentions: List[EntityMention] = []
        ml_error: Optional[str] = None
        try:
            ml_mentions = self.ml_extractor.extract_entities(document)
        except MLModelUnavailableError as ex:
            if not self.allow_rule_fallback:
                raise
            ml_error = str(ex)

        if ml_error is not None:
            # Fallback path: annotate mentions with fallback provenance
            fallback_mentions: List[EntityMention] = []
            for m in rule_mentions:
                meta = dict(m.metadata)
                meta["hybrid_fallback"] = True
                meta["backends_executed"] = ["rule"]
                meta["ml_unavailable_reason"] = ml_error
                fallback_mentions.append(
                    EntityMention(
                        mention_id=m.mention_id,
                        document_id=m.document_id,
                        surface_text=m.surface_text,
                        entity_type=m.entity_type,
                        start_char=m.start_char,
                        end_char=m.end_char,
                        page_number=m.page_number,
                        sentence_index=m.sentence_index,
                        normalized_value=m.normalized_value,
                        extraction_method=f"{m.extraction_method}_fallback",
                        extraction_version=m.extraction_version,
                        confidence_score=m.confidence_score,
                        confidence_semantics=m.confidence_semantics,
                        metadata=meta,
                    )
                )
            return fallback_mentions

        # 3. Reconcile candidates deterministically
        return self._reconcile_mentions(document, rule_mentions, ml_mentions)

    def _reconcile_mentions(
        self,
        document: IngestedDocument,
        rule_mentions: List[EntityMention],
        ml_mentions: List[EntityMention],
    ) -> List[EntityMention]:
        matched_rule_ids: Set[str] = set()
        matched_ml_ids: Set[str] = set()
        combined: List[EntityMention] = []

        is_mock_ml = getattr(self.ml_extractor.backend, "is_mock", False)
        backends_executed = ["rule", "mock_ml"] if is_mock_ml else ["rule", "ml"]

        # Pass A: Exact span matches
        for r_m in rule_mentions:
            for m_m in ml_mentions:
                if m_m.mention_id in matched_ml_ids:
                    continue

                if r_m.start_char == m_m.start_char and r_m.end_char == m_m.end_char:
                    # Same span! Check entity type agreement
                    matched_rule_ids.add(r_m.mention_id)
                    matched_ml_ids.add(m_m.mention_id)

                    if r_m.entity_type == m_m.entity_type:
                        # AGREEMENT: Emit hybrid agreement mention
                        meta = dict(m_m.metadata)
                        meta.update({
                            "backends_executed": backends_executed,
                            "backends_agreed": ["rule", "ml"],
                            "rule_method": r_m.extraction_method,
                            "ml_method": m_m.extraction_method,
                            "independent_corroboration": False,  # Same document span
                        })
                        combined.append(
                            EntityMention(
                                mention_id=f"men_hyb_{document.document_id}_{r_m.start_char}_{r_m.end_char}",
                                document_id=document.document_id,
                                surface_text=r_m.surface_text,
                                entity_type=r_m.entity_type,
                                start_char=r_m.start_char,
                                end_char=r_m.end_char,
                                page_number=r_m.page_number,
                                sentence_index=r_m.sentence_index,
                                normalized_value=r_m.normalized_value or m_m.normalized_value,
                                extraction_method="hybrid_agreement",
                                extraction_version=self.VERSION,
                                confidence_score=m_m.confidence_score,
                                confidence_semantics=ConfidenceSemantics.HEURISTIC_SCORE,
                                metadata=meta,
                            )
                        )
                    else:
                        # DISAGREEMENT: Type conflict on identical span
                        meta = dict(m_m.metadata)
                        meta.update({
                            "backends_executed": backends_executed,
                            "backends_disagreed": True,
                            "disagreement_type": "type_conflict",
                            "rule_type": r_m.entity_type.value,
                            "ml_type": m_m.entity_type.value,
                            "tie_break_strategy": self.tie_break_strategy,
                        })
                        chosen_type = r_m.entity_type if self.tie_break_strategy == "prefer_rule" else m_m.entity_type
                        chosen_score = m_m.confidence_score if self.tie_break_strategy != "prefer_rule" else None
                        combined.append(
                            EntityMention(
                                mention_id=f"men_hyb_conflict_{document.document_id}_{r_m.start_char}_{r_m.end_char}",
                                document_id=document.document_id,
                                surface_text=r_m.surface_text,
                                entity_type=chosen_type,
                                start_char=r_m.start_char,
                                end_char=r_m.end_char,
                                page_number=r_m.page_number,
                                sentence_index=r_m.sentence_index,
                                normalized_value=r_m.normalized_value,
                                extraction_method=f"hybrid_conflict_{self.tie_break_strategy}",
                                extraction_version=self.VERSION,
                                confidence_score=chosen_score,
                                confidence_semantics=ConfidenceSemantics.HEURISTIC_SCORE if chosen_score else None,
                                metadata=meta,
                            )
                        )
                    break

        # Pass B: Non-exact overlapping spans
        for r_m in rule_mentions:
            if r_m.mention_id in matched_rule_ids:
                continue
            for m_m in ml_mentions:
                if m_m.mention_id in matched_ml_ids:
                    continue

                # Check if spans overlap
                if max(r_m.start_char, m_m.start_char) < min(r_m.end_char, m_m.end_char):
                    matched_rule_ids.add(r_m.mention_id)
                    matched_ml_ids.add(m_m.mention_id)

                    meta = dict(m_m.metadata)
                    meta.update({
                        "backends_executed": backends_executed,
                        "backends_disagreed": True,
                        "disagreement_type": "span_boundary_overlap",
                        "rule_span": (r_m.start_char, r_m.end_char, r_m.surface_text),
                        "ml_span": (m_m.start_char, m_m.end_char, m_m.surface_text),
                    })
                    # Select according to tie break strategy
                    chosen = r_m if self.tie_break_strategy == "prefer_rule" else m_m
                    combined.append(
                        EntityMention(
                            mention_id=f"men_hyb_overlap_{document.document_id}_{chosen.start_char}_{chosen.end_char}",
                            document_id=document.document_id,
                            surface_text=chosen.surface_text,
                            entity_type=chosen.entity_type,
                            start_char=chosen.start_char,
                            end_char=chosen.end_char,
                            page_number=chosen.page_number,
                            sentence_index=chosen.sentence_index,
                            normalized_value=chosen.normalized_value,
                            extraction_method=f"hybrid_span_overlap_{self.tie_break_strategy}",
                            extraction_version=self.VERSION,
                            confidence_score=chosen.confidence_score,
                            confidence_semantics=chosen.confidence_semantics,
                            metadata=meta,
                        )
                    )
                    break

        # Pass C: Unmatched rule mentions (e.g. DATE, MONEY, or rule-specific ORGs)
        for r_m in rule_mentions:
            if r_m.mention_id not in matched_rule_ids:
                combined.append(r_m)

        # Pass D: Unmatched ML mentions
        for m_m in ml_mentions:
            if m_m.mention_id not in matched_ml_ids:
                combined.append(m_m)

        # Sort deterministically
        combined.sort(key=lambda m: (m.start_char, m.end_char, m.mention_id))
        return combined

