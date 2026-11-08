from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from nadeg.main import app
from nadeg.maintenance import MaintenanceProblem, calculate_maintenance
from nadeg.maintenance_io import ImportRegulation, import_regulation, csv_maintenance


def payload(resource="800", periods=("50", "100", "200")):
    return {"title": "Пользовательская система", "resource": resource, "flight_time": "1", "flights_per_day": 4,
            "periods": [{"id": f"P{i+1}", "interval": p} for i, p in enumerate(periods)],
            "operations": [{"name": "Осмотр", "labor": {key: "0" for key in
                            ["preliminary", "preflight", "turnaround", "postflight", *[f"P{i+1}" for i in range(len(periods))]]}}]}


@pytest.fixture
def guide():
    # Manual, pp.72–73: fixture only; production UI contains no catalogue/variants.
    data = payload()
    rows = [
        ["Осмотр авиашины", ".02", ".02", ".05", ".05", 0, 0, 0],
        ["Осмотр стойки", ".02", ".02", ".05", ".05", 0, 0, 0],
        ["Осмотр замка убранного положения", ".02", ".05", 0, 0, 0, 0, 0],
        ["Осмотр шлангов и трубопроводов", ".02", ".08", ".05", ".05", 0, 0, 0],
        ["Осмотр щитков стойки", ".05", ".05", ".05", ".05", 0, 0, 0],
        ["Снять, обслужить и установить колесо", 0, 0, 0, 0, ".5", ".5", ".5"],
        ["Проверить тормоза", 0, 0, 0, 0, ".3", ".3", ".3"],
        ["Разборка и дефектовка тормоза", 0, 0, 0, 0, 0, 0, 1],
        ["Наполнить узлы смазкой", 0, 0, 0, 0, ".5", ".5", ".5"],
        ["Замерить люфты", 0, 0, 0, 0, ".5", ".5", ".5"],
        ["Проверить уровень масла", 0, 0, 0, 0, 0, ".05", ".05"],
        ["Проверить давление азота", 0, 0, 0, 0, ".05", ".05", ".05"],
        ["Контрольная уборка и выпуск", 0, 0, 0, 0, ".08", ".08", ".08"],
        ["Повторная контрольная уборка и выпуск", 0, 0, 0, 0, ".16", ".16", ".16"],
    ]
    keys = list(data["operations"][0]["labor"])
    data["operations"] = [{"name": r[0], "labor": dict(zip(keys, map(str, r[1:])))} for r in rows]
    return data


def test_guide_example(guide):
    r = calculate_maintenance(MaintenanceProblem(**guide))
    assert r["flight_days"] == "200"
    assert [f["count"] for f in r["forms"]] == ["100", "200", "600", "200", "8", "4", "3"]
    assert [Decimal(f["per_service"]) for f in r["forms"]] == list(map(Decimal, [".13", ".22", ".2", ".2", "2.09", "2.14", "3.14"]))
    assert r["total_labor"] == "251.7"
    assert r["specific_labor"] == "0.314625"
    assert sum(Decimal(op["total"]) for op in r["operations"]) == Decimal("251.7")


@pytest.mark.parametrize("resource,expected", [("49", [0, 0, 0]), ("50", [0, 0, 0]), ("50.01", [1, 0, 0]),
    ("100", [1, 0, 0]), ("100.01", [1, 1, 0]), ("200", [2, 1, 0]), ("200.01", [2, 1, 1]), ("800", [8, 4, 3]), ("825", [8, 4, 4])])
def test_repair_boundary_and_replacement(resource, expected):
    result = calculate_maintenance(MaintenanceProblem(**payload(resource)))
    assert [int(f["count"]) for f in result["forms"][4:]] == expected


def test_custom_nested_periods_against_event_enumeration():
    for resource in range(1, 151):
        data = payload(str(resource), ("3", "6", "18"))
        expected = [0, 0, 0]
        for tick in range(3, resource, 3):
            selected = max(i for i, period in enumerate([3, 6, 18]) if tick % period == 0)
            expected[selected] += 1
        r = calculate_maintenance(MaintenanceProblem(**data))
        assert [int(f["count"]) for f in r["forms"][4:]] == expected


def test_decimal_periods_and_exact_divisibility():
    r = calculate_maintenance(MaintenanceProblem(**payload("1,2", ("0,1", "0,3", "0,6"))))
    assert [int(f["count"]) for f in r["forms"][4:]] == [8, 2, 1]


def test_fractional_days_are_never_rounded_in_totals():
    data = payload("1000")
    data["flight_time"], data["flights_per_day"] = "1.5", 3
    data["operations"][0]["labor"]["preliminary"] = "1"
    r = calculate_maintenance(MaintenanceProblem(**data))
    assert r["flight_days_exact"] == "2000/9"
    with localcontext() as context:
        context.prec = 60
        assert Decimal(r["total_labor"]) == Decimal(1000) / 9
        assert Decimal(r["specific_labor"]) == Decimal(1) / 9


def test_large_schedule_has_no_event_loop():
    r = calculate_maintenance(MaintenanceProblem(**payload("1e12", ("1e-30",))))
    assert int(r["forms"][4]["count"]) == 10**42 - 1


@pytest.mark.parametrize("field,value", [("resource", "0"), ("flight_time", "0"), ("flight_time", "NaN"),
    ("flights_per_day", "1.5"), ("flights_per_day", True), ("flights_per_day", 0)])
def test_invalid_settings(field, value):
    data = payload(); data[field] = value
    with pytest.raises(ValidationError):
        MaintenanceProblem(**data)


@pytest.mark.parametrize("periods", [("50", "120"), ("100", "50"), ("50", "50"), ("0",), ("-1",)])
def test_invalid_periods(periods):
    with pytest.raises(ValidationError):
        MaintenanceProblem(**payload(periods=periods))


def test_negative_unknown_and_missing_labor_are_rejected():
    for mutation in ["negative", "missing", "unknown"]:
        data = payload()
        if mutation == "negative": data["operations"][0]["labor"]["P1"] = "-1"
        elif mutation == "missing": del data["operations"][0]["labor"]["P1"]
        else: data["operations"][0]["labor"]["P99"] = "1"
        with pytest.raises(ValidationError):
            MaintenanceProblem(**data)


def test_zero_labor_and_one_flight_per_day():
    data = payload(); data["flights_per_day"] = 1
    r = calculate_maintenance(MaintenanceProblem(**data))
    assert r["total_labor"] == "0" and r["specific_labor"] == "0"
    assert r["forms"][2]["count"] == "0"
    assert all(f["share_percent"] == "0" for f in r["forms"])


def test_api_and_csv_roundtrip(guide):
    problem = MaintenanceProblem(**guide)
    with TestClient(app) as c:
        assert c.get('/lab2').status_code == 200
        assert '/lab2' in c.get('/').text
        response = c.post('/api/lab2/calculate', json=guide)
        assert response.status_code == 200 and response.json()['total_labor'] == '251.7'
        csv = c.post('/api/lab2/export/csv', json=guide)
        imported = c.post('/api/lab2/import', json={'periods': guide['periods'], 'text': csv.content.decode('utf-8-sig')})
        assert imported.status_code == 200
        assert imported.json()['operations'] == [op.model_dump(mode='json') for op in problem.operations]


def test_clipboard_headerless_and_russian_headers():
    data = payload()
    for text in ['Осмотр\t0,1\t0,2\t0\t0,3\t0,4\t0,5\t0,6',
                 'Операция;Предварительная;Предполётная;Повторный вылет;Послеполётная;50;100;200\nОсмотр;0,1;0,2;0;0,3;0,4;0,5;0,6']:
        result = import_regulation(ImportRegulation(periods=data['periods'], text=text))
        assert result['operations'][0]['labor']['P3'] == '0.6'


def test_csv_formula_injection_escaping(guide):
    guide['operations'][0]['name'] = '=HYPERLINK("test")'
    p = MaintenanceProblem(**guide)
    content = csv_maintenance(p, calculate_maintenance(p)).decode('utf-8-sig')
    assert "'=HYPERLINK" in content


def test_csv_roundtrip_preserves_decimal_period_notation():
    for periods in [("50.0", "100.0", "200.0"), ("5e1", "1e2", "2e2")]:
        p = MaintenanceProblem(**payload(periods=periods))
        content = csv_maintenance(p, calculate_maintenance(p)).decode('utf-8-sig')
        imported = import_regulation(ImportRegulation(text=content, periods=p.periods))
        assert imported['operations'] == [op.model_dump(mode='json') for op in p.operations]


def test_settings_validation_and_separate_lab1(guide):
    with TestClient(app) as c:
        settings = {k: v for k, v in guide.items() if k != 'operations'}
        assert c.post('/api/lab2/validate', json=settings).status_code == 200
        settings['periods'][1]['interval'] = '120'
        assert c.post('/api/lab2/validate', json=settings).status_code == 422
        lab1 = {'time': 1, 'rate_scale': '1', 'expression': 'A', 'elements': [{'id': 'A', 'rate': '.1'}]}
        assert c.post('/api/analyze', json=lab1).json()['probability'] == '0.9'


def test_pdf_export(guide):
    with TestClient(app) as c:
        response = c.post('/api/lab2/export/pdf', json=guide)
        assert response.status_code == 200 and response.content.startswith(b'%PDF-')
