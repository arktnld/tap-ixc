"""Testes unitários para etl.core.contracts."""
from pydantic import BaseModel

from tap_ixc.core.contracts import sanitize, validate_batch


class TestSanitize:
    def test_empty_string_becomes_none(self):
        assert sanitize({"x": ""})["x"] is None
        assert sanitize({"x": "   "})["x"] is None

    def test_zero_date_becomes_none(self):
        assert sanitize({"d": "0000-00-00"})["d"] is None
        assert sanitize({"d": "0000-00-00 00:00:00"})["d"] is None

    def test_zero_month_or_day_becomes_none(self):
        assert sanitize({"d": "2024-00-01"})["d"] is None
        assert sanitize({"d": "2024-03-00"})["d"] is None

    def test_impossible_date_becomes_none(self):
        assert sanitize({"d": "2024-02-30"})["d"] is None

    def test_valid_date_kept(self):
        assert sanitize({"d": "2024-03-15"})["d"] == "2024-03-15"

    def test_valid_datetime_kept(self):
        assert sanitize({"d": "2024-03-15 10:30:00"})["d"] == "2024-03-15 10:30:00"

    def test_non_date_string_kept(self):
        assert sanitize({"x": "hello"})["x"] == "hello"

    def test_non_string_values_kept(self):
        assert sanitize({"n": 42, "b": True, "f": 3.14}) == {"n": 42, "b": True, "f": 3.14}

    def test_none_value_kept(self):
        assert sanitize({"x": None})["x"] is None


class TestValidateBatch:
    def test_no_schema_sanitizes_only(self):
        records = [{"name": "João", "date": "0000-00-00"}, {"name": "Maria", "date": ""}]
        valid, dead = validate_batch(records)
        assert len(valid) == 2
        assert len(dead) == 0
        assert valid[0]["date"] is None
        assert valid[1]["date"] is None

    def test_with_schema_separates_invalid(self):
        class ClientSchema(BaseModel):
            id: int
            name: str

        records = [
            {"id": 1, "name": "João"},
            {"id": "nao-e-inteiro", "name": "Maria"},
            {"id": 3, "name": "Pedro"},
        ]
        valid, dead = validate_batch(records, schema=ClientSchema)
        assert len(valid) == 2
        assert len(dead) == 1
        assert dead[0]["record"]["id"] == "nao-e-inteiro"

    def test_empty_batch(self):
        valid, dead = validate_batch([])
        assert valid == []
        assert dead == []
