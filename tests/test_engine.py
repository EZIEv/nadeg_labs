from decimal import Decimal
from itertools import product
import random

import pytest
from pydantic import ValidationError

from nadeg.engine import ModelError, calculate, optimize, parse
from nadeg.models import Problem


def problem(expression="A & B", rates=("0.1", "0.2"), masses=None, **kwargs):
    return Problem(time="1", rate_scale="1", expression=expression,
                   elements=[{"id": chr(65 + i), "rate": rate, "mass": (masses or ["1"] * len(rates))[i], "max_reserves": 2} for i, rate in enumerate(rates)], **kwargs)


def test_series_and_reserves_follow_guide():
    assert Decimal(calculate(problem())["probability"]) == Decimal("0.7")
    p = problem("A")
    p.elements[0].reserves = 1
    assert Decimal(calculate(p)["probability"]) == Decimal("0.99")


def test_only_methodical_model_is_accepted():
    assert problem().model == "methodical"
    for unsupported in ["linear", "exponential"]:
        with pytest.raises(ValidationError):
            problem(model=unsupported)


def test_nested_serial_groups_follow_the_same_formula():
    assert calculate(problem("A & (B)", ("0.1", "0.2")))["probability"] == "0.7"


def test_units_and_decimal_comma():
    p = Problem(time="4", rate_scale="1e-4", expression="A", elements=[{"id": "a", "rate": "0,93"}])
    assert Decimal(calculate(p)["probability"]) == Decimal("0.999628")


def test_tiny_failure_is_preserved():
    p = problem("A & B", ("1e-20", "1e-20"))
    p.elements[0].reserves = p.elements[1].reserves = 2
    assert Decimal(calculate(p)["failure_probability"]) > 0


def test_methodical_formula_and_manual_variant_one():
    # Guide, table 3 / page 44, variant 1. Test fixture only, no catalogue in UI.
    rates = [Decimal("0.1") + Decimal("0.2") * i for i in range(10)]
    masses = ["0.5", "1.2", "1.5", "2.0", "2.4", "3.0", "3.7", "4.2", "4.8", "5.3"]
    p = problem(" & ".join(chr(65 + i) for i in range(10)), rates, masses, target="0.9999")
    p.rate_scale = "1e-4"
    r = calculate(p)
    assert Decimal(r["probability"]) == Decimal("0.999")
    assert Decimal(r["mass"]) == Decimal("28.6")
    p.elements[-1].reserves = 1
    assert Decimal(calculate(p)["failure_probability"]) == Decimal("0.0008100361")


def test_methodical_rejects_parallel_and_repeated_nodes():
    for expression in ("A | B", "A & A", "(A & B) | A"):
        with pytest.raises(ModelError):
            calculate(problem(expression))


def test_negative_system_probability_is_not_clamped():
    with pytest.raises(ModelError, match="P < 0"):
        calculate(problem(rates=("0.7", "0.7")))


def test_optimal_search_prefers_a_cheaper_non_greedy_solution():
    p = problem(masses=["10", "1"], rates=("0.02", "0.0015"), target="0.9799")
    r = optimize(p)
    assert r["optimization"]["status"] == "optimal"
    assert [e["reserves"] for e in r["elements"]] == [0, 1]
    assert Decimal(r["mass"]) == 12


def test_optimizer_matches_exhaustive_search_for_serial_structures():
    rng = random.Random(17)
    for expression in ["A & B & C", "A & (B & C)", "(A & B) & C", "C & A & B"]:
        for _ in range(4):
            rates = [str(rng.randint(1, 4) / 100) for i in range(3)]
            masses = [str(rng.randint(1, 5)) for i in range(3)]
            p = problem(expression, rates, masses, target="0.999")
            feasible = []
            for vector in product(range(3), repeat=3):
                trial = p.model_copy(deep=True)
                for e, k in zip(trial.elements, vector):
                    e.reserves = k
                r = calculate(trial)
                if r["target_met"]:
                    feasible.append(Decimal(r["mass"]))
            r = optimize(p)
            if feasible:
                assert r["optimization"]["status"] == "optimal"
                assert Decimal(r["mass"]) == min(feasible)
            else:
                assert r["optimization"]["status"] == "infeasible"


def test_resource_limit_never_claims_optimality():
    p = problem(rates=("0.1", "0.2"), target="0.99", search_limit=1)
    r = optimize(p)
    assert r["optimization"]["status"] in {"feasible", "limit"}
    assert "не подтверждена" in r["optimization"]["reason"]


def test_mass_limit_and_forbidden_reserves():
    p = problem(target="0.99", max_mass="2")
    assert optimize(p)["optimization"]["status"] == "infeasible"
    p = problem(target="0.99")
    for e in p.elements:
        e.reservable = False
    assert optimize(p)["optimization"]["status"] == "infeasible"


def test_existing_reserves_are_lower_bounds():
    p = problem(target="0.9")
    for e in p.elements:
        e.reserves = 1
    r = optimize(p)
    assert [e["reserves"] for e in r["elements"]] == [1, 1]


def test_unused_component_is_not_optimized_but_has_mass():
    p = problem("A", target="0.99")
    r = optimize(p)
    assert r["elements"][1]["reserves"] == 0
    assert r["elements"][1]["used"] is False
    assert Decimal(r["mass"]) >= 3


@pytest.mark.parametrize("expression", ["A &", "A B", "A & Z", "(A | B", "A | )", "__import__('os')", ""])
def test_invalid_expressions_are_not_executed(expression):
    with pytest.raises((ModelError, ValidationError)):
        calculate(problem(expression))


@pytest.mark.parametrize("rate", ["NaN", "Infinity", "-0.1", "1e-999", True])
def test_invalid_numbers(rate):
    with pytest.raises(ValidationError):
        problem(rates=(rate, "0.2"))


def test_guide_applicability_and_duplicate_ids():
    with pytest.raises(ModelError):
        calculate(problem(rates=("1.1", "0.2")))
    with pytest.raises(ValidationError):
        Problem(time=1, expression="A", elements=[{"id": "A", "rate": 0}, {"id": "a", "rate": 0}])


def test_operator_aliases_and_precedence():
    assert parse("A И B ИЛИ C", {"A", "B", "C"}) == parse("A AND B OR C", {"A", "B", "C"})
