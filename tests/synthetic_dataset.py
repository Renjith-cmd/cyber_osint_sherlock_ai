from src.core.models import Record, EntityType, CandidatePair

# A fictional, deterministic dataset for entity resolution evaluation.
# Cases covered:
# 1. Exact duplicate
# 2. Abbreviation
# 3. Typo
# 4. Missing attribute
# 5. Common name but different people
# 6. Same organization but different people
# 7. Conflicting attribute
# 8. Alias
# 9. Multiple records representing one person (transitive)
# 10. Clearly unrelated records

def get_fictional_records():
    return [
        # 1. Exact duplicate
        Record(record_id="r1a", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"dob": "1980-01-01"}),
        Record(record_id="r1b", source_id="s1", entity_type=EntityType.PERSON, raw_name="John Doe", structured_attributes={"dob": "1980-01-01"}),
        
        # 2. Abbreviation
        Record(record_id="r2a", source_id="s2", entity_type=EntityType.ORGANIZATION, raw_name="International Business Machines", structured_attributes={"country": "USA"}),
        Record(record_id="r2b", source_id="s2", entity_type=EntityType.ORGANIZATION, raw_name="IBM", structured_attributes={"country": "USA"}),
        
        # 3. Typo
        Record(record_id="r3a", source_id="s3", entity_type=EntityType.PERSON, raw_name="Sarah Connor", structured_attributes={"city": "Los Angeles"}),
        Record(record_id="r3b", source_id="s3", entity_type=EntityType.PERSON, raw_name="Sara Connor", structured_attributes={"city": "Los Angeles"}),
        
        # 4. Missing attribute
        Record(record_id="r4a", source_id="s4", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={"phone": "555-1234"}),
        Record(record_id="r4b", source_id="s4", entity_type=EntityType.PERSON, raw_name="Alice Smith", structured_attributes={}),
        
        # 5. Common name but different people
        Record(record_id="r5a", source_id="s5", entity_type=EntityType.PERSON, raw_name="Michael Jordan", structured_attributes={"occupation": "Basketball Player"}),
        Record(record_id="r5b", source_id="s5", entity_type=EntityType.PERSON, raw_name="Michael Jordan", structured_attributes={"occupation": "AI Researcher"}),
        
        # 6. Same organization but different people
        Record(record_id="r6a", source_id="s6", entity_type=EntityType.PERSON, raw_name="Employee A", structured_attributes={"org": "Cyberdyne Systems"}),
        Record(record_id="r6b", source_id="s6", entity_type=EntityType.PERSON, raw_name="Employee B", structured_attributes={"org": "Cyberdyne Systems"}),
        
        # 7. Conflicting attribute
        Record(record_id="r7a", source_id="s7", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"dob": "1960-05-12"}),
        Record(record_id="r7b", source_id="s7", entity_type=EntityType.PERSON, raw_name="David Bowman", structured_attributes={"dob": "1985-09-30"}),
        
        # 8. Alias
        Record(record_id="r8a", source_id="s8", entity_type=EntityType.PERSON, raw_name="Marshall Mathers", structured_attributes={"city": "Detroit"}),
        Record(record_id="r8b", source_id="s8", entity_type=EntityType.PERSON, raw_name="Eminem", structured_attributes={"city": "Detroit"}),
        
        # 9. Multiple records representing one person (r9a == r9b, r9b == r9c -> r9a == r9c)
        Record(record_id="r9a", source_id="s9", entity_type=EntityType.PERSON, raw_name="Bruce Wayne", structured_attributes={"role": "CEO"}),
        Record(record_id="r9b", source_id="s9", entity_type=EntityType.PERSON, raw_name="B. Wayne", structured_attributes={"role": "CEO", "city": "Gotham"}),
        Record(record_id="r9c", source_id="s9", entity_type=EntityType.PERSON, raw_name="Bruce Wayne", structured_attributes={"city": "Gotham"}),
        
        # 10. Clearly unrelated
        Record(record_id="r10a", source_id="s10", entity_type=EntityType.ORGANIZATION, raw_name="Acme Corp", structured_attributes={"type": "Manufacturing"}),
        Record(record_id="r10b", source_id="s10", entity_type=EntityType.LOCATION, raw_name="Mount Everest", structured_attributes={"type": "Mountain"}),
    ]

def get_candidate_pairs():
    pairs = []
    def add(ida, idb):
        pairs.append(CandidatePair(candidate_id=f"cp_{ida}_{idb}", left_record_id=ida, right_record_id=idb, generation_method="synthetic"))
    
    add("r1a", "r1b")
    add("r2a", "r2b")
    add("r3a", "r3b")
    add("r4a", "r4b")
    add("r5a", "r5b")
    add("r6a", "r6b")
    add("r7a", "r7b")
    add("r8a", "r8b")
    add("r9a", "r9b")
    add("r9b", "r9c")
    add("r9a", "r9c")
    add("r10a", "r10b")
    return pairs

GROUND_TRUTH = {
    "cp_r1a_r1b": True,   # Exact duplicate
    "cp_r2a_r2b": True,   # Abbreviation
    "cp_r3a_r3b": True,   # Typo
    "cp_r4a_r4b": True,   # Missing attribute (highly likely match)
    "cp_r5a_r5b": False,  # Common name, diff people
    "cp_r6a_r6b": False,  # Same org, diff people
    "cp_r7a_r7b": False,  # Conflicting attribute
    "cp_r8a_r8b": True,   # Alias
    "cp_r9a_r9b": True,   # Transitive a=b
    "cp_r9b_r9c": True,   # Transitive b=c
    "cp_r9a_r9c": True,   # Transitive a=c
    "cp_r10a_r10b": False # Unrelated
}

GROUND_TRUTH_CLUSTERS = {
    "r1a": "c_john_doe",
    "r1b": "c_john_doe",
    "r2a": "c_ibm",
    "r2b": "c_ibm",
    "r3a": "c_sarah_connor",
    "r3b": "c_sarah_connor",
    "r4a": "c_alice_smith",
    "r4b": "c_alice_smith",
    "r5a": "c_mj_basketball",
    "r5b": "c_mj_ai",
    "r6a": "c_emp_a",
    "r6b": "c_emp_b",
    "r7a": "c_bowman_1",
    "r7b": "c_bowman_2",
    "r8a": "c_eminem",
    "r8b": "c_eminem",
    "r9a": "c_bruce_wayne",
    "r9b": "c_bruce_wayne",
    "r9c": "c_bruce_wayne",
    "r10a": "c_acme",
    "r10b": "c_everest",
}
