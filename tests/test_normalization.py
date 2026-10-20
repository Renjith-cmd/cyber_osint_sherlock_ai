import datetime
import pytest
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
    strip_punctuation,
    tokenize_name,
)


def test_normalize_text_unicode_and_casefold():
    # German Eszett
    assert normalize_text("STRAßE") == "strasse"
    # Accents with NFKC
    assert normalize_text("Café") == "café"
    # Cyrillic
    assert normalize_text("Иван") == "иван"
    # Greek
    assert normalize_text("ΣΩΚΡΑΤΗΣ") == "σωκρατησ" or normalize_text("ΣΩΚΡΑΤΗΣ") == "σωκράτης".replace("ά", "α")


def test_normalize_text_whitespace_collapsing():
    assert normalize_text("  John   \t  Doe \n\n ") == "john doe"
    assert normalize_text("") == ""
    assert normalize_text(None) == ""
    assert normalize_text("   ") == ""


def test_strip_punctuation():
    # Replacing with space preserves token boundaries
    assert strip_punctuation("B. Wayne") == "b wayne"
    assert strip_punctuation("Smith, John") == "smith john"
    assert strip_punctuation("semi-conductor") == "semi conductor"
    # Without space replacement
    assert strip_punctuation("B. Wayne", replace_with_space=False) == "b wayne"
    assert strip_punctuation("U.S.A.", replace_with_space=False) == "usa"
    # Non-Latin characters preserved
    assert strip_punctuation("«Война и мир»") == "война и мир"
    assert strip_punctuation(None) == ""


def test_tokenize_name():
    assert tokenize_name("John Doe") == ["john", "doe"]
    assert tokenize_name("B. Wayne", min_length=2) == ["wayne"]
    assert tokenize_name("B. Wayne", min_length=1) == ["b", "wayne"]
    assert tokenize_name("  ", min_length=1) == []
    assert tokenize_name(None) == []


def test_extract_initials():
    # Multi-token organization
    assert extract_initials("International Business Machines") == "ibm"
    # Single acronym token
    assert extract_initials("IBM") == "ibm"
    assert extract_initials("NASA") == "nasa"
    # Person name
    assert extract_initials("Bruce Wayne") == "bw"
    # Empty
    assert extract_initials("") == ""
    assert extract_initials(None) == ""


def test_name_fingerprint():
    # Order-invariant representation
    assert name_fingerprint("Smith, John") == "john smith"
    assert name_fingerprint("John Smith") == "john smith"
    assert name_fingerprint("Alice Bob Charlie") == "alice bob charlie"
    assert name_fingerprint("Charlie Alice Bob") == "alice bob charlie"
    assert name_fingerprint("") == ""
    assert name_fingerprint(None) == ""


def test_soundex_latin_and_variations():
    # Spelling variation: Sarah vs Sara
    assert soundex("Sarah") == "S600"
    assert soundex("Sara") == "S600"
    # Connor
    assert soundex("Connor") == "C560"
    assert soundex("Conner") == "C560"
    # Accented Latin: José decomposes to Jose
    assert soundex("José") == "J200"
    assert soundex("Jose") == "J200"


def test_soundex_edge_cases():
    assert soundex("") == ""
    assert soundex(None) == ""
    assert soundex("1234") == ""
    # Non-Latin tokens return empty string safely
    assert soundex("Иван") == ""
    # Single letter
    assert soundex("A") == "A000"


def test_normalize_attribute_value():
    assert normalize_attribute_value(None) == ""
    assert normalize_attribute_value("  Detroit  ") == "detroit"
    assert normalize_attribute_value(1980) == "1980"
    assert normalize_attribute_value(True) == "true"
    
    # Dates
    d = datetime.date(1980, 1, 1)
    assert normalize_attribute_value(d) == "1980-01-01"
    
    # Collections
    assert normalize_attribute_value(["apple", "banana"]) == "apple,banana"
    assert normalize_attribute_value({"b": 2, "a": 1}) == "a:1;b:2"


def test_normalize_address():
    # Street abbreviations: blv. vs blvd. vs boulevard -> canonical boulevard
    assert normalize_address("100 Sunset Blv.") == "100 sunset boulevard"
    assert normalize_address("100 Sunset Boulevard") == "100 sunset boulevard"
    assert normalize_address("500 S. Michigan Ave.") == "500 south michigan avenue"
    assert normalize_address("500 South Michigan Avenue") == "500 south michigan avenue"
    assert normalize_address("123 N. Main St.") == "123 north main street"
    assert normalize_address("123 North Main Street") == "123 north main street"
    # Ordinal street numbers
    assert normalize_address("200 Fifth Avenue") == "200 5th avenue"
    assert normalize_address("200 5th Ave.") == "200 5th avenue"
    # Cross street clauses stripped
    assert normalize_address("100 5th Ave between 90th and 91st sts.") == "100 5th avenue"
    assert normalize_address("450 W. 42nd St at 10th Ave") == "450 west 42nd street"
    # Edge cases
    assert normalize_address("") == ""
    assert normalize_address(None) == ""


def test_extract_address_components():
    num, st = extract_address_components("100 sunset blvd")
    assert num == "100"
    assert st == "sunset boulevard"

    num, st = extract_address_components("3434 peachtree rd ne")
    assert num == "3434"
    assert st == "peachtree road northeast"

    # No number
    num, st = extract_address_components("broadway")
    assert num is None
    assert st == "broadway"

    # Empty
    assert extract_address_components("") == (None, "")
    assert extract_address_components(None) == (None, "")


def test_normalize_city():
    assert normalize_city("New York City") == "new york"
    assert normalize_city("NYC") == "new york"
    assert normalize_city("N.Y.C.") == "new york"
    assert normalize_city("Washington, D.C.") == "washington dc"
    assert normalize_city("Washington DC") == "washington dc"
    assert normalize_city("Los Angeles, CA") == "los angeles"
    assert normalize_city("") == ""
    assert normalize_city(None) == ""


def test_normalize_business_name():
    # Parenthetical qualifier stripping
    assert normalize_business_name("Ritz-Carlton (Buckhead)") == "ritz carlton"
    assert normalize_business_name("Art's Delicatessen (Los Angeles)") == "arts deli"
    assert normalize_business_name("Art's Deli") == "arts deli"
    # Business abbreviation canonicalization
    assert normalize_business_name("Smith & Jones Co., Inc.") == "smith jones co inc"
    assert normalize_business_name("International Restaurant") == "international restaurant"
    assert normalize_business_name("") == ""
    assert normalize_business_name(None) == ""
