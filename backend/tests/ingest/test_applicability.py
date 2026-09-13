from app.ingest.applicability import (
    extract_building_classes,
    extract_climate_zones,
    extract_jurisdiction,
)
from tests.ingest.conftest import parse


def test_extract_building_classes_strips_the_class_prefix():
    el = parse('<clause building="Class 2,Class 3,Class 9a"/>')

    assert extract_building_classes(el) == ["2", "3", "9a"]


def test_extract_building_classes_missing_attribute_is_empty():
    el = parse("<clause/>")

    assert extract_building_classes(el) == []


def test_extract_climate_zones_pulls_the_number_out_of_each_entry():
    el = parse('<clause climate="Climate zone 1,Climate zone 2,Climate zone 8"/>')

    assert extract_climate_zones(el) == [1, 2, 8]


def test_extract_climate_zones_missing_attribute_is_empty():
    el = parse("<clause/>")

    assert extract_climate_zones(el) == []


def test_extract_jurisdiction_returns_the_state_as_a_single_item_list():
    el = parse('<subclause state="NSW"/>')

    assert extract_jurisdiction(el) == ["NSW"]


def test_extract_jurisdiction_empty_state_is_national_i_e_none():
    el = parse('<subclause state=""/>')

    assert extract_jurisdiction(el) is None


def test_extract_jurisdiction_missing_attribute_is_none():
    el = parse("<subclause/>")

    assert extract_jurisdiction(el) is None
