import json
from datetime import date
from pathlib import Path

import requests

import supabase


class MockResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self.payload = payload
        self.text = text if text is not None else json.dumps(payload or [])
        self.content = self.text.encode() if self.text else b""

    def json(self):
        return self.payload


def configure_supabase(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")


def simulation_request(**overrides):
    fields = {
        "location": "TH_NP15_GEN-APND",
        "market": "RTM",
        "date": "2025-07-18",
        "power_mw": 10,
        "duration_hours": 4,
        "round_trip_efficiency": 0.8,
        "cycles": 1,
        "storage_fee_per_mwh": 5,
        "variable_om_per_mwh": 2,
        "asset_id": "BAT-001",
    }
    fields.update(overrides)
    return fields


def simulation_result():
    return {
        "power_mw": 10,
        "duration_hours": 4,
        "round_trip_efficiency": 0.8,
        "cycles": 1,
        "charging_cost": 750,
        "discharge_revenue": 3600,
        "storage_lease_cost": 200,
        "variable_operating_cost": 80,
        "estimated_net_margin": 2570,
        "discharged_energy_mwh": 40,
        "charging_window": {
            "start_timestamp": "2025-07-18T01:00:00Z",
            "end_timestamp": "2025-07-18T05:00:00Z",
        },
        "discharging_window": {
            "start_timestamp": "2025-07-18T16:00:00Z",
            "end_timestamp": "2025-07-18T20:00:00Z",
        },
    }


def test_missing_configuration_fails_clearly(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    try:
        supabase.list_assets(limit=1)
    except supabase.SupabaseError as exc:
        assert exc.error_code == "supabase_not_configured"
        assert exc.status_code == 503
        assert "SUPABASE_URL" in str(exc)
    else:
        raise AssertionError("Expected SupabaseError")


def test_migration_defines_authoritative_schema_integrity():
    sql = Path(
        "supabase/migrations/202607130001_supabase_system_of_record.sql"
    ).read_text()

    for table in ("assets", "simulation_results", "dispatch_events"):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "unique (asset_id)" in sql
    assert "unique (external_simulation_id)" in sql
    assert "unique (dispatch_id)" in sql
    assert "foreign key (asset_id) references public.assets(asset_id)" in sql
    assert "foreign key (simulation_id) references public.simulation_results(id)" in sql
    assert "dispatch_events_timestamp_id_idx" in sql


def test_request_uses_supabase_service_role_without_exposing_it(monkeypatch):
    configure_supabase(monkeypatch)
    captured = {}

    def request(method, url, headers, params, json, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return MockResponse(payload=[])

    monkeypatch.setattr(supabase.requests, "request", request)

    assert supabase.list_assets(limit=1) == []
    assert captured["url"] == "https://project.supabase.co/rest/v1/assets"
    assert captured["headers"]["apikey"] == "service-role-secret"
    assert captured["headers"]["Authorization"] == "Bearer service-role-secret"
    assert captured["timeout"] == supabase.SUPABASE_TIMEOUT_SECONDS


def test_request_reports_timeout_without_logging_service_key(monkeypatch):
    configure_supabase(monkeypatch)
    monkeypatch.setattr(
        supabase.requests,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.Timeout("service-role-secret timed out")
        ),
    )

    try:
        supabase.list_assets(limit=1)
    except supabase.SupabaseError as exc:
        assert exc.error_code == "supabase_timeout"
        assert "service-role-secret" not in str(exc)
    else:
        raise AssertionError("Expected SupabaseError")


def test_request_rejects_malformed_supabase_response(monkeypatch):
    configure_supabase(monkeypatch)
    monkeypatch.setattr(
        supabase.requests,
        "request",
        lambda *args, **kwargs: MockResponse(payload={"unexpected": True}),
    )

    try:
        supabase.list_assets(limit=1)
    except supabase.SupabaseError as exc:
        assert exc.error_code == "malformed_supabase_response"
    else:
        raise AssertionError("Expected SupabaseError")


def test_duplicate_asset_is_rejected(monkeypatch):
    monkeypatch.setattr(
        supabase,
        "_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            supabase.SupabaseError("duplicate", status_code=409)
        ),
    )

    try:
        supabase.create_asset({"asset_id": "BAT-001", "asset_name": "Battery"})
    except supabase.DuplicateAssetError as exc:
        assert exc.error_code == "duplicate_asset"
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected DuplicateAssetError")


def test_derived_idempotency_key_is_stable_for_identical_simulation():
    first = supabase.derive_idempotency_key(
        simulation_request(), simulation_result()
    )
    second = supabase.derive_idempotency_key(
        simulation_request(), simulation_result()
    )

    assert first == second
    assert first.startswith("auto:")


def test_persistence_retry_does_not_duplicate_dispatch_and_preserves_foreign_keys(
    monkeypatch,
):
    simulations = {}
    dispatches = {}
    asset = {"id": "asset-uuid", "asset_id": "BAT-001"}

    def request(method, table, params=None, json_body=None, prefer=None):
        if table == "simulation_results" and method == "get":
            key = params["external_simulation_id"].removeprefix("eq.")
            return [simulations[key]] if key in simulations else []
        if table == "simulation_results" and method == "post":
            simulations[json_body["external_simulation_id"]] = dict(json_body)
            return [dict(json_body)]
        if table == "simulation_results" and method == "patch":
            simulations["run-1"]["asset_id"] = json_body["asset_id"]
            return []
        if table == "assets" and method == "get":
            return [asset]
        if table == "dispatch_events" and method == "post":
            dispatches.setdefault(json_body["dispatch_id"], dict(json_body))
            return []
        raise AssertionError((method, table, params, json_body, prefer))

    monkeypatch.setattr(supabase, "_request", request)

    first = supabase.persist_simulation(
        simulation_request(), simulation_result(), "run-1"
    )
    second = supabase.persist_simulation(
        simulation_request(), simulation_result(), "run-1"
    )

    assert first == second
    assert len(simulations) == 1
    assert len(dispatches) == 1
    simulation = simulations["run-1"]
    assert simulation["external_simulation_id"] == "run-1"
    assert simulation["asset_id"] == "BAT-001"
    assert simulation["storage_fee_per_mwh"] == 5
    assert "idempotency_key" not in simulation
    dispatch = next(iter(dispatches.values()))
    assert dispatch["asset_id"] == "BAT-001"
    assert dispatch["simulation_id"] == first["simulation_id"]
    assert dispatch["dispatch_id"] == f"dispatch:{first['simulation_id']}"


def test_missing_asset_saves_simulation_without_fake_dispatch(monkeypatch):
    calls = []

    def request(method, table, params=None, json_body=None, prefer=None):
        calls.append((method, table))
        if table == "simulation_results" and method == "get":
            return []
        if table == "simulation_results" and method == "post":
            return [json_body]
        if table == "assets" and method == "get":
            return []
        raise AssertionError((method, table))

    monkeypatch.setattr(supabase, "_request", request)

    result = supabase.persist_simulation(
        simulation_request(asset_id="MISSING"), simulation_result(), "run-missing"
    )

    assert result["status"] == "partial"
    assert result["error_code"] == "missing_asset"
    assert ("post", "dispatch_events") not in calls


def test_failed_simulation_archival_has_structured_error(monkeypatch):
    def request(method, table, params=None, json_body=None, prefer=None):
        if table == "simulation_results" and method == "get":
            return []
        if table == "simulation_results" and method == "post":
            raise supabase.SupabaseError("database unavailable")
        raise AssertionError((method, table))

    monkeypatch.setattr(supabase, "_request", request)

    try:
        supabase.persist_simulation(
            simulation_request(), simulation_result(), "run-failed"
        )
    except supabase.SupabaseError as exc:
        assert exc.error_code == "failed_simulation_archival"
        assert exc.operation == "archive_simulation"
    else:
        raise AssertionError("Expected SupabaseError")


def test_dispatch_failure_is_visible_after_simulation_archival(monkeypatch):
    def request(method, table, params=None, json_body=None, prefer=None):
        if table == "simulation_results" and method == "get":
            return []
        if table == "simulation_results" and method == "post":
            return [json_body]
        if table == "simulation_results" and method == "patch":
            return []
        if table == "assets" and method == "get":
            return [{"id": "asset-uuid", "asset_id": "BAT-001"}]
        if table == "dispatch_events" and method == "post":
            raise supabase.SupabaseError("database unavailable")
        raise AssertionError((method, table))

    monkeypatch.setattr(supabase, "_request", request)

    try:
        supabase.persist_simulation(
            simulation_request(), simulation_result(), "run-partial"
        )
    except supabase.SupabaseError as exc:
        assert exc.error_code == "failed_dispatch_creation"
        assert exc.simulation_id
    else:
        raise AssertionError("Expected SupabaseError")


def test_list_all_uses_offset_pagination(monkeypatch):
    monkeypatch.setattr(supabase, "PAGE_SIZE", 2)
    calls = []

    def request(method, table, params=None, **kwargs):
        calls.append(dict(params))
        if params["offset"] == 0:
            return [{"id": "one"}, {"id": "two"}]
        return [{"id": "three"}]

    monkeypatch.setattr(supabase, "_request", request)

    records = supabase.list_assets()

    assert [record["id"] for record in records] == ["one", "two", "three"]
    assert [call["offset"] for call in calls] == [0, 2]


def test_dispatch_filters_and_stable_pagination_are_forwarded(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        supabase,
        "get_asset",
        lambda asset_id: {"id": "asset-uuid", "asset_id": asset_id},
    )

    def request(method, table, params=None, **kwargs):
        captured.update(params)
        return []

    monkeypatch.setattr(supabase, "_request", request)

    supabase.list_dispatch_events(
        start_date=date(2025, 7, 1),
        end_date=date(2025, 7, 31),
        asset_id="BAT-001",
        market="RTM",
        location="NP15",
        status="completed",
        limit=25,
        offset=50,
    )

    assert captured["asset_id"] == "eq.BAT-001"
    assert captured["market"] == "eq.RTM"
    assert captured["location"] == "eq.NP15"
    assert captured["status"] == "eq.completed"
    assert captured["order"] == "dispatch_timestamp.asc,id.asc"
    assert captured["limit"] == 25
    assert captured["offset"] == 50
    assert "dispatch_timestamp.gte.2025-07-01" in captured["and"]
    assert "dispatch_timestamp.lt.2025-08-01" in captured["and"]


def test_asset_performance_includes_zero_dispatch_assets(monkeypatch):
    monkeypatch.setattr(
        supabase,
        "list_assets",
        lambda: [
            {"id": "one", "asset_id": "ONE", "asset_name": "One"},
            {"id": "two", "asset_id": "TWO", "asset_name": "Two"},
        ],
    )
    monkeypatch.setattr(
        supabase,
        "list_dispatch_events",
        lambda **kwargs: [{
            "asset_id": "ONE",
            "discharge_revenue": "100",
            "charging_cost": "40",
            "net_profit": "50",
            "discharge_end": "2025-07-18T20:00:00Z",
        }],
    )

    performance = supabase.get_asset_performance()

    assert performance[0]["total_dispatches"] == 1
    assert performance[0]["total_profit"] == 50
    assert performance[1]["total_dispatches"] == 0
    assert performance[1]["average_profit_per_dispatch"] == 0


def test_report_totals_come_from_dispatches_and_ignore_malformed_numbers(monkeypatch):
    monkeypatch.setattr(
        supabase,
        "list_dispatch_events",
        lambda **kwargs: [
            {
                "dispatch_timestamp": "2025-07-18T01:00:00Z",
                "energy_mwh": "40",
                "charging_cost": "750",
                "discharge_revenue": "3600",
                "storage_cost": "280",
                "net_profit": "2570",
            },
            {
                "dispatch_timestamp": "2025-07-18T05:00:00Z",
                "energy_mwh": "malformed",
                "charging_cost": None,
                "discharge_revenue": 100,
                "storage_cost": float("nan"),
                "net_profit": 80,
            },
        ],
    )

    daily = supabase.aggregate_report("daily")

    assert daily == [{
        "period_start": "2025-07-18",
        "period_end": "2025-07-18",
        "total_dispatches": 2,
        "total_energy_mwh": 40.0,
        "charging_cost": 750.0,
        "discharge_revenue": 3700.0,
        "storage_cost": 280.0,
        "net_profit": 2650.0,
    }]


def test_report_period_boundaries():
    value = date(2025, 7, 18)

    assert supabase._period_bounds(value, "daily") == (value, value)
    assert supabase._period_bounds(value, "weekly") == (
        date(2025, 7, 14), date(2025, 7, 20)
    )
    assert supabase._period_bounds(value, "monthly") == (
        date(2025, 7, 1), date(2025, 7, 31)
    )
    assert supabase._period_bounds(value, "quarterly") == (
        date(2025, 7, 1), date(2025, 9, 30)
    )
    assert supabase._period_bounds(value, "yearly") == (
        date(2025, 1, 1), date(2025, 12, 31)
    )
