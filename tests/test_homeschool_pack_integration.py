"""End-to-end integration for the governed 13-state homeschool pack."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from hybridagent import config as cfg
from hybridagent import pack
from hybridagent.broker import GovernanceBroker, GovernancePolicy, RiskClass, Verdict
from hybridagent.daemon import Daemon, _StatusHandler
from hybridagent.llm import LLMClient
from hybridagent.tools import default_registry

from hybridagent_praxis_homeschool.modules.homeschool_compliance import (
    build_compliance_calendar,
)
from hybridagent_praxis_homeschool.modules.homeschool_jurisdictions import (
    get_homeschool_profile,
    profile_for_route,
    registered_homeschool_states,
)
from hybridagent_praxis_homeschool.modules.homeschool_route import RouteSelection

STATES = ("FL", "GA", "SC", "TN", "VA", "WV", "MD", "PA", "OH", "NJ", "NY", "CT", "MA")


def activate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cfg.ENV_HOME, str(tmp_path / ".praxis"))
    pack.activate("homeschool")


def test_pack_manifest_is_governed_and_complete(tmp_path, monkeypatch):
    activate(tmp_path, monkeypatch)
    hs = pack.active()
    assert hs is not None
    assert hs.name == "homeschool" and hs.version == "0.1.2"
    assert hs.compliance_mode == "enforced"
    assert set(hs.risk_policy["autonomousRisks"]) == {"read", "draft"}
    assert set(hs.risk_policy["dualApprovalRisks"]) == {"send", "destructive"}
    assert hs.risk_policy["egressCheck"] and hs.risk_policy["injectionCheck"]
    assert len(hs.skills) == 9
    registry = default_registry()
    assert {"read_file", "write_file", "query_knowledge", "send_email"} <= set(hs.tools)
    assert set(hs.tools) <= set(registry.names())
    policy = GovernancePolicy(allowed_tools=set(registry.names()))
    pack.apply_to_policy(hs, policy)
    broker = GovernanceBroker(policy)
    assert broker.authorize("parent", "read_file", RiskClass.READ, {"path": "x"}).verdict == Verdict.ALLOW
    assert broker.authorize("parent", "write_file", RiskClass.DRAFT, {"path": "x"}).verdict == Verdict.ALLOW
    assert broker.authorize("parent", "send_email", RiskClass.SEND, {}).verdict != Verdict.DENY
    prompt = hs.system_prompt.lower()
    for phrase in ("never fabricate attendance", "parent-visible", "send-held",
                   "never claim state issuance or accreditation"):
        assert phrase in prompt


def test_knowledge_covers_all_states_and_hard_boundaries():
    knowledge = (Path(__file__).parents[1] / "hybridagent_praxis_homeschool" / "packs" /
                 "homeschool" / "knowledge.md").read_text(encoding="utf-8")
    for state in STATES:
        assert f"### {state} " in knowledge
    for phrase in ("Public virtual", "Never fabricate", "not diagnoses or IEPs",
                   "No advertising", "Uncertain"):
        assert phrase.lower() in knowledge.lower()


def test_all_state_default_routes_build_a_source_versioned_calendar():
    assert registered_homeschool_states() == STATES
    for state in STATES:
        profile = get_homeschool_profile(state)
        assert profile is not None
        selection = RouteSelection(
            state, profile.default_route, True, "2026-08-01",
            oversight_entity="Parent-selected association" if state == "SC" else "",
        )
        calendar = build_compliance_calendar(
            selection, school_year_start="2026-08-01",
            commencement="annual_continuation", learner_grades=(3, 5, 8, 11),
        )
        assert calendar.state == state
        assert calendar.route == profile.default_route
        assert calendar.source_verified_on == profile.verified_on
        assert calendar.tasks
        assert all(
            task.authority == profile.source_citation
            or task.authority.startswith("Planning target only")
            for task in calendar.tasks
        )
        assert calendar.tasks[-1].title == "Close annual records and freeze evidence archive"


def test_every_registered_route_builds_without_cross_route_fallback():
    oversight_routes = {
        ("SC", "option2_scaihs"), ("SC", "option3_association"),
        ("TN", "church_related_school"), ("FL", "private_school_umbrella"),
        ("FL", "pep_scholarship"), ("MD", "nonpublic_supervision"),
        ("PA", "private_tutor"),
    }
    checked = 0
    for state in STATES:
        profile = get_homeschool_profile(state)
        assert profile is not None
        for route in profile.routes:
            selection = RouteSelection(
                state, route, True, "2026-08-01",
                oversight_entity=("Verified oversight"
                                  if (state, route) in oversight_routes else ""),
            )
            calendar = build_compliance_calendar(
                selection, school_year_start="2026-08-01",
                commencement="annual_continuation",
                learner_grades=(3, 5, 8, 11),
            )
            assert calendar.state == state and calendar.route == route
            assert calendar.tasks
            checked += 1
    assert checked == 24


def test_route_specific_state_divergence_is_preserved():
    ny = get_homeschool_profile("NY")
    nj = get_homeschool_profile("NJ")
    sc = get_homeschool_profile("SC")
    wv = get_homeschool_profile("WV")
    assert ny and nj and sc and wv
    assert ny.progress_reports_per_year == 4 and ny.instruction_hours_secondary == 990
    assert nj.instruction_days == 0 and not nj.portfolio_required
    assert sc.routes == ("option1_district", "option2_scaihs", "option3_association")
    assert {"hope_individualized", "learning_pod"} <= set(wv.routes)
    assert "microschool" not in wv.routes
    tn = get_homeschool_profile("TN")
    tn_umbrella = profile_for_route("TN", "church_related_school")
    assert tn and tn_umbrella and tn.confidence == "primary_source"
    assert tn.instruction_days == 180 and tn.assessment_grades == (5, 7, 9)
    assert tn_umbrella.instruction_days == 0 and tn_umbrella.assessment_grades == ()
    assert "church-related school" in tn_umbrella.diploma_note


def test_command_deck_status_is_privacy_minimal(tmp_path, monkeypatch):
    activate(tmp_path, monkeypatch)
    daemon = Daemon(llm=LLMClient(mode="mock"), status_port=0)
    status = daemon.homeschool_status()
    assert status["active"] and status["profile"]["state"] == "FL"
    assert status["privacy"] == {
        "parent_owned": True,
        "sibling_isolation": True,
        "external_disclosures_held": True,
        "model_training": False,
        "profiling": False,
    }
    serialized = json.dumps(status).lower()
    assert "learner_name" not in serialized and "health_record" not in serialized


def test_command_deck_requires_literal_parent_and_commencement_confirmation(tmp_path, monkeypatch):
    activate(tmp_path, monkeypatch)
    daemon = Daemon(llm=LLMClient(mode="mock"), status_port=0)
    blocked = daemon.homeschool_set_context({
        "state": "NY", "route": "home_instruction",
        "school_year_start": "2026-08-01", "parent_confirmed": "true",
        "commencement": "annual_continuation",
    })
    assert blocked["blocked"]
    commencement_missing = daemon.homeschool_set_context({
        "state": "NY", "route": "home_instruction",
        "school_year_start": "2026-08-01", "parent_confirmed": True,
    })
    assert commencement_missing["blocked"]
    not_started = daemon.homeschool_set_context({
        "state": "NY", "route": "home_instruction",
        "school_year_start": "2026-08-01", "parent_confirmed": True,
        "commencement": "not_yet_started",
    })
    assert not_started["calendar"]["confirmed"] is False
    ready = daemon.homeschool_set_context({
        "state": "NY", "route": "home_instruction",
        "school_year_start": "2026-08-01", "parent_confirmed": True,
        "commencement": "annual_continuation",
        "reporting_dates": ["2026-10-31", "2027-01-31", "2027-04-30", "2027-07-31"],
    })
    assert ready["calendar"]["confirmed"]
    titles = {task["title"] for task in ready["calendar"]["tasks"]}
    assert "Submit parent-approved IHIP" in titles
    assert sum("quarterly report" in title for title in titles) == 4


def test_command_deck_ui_collects_commencement_and_event_driven_dates():
    script = (
        Path(__file__).parents[1]
        / "hybridagent_praxis_homeschool/web/homeschool.js"
    ).read_text(encoding="utf-8")
    assert "'hs-commencement'" in script
    assert "'hs-materials-received'" in script
    assert "'hs-reporting-dates'" in script
    assert "'hs-assessment-due'" in script
    assert ".innerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert "textContent" in script and "replaceChildren" in script
    assert "commencement:" in script
    assert "materials_received_on:" in script
    assert "reporting_dates:" in script
    assert "assessment_due_date:" in script


def test_command_deck_blocks_unknown_route_and_public_virtual(tmp_path, monkeypatch):
    activate(tmp_path, monkeypatch)
    daemon = Daemon(llm=LLMClient(mode="mock"), status_port=0)
    unknown = daemon.homeschool_set_context({
        "state": "FL", "route": "invented", "school_year_start": "2026-08-01",
        "parent_confirmed": True, "commencement": "annual_continuation",
    })
    assert unknown["blocked"]
    virtual = daemon.homeschool_set_context({
        "state": "OH", "route": "public_virtual", "school_year_start": "2026-08-01",
        "parent_confirmed": True, "district_enrolled": True,
        "school_of_record": "public_school", "commencement": "annual_continuation",
    })
    assert virtual["blocked"]
    assert any(x["code"] == "public_school_not_homeschool" for x in virtual["findings"])


def test_blocked_command_deck_change_preserves_valid_context(tmp_path, monkeypatch):
    activate(tmp_path, monkeypatch)
    daemon = Daemon(llm=LLMClient(mode="mock"), status_port=0)
    ready = daemon.homeschool_set_context({
        "state": "NY", "route": "home_instruction",
        "school_year_start": "2026-08-01", "parent_confirmed": True,
        "commencement": "annual_continuation",
        "reporting_dates": ["2026-10-31", "2027-01-31", "2027-04-30", "2027-07-31"],
    })
    assert ready["profile"]["state"] == "NY"
    blocked = daemon.homeschool_set_context({
        "state": "TN", "route": "church_related_school",
        "school_year_start": "2026-08-01", "parent_confirmed": True,
        "commencement": "annual_continuation",
    })
    assert blocked["blocked"]
    current = daemon.homeschool_status()
    assert current["profile"]["state"] == "NY" and current["route"] == "home_instruction"
    invalid_dates = daemon.homeschool_set_context({
        "state": "NY", "route": "home_instruction",
        "school_year_start": "2026-08-01", "parent_confirmed": True,
        "commencement": "annual_continuation",
        "reporting_dates": ["2026-10-31"],
    })
    assert invalid_dates["blocked"]
    current = daemon.homeschool_status()
    assert current["profile"]["state"] == "NY" and current["route"] == "home_instruction"
    impossible_year = daemon.homeschool_set_context({
        "state": "FL", "route": "independent_home_education",
        "school_year_start": "9999-12-31", "parent_confirmed": True,
        "commencement": "annual_continuation",
    })
    assert impossible_year["blocked"]
    current = daemon.homeschool_status()
    assert current["profile"]["state"] == "NY" and current["route"] == "home_instruction"


def test_command_deck_context_transaction_rolls_back_unexpected_failures(tmp_path, monkeypatch):
    activate(tmp_path, monkeypatch)
    daemon = Daemon(llm=LLMClient(mode="mock"), status_port=0)
    before = daemon._homeschool_context

    def fail_status():
        raise RuntimeError("simulated calendar failure")

    monkeypatch.setattr(daemon, "homeschool_status", fail_status)
    with pytest.raises(RuntimeError, match="simulated"):
        daemon.homeschool_set_context({
            "state": "FL", "route": "independent_home_education",
            "school_year_start": "2026-08-01", "parent_confirmed": True,
            "commencement": "annual_continuation",
        })
    assert daemon._homeschool_context == before
    with pytest.raises(RuntimeError, match="simulated"):
        daemon.homeschool_set_context({"state": "FL", "route": ""})
    assert daemon._homeschool_context == before


def test_command_deck_canonicalizes_umbrella_school_of_record(tmp_path, monkeypatch):
    activate(tmp_path, monkeypatch)
    daemon = Daemon(llm=LLMClient(mode="mock"), status_port=0)
    ready = daemon.homeschool_set_context({
        "state": "tn", "route": " CHURCH_RELATED_SCHOOL ",
        "school_year_start": "2026-08-01", "parent_confirmed": True,
        "oversight_entity": " Umbrella Academy ",
        "commencement": "annual_continuation",
    })
    assert ready["route"] == "church_related_school"
    assert ready["school_of_record"] == "church_related_school"


def test_command_deck_retains_grade_triggered_calendar_without_child_pii(tmp_path, monkeypatch):
    activate(tmp_path, monkeypatch)
    daemon = Daemon(llm=LLMClient(mode="mock"), status_port=0)
    ready = daemon.homeschool_set_context({
        "state": "PA", "route": "home_education",
        "school_year_start": "2026-08-01", "parent_confirmed": True,
        "learner_grades": [5], "commencement": "annual_continuation",
        "assessment_due_date": "2027-06-15",
    })
    titles = {task["title"] for task in ready["calendar"]["tasks"]}
    assert "Complete grade-triggered standardized testing" in titles
    assert "learner_grades" not in json.dumps(ready)
    blocked = daemon.homeschool_set_context({
        "state": "PA", "route": "home_education",
        "school_year_start": "2026-08-01", "parent_confirmed": True,
        "learner_grades": [True], "commencement": "annual_continuation",
    })
    assert blocked["blocked"]


def test_homeschool_dashboard_assets_api_and_mount_served(tmp_path, monkeypatch):
    activate(tmp_path, monkeypatch)
    daemon = Daemon(llm=LLMClient(mode="mock"), status_port=0)
    daemon._start_status_server()
    time.sleep(0.15)
    base = f"http://127.0.0.1:{daemon.status_port}"
    try:
        for asset in ("homeschool.js", "homeschool.css"):
            with urllib.request.urlopen(f"{base}/web/{asset}", timeout=5) as response:
                assert response.status == 200 and response.read()
        with urllib.request.urlopen(f"{base}/", timeout=5) as response:
            html = response.read().decode()
        assert "homeschool.js" in html and "homeschool.css" in html
        assert 'id="homeschool-section"' in html and 'id="homeschool-mount"' in html
        with urllib.request.urlopen(f"{base}/api/homeschool", timeout=5) as response:
            body = json.loads(response.read())
        assert body["active"] and len(body["states"]) == 13
        request = urllib.request.Request(
            f"{base}/api/homeschool/context",
            data=json.dumps({
                "state": "NJ", "route": "equivalent_instruction_elsewhere",
                "school_year_start": "2026-08-01", "parent_confirmed": True,
                "commencement": "annual_continuation",
            }).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read())
        assert body["calendar"]["confirmed"] and body["profile"]["state"] == "NJ"

        for headers, expected in (
            ({"Content-Type": "text/plain"}, 415),
            ({"Content-Type": "application/json", "Origin": "https://evil.example"}, 403),
        ):
            blocked = urllib.request.Request(
                f"{base}/api/homeschool/context",
                data=json.dumps({"state": "NY"}).encode(),
                headers=headers, method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(blocked, timeout=5)
            assert exc.value.code == expected
        oversized = urllib.request.Request(
            f"{base}/api/homeschool/context", data=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "65537"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(oversized, timeout=5)
        assert exc.value.code == 413

        with monkeypatch.context() as remote:
            remote.setenv("PRAXIS_AUTH_TOKEN", "homeschool-test-token")
            remote.setattr(_StatusHandler, "_is_loopback", lambda self: False)
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(f"{base}/api/homeschool", timeout=5)
            assert exc.value.code == 401
            authorized = urllib.request.Request(
                f"{base}/api/homeschool",
                headers={"X-Praxis-Token": "homeschool-test-token"},
            )
            with urllib.request.urlopen(authorized, timeout=5) as response:
                assert json.loads(response.read())["active"]
        with monkeypatch.context() as remote:
            remote.delenv("PRAXIS_AUTH_TOKEN", raising=False)
            remote.setattr(_StatusHandler, "_is_loopback", lambda self: False)
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(f"{base}/api/homeschool", timeout=5)
            assert exc.value.code == 401
        rebinding = urllib.request.Request(
            f"{base}/api/homeschool/context",
            data=json.dumps({"state": "NY"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Host": "evil.example",
                "Origin": "http://evil.example",
            }, method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(rebinding, timeout=5)
        assert exc.value.code == 403
        numeric_prefix = urllib.request.Request(
            f"{base}/api/homeschool",
            headers={"Host": "127.attacker.example"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(numeric_prefix, timeout=5)
        assert exc.value.code == 403
        for malformed_host in (
            "evil.example@localhost", "localhost:bad", "localhost?ignored",
            "localhost#ignored", "localhost/path", "localhost:0", "localhost:65536",
        ):
            malformed = urllib.request.Request(
                f"{base}/api/homeschool", headers={"Host": malformed_host},
            )
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(malformed, timeout=5)
            assert exc.value.code == 403
    finally:
        daemon._stop_status_server()
        pack.deactivate()
