"""Tests for RIQA-37, RIQA-38, RIQA-39 input validation."""

import unittest

from pydantic import ValidationError

from api import InputsUpdate, TankEnvironmentUpdate, UserTypeUpdate


def _valid_tank(**overrides):
    base = {
        "fresh_capacity_gal": 100,
        "grey_capacity_gal": 80,
        "black_capacity_gal": 40,
        "current_fresh_gal": 100,
        "current_grey_gal": 0,
        "current_black_gal": 0,
        "climate_multiplier": 1.0,
        "target_autonomy_days": 5,
    }
    base.update(overrides)
    return base


class TankValidationTests(unittest.TestCase):
    def test_target_autonomy_accepts_integer(self):
        t = TankEnvironmentUpdate(**_valid_tank(target_autonomy_days=7))
        self.assertEqual(t.target_autonomy_days, 7)

    def test_target_autonomy_rejects_decimal(self):
        with self.assertRaises(ValidationError):
            TankEnvironmentUpdate(**_valid_tank(target_autonomy_days=7.5))

    def test_target_autonomy_rejects_blank(self):
        with self.assertRaises(ValidationError):
            TankEnvironmentUpdate(**_valid_tank(target_autonomy_days=""))

    def test_current_fresh_rejects_blank(self):
        with self.assertRaises(ValidationError):
            TankEnvironmentUpdate(**_valid_tank(current_fresh_gal=""))

    def test_current_grey_rejects_blank(self):
        with self.assertRaises(ValidationError):
            TankEnvironmentUpdate(**_valid_tank(current_grey_gal=""))

    def test_climate_multiplier_rejects_blank(self):
        with self.assertRaises(ValidationError):
            TankEnvironmentUpdate(**_valid_tank(climate_multiplier=""))


class PeopleValidationTests(unittest.TestCase):
    def test_count_accepts_integer(self):
        u = UserTypeUpdate(name="Expert", count=2, is_child=0)
        self.assertEqual(u.count, 2)

    def test_count_rejects_decimal(self):
        with self.assertRaises(ValidationError):
            UserTypeUpdate(name="Expert", count=1.5, is_child=0)

    def test_count_blank_becomes_zero(self):
        u = UserTypeUpdate(name="Expert", count="", is_child=0)
        self.assertEqual(u.count, 0)


class ApiValidationTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from api import app

        self.client = TestClient(app)

    def test_put_rejects_decimal_target_autonomy(self):
        r = self.client.put(
            "/api/inputs",
            json={"tank_environment": _valid_tank(target_autonomy_days=7.5)},
        )
        self.assertEqual(r.status_code, 422)

    def test_put_rejects_blank_current_fresh(self):
        r = self.client.put(
            "/api/inputs",
            json={"tank_environment": _valid_tank(current_fresh_gal="")},
        )
        self.assertEqual(r.status_code, 422)

    def test_put_rejects_decimal_occupant_count(self):
        r = self.client.put(
            "/api/inputs",
            json={
                "user_types": [
                    {"name": "Expert", "count": 1.5, "is_child": 0},
                    {"name": "Typical", "count": 0, "is_child": 0},
                    {"name": "Glamper", "count": 0, "is_child": 0},
                    {"name": "Children", "count": 0, "is_child": 1},
                    {"name": "Adults Total", "count": 0, "is_child": 0},
                ]
            },
        )
        self.assertEqual(r.status_code, 422)

    def test_put_accepts_valid_integer_autonomy(self):
        r = self.client.put(
            "/api/inputs",
            json={"tank_environment": _valid_tank(target_autonomy_days=7)},
        )
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
