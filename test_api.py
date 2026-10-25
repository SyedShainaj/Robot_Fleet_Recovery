from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
import main
from main import app, verified_user
import profile_store

client = TestClient(app)

def test_health_and_simulation_label():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["environment"] == "simulation"

def test_evaluation_endpoint_handles_unmeasured_metrics():
    client.post('/api/theme4/reset')
    response = client.get('/api/theme4/evaluation')
    assert response.status_code == 200
    payload = response.json()
    assert payload['evaluation']['migration_success_rate'] is None
    assert payload['evaluation']['mission_preservation'] == 100


def test_deployed_vercel_frontend_origin_is_allowed_by_cors():
    origin = "https://sentinel-fleet-recovery-ai-git-main-kvrtkvrt9-7956s-projects.vercel.app"
    response = client.get("/api/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin

def test_vite_fallback_ports_are_allowed_by_cors():
    for origin in ["http://localhost:5174", "http://localhost:5175"]:
        response = client.options("/api/simulation/state", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        })
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin

def test_prediction_and_recovery_contract():
    client.post('/api/theme4/reset')
    prediction = client.get("/api/predictions/R-004")
    assert prediction.status_code == 200
    assert prediction.json()["model"] == 'simulation-based telemetry rule'
    assert prediction.json()["confidence"] is None
    assert 0 <= prediction.json()["risk"] <= 99
    recovery = client.post("/api/recovery", json={"incident_id": "INC-TEST", "approve": True})
    assert recovery.status_code == 200
    assert recovery.json()["performance"]["recovered"] is None
    assert recovery.json()["performance"]["mission_preservation"] == 100

def test_demo_auth_role():
    response = client.post("/auth/demo", json={"role": "Operator"})
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "Operator"


def test_demo_auth_uses_public_identity_not_fake_person():
    response = client.post("/auth/demo", json={"role": "Operator"})
    assert response.status_code == 200
    payload = response.json()["user"]
    assert payload["name"] == "Public visitor"
    assert payload["email"] == "preview@sentinel.local"
    assert payload["organization"] == "Sentinel Robotics"


def test_robot_alias_lookup_is_canonical_and_case_insensitive():
    assert client.get('/api/recovery/candidates/SV-088').status_code == 404
    assert client.get('/api/recovery/candidates/R-088').status_code == 404

def test_real_pdf_and_exports():
    pdf = client.post("/api/reports/generate", json={"performance": {"before": 98.4, "lowest": 54.2, "recovered": 89.7}, "robots": [{"id": "R-004", "health": 38}], "migrations": [{"task": "T14"}]})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert b'T-014' not in pdf.content
    assert b'89.7' not in pdf.content
    assert b'42 seconds' not in pdf.content
    assert "Sentinel_Fleet_Recovery_" in pdf.headers["content-disposition"]
    page_count = pdf.content.count(b"/Type /Page")
    assert 6 <= page_count <= 10
    assert client.get("/api/export/json").headers["content-type"].startswith("application/json")
    assert client.get("/api/export/csv").headers["content-type"].startswith("text/csv")


def test_profile_update_persists_and_does_not_trust_identity_fields(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(profile_store, "DB_PATH", tmp_path / "profile-test.db")
    app.dependency_overrides[verified_user] = lambda: {"uid": "user-a", "name": "Google Name", "email": "a@example.com", "picture": "https://photo/a"}
    try:
        response = client.put("/api/profile", json={"name": "Saved Name", "date_of_birth": "1992-04-03", "phone": "+1 (555) 123-4567", "uid": "user-b", "email": "attacker@example.com"})
        assert response.status_code == 200
        assert response.json()["profile"] == {
            "uid": "user-a", "name": "Saved Name", "email": "a@example.com", "photoURL": "https://photo/a",
            "dateOfBirth": "1992-04-03", "phoneNumber": "+1 (555) 123-4567", "provider": "google", "role": "USER",
            "accountStatus": "ACTIVE", "createdAt": response.json()["profile"]["createdAt"],
            "lastLoginAt": response.json()["profile"]["lastLoginAt"], "lastSeenAt": response.json()["profile"]["lastSeenAt"],
        }
        loaded = client.get("/api/profile")
        assert loaded.status_code == 200
        assert loaded.json()["profile"]["name"] == "Saved Name"
        assert loaded.json()["profile"]["dateOfBirth"] == "1992-04-03"
        assert loaded.json()["profile"]["phoneNumber"] == "+1 (555) 123-4567"
    finally:
        app.dependency_overrides.clear()


def test_profile_requires_authentication():
    assert client.get("/api/profile").status_code == 401


def test_profile_rejects_invalid_payload():
    app.dependency_overrides[verified_user] = lambda: {"uid": "user-a", "email": "a@example.com"}
    try:
        assert client.put("/api/profile", json={"name": "", "date_of_birth": "not-a-date", "phone": "bad"}).status_code == 422
    finally:
        app.dependency_overrides.clear()

def test_theme4_injection_updates_authoritative_state_and_progressive_timeline():
    assert client.post('/api/theme4/reset').status_code == 200
    response = client.post('/api/theme4/failures/inject', json={
        'robot_id': 'R-004', 'failure_type': 'communication', 'severity': 'critical', 'timing': 'progressive'
    })
    assert response.status_code == 200
    payload = response.json()
    robot = next(item for item in payload['state']['robots'] if item['id'] == 'R-004')
    assert robot['status'] == 'failed'
    assert any(event['type'] == 'PROPAGATION' for event in payload['state']['events'])
    assert payload['evaluation']['cascade_depth'] >= 2


def test_battery_failure_routes_robot_to_charging_station():
    client.post('/api/theme4/reset')
    response = client.post('/api/theme4/failures/inject', json={
        'robot_id': 'R-006', 'failure_type': 'battery', 'severity': 'failed', 'timing': 'immediate'
    })
    assert response.status_code == 200
    robot = next(item for item in response.json()['state']['robots'] if item['id'] == 'R-006')
    assert robot['status'] == 'charging'
    assert robot['charging_state'] == 'navigating_to_charger'
    assert robot['charger_name'] in {'CHARGING STATION A', 'CHARGING STATION B'}
    assert robot['route'][-1] == robot['charger_name']
    assert len(robot['route_options']) >= 2
    assert {option['station'] for option in robot['route_options']} == {'CHARGING STATION A', 'CHARGING STATION B'}
    assert robot['route_options'][0]['waypoints'][0] == robot['position']


def test_prediction_precedes_actual_failure_in_progressive_timeline():
    client.post('/api/theme4/reset')
    response = client.post('/api/theme4/failures/inject', json={
        'robot_id': 'R-003', 'failure_type': 'motor', 'severity': 'critical', 'timing': 'progressive'
    })
    payload = response.json()
    progressive_types = [event['type'] for event in reversed(payload['state']['events']) if event.get('robot') == 'R-003' and event['type'] in {'WARNING', 'HIGH_RISK', 'PREDICTION', 'PROPAGATION', 'FAILURE'}]
    assert progressive_types == ['WARNING', 'HIGH_RISK', 'PREDICTION', 'PROPAGATION', 'FAILURE']
    assert progressive_types.index('PREDICTION') < progressive_types.index('FAILURE')
    assert payload['state']['predictions'][-1]['robot_id'] == 'R-003'


def test_theme4_scenarios_are_seed_reproducible_and_benchmark_is_derived():
    first = client.post('/api/theme4/scenarios/generate', json={'failure_count': 6, 'seed': 48291}).json()
    second = client.post('/api/theme4/scenarios/generate', json={'failure_count': 6, 'seed': 48291}).json()
    assert first == second
    benchmark = client.post('/api/theme4/benchmark', json={'failure_count': 3, 'seed': 7})
    assert benchmark.status_code == 200
    result = benchmark.json()
    assert result['scenario']['seed'] == 7
    assert result['baseline']['recovery_enabled'] is False
    assert result['sentinel_recovery']['recovery_enabled'] is True
    assert 0 <= result['sentinel_recovery']['mission_preservation'] <= 100
    assert client.post('/api/theme4/reset').status_code == 200

def test_simulation_uses_10_robots_and_control_changes_state():
    client.post('/api/theme4/reset')
    state = client.get('/api/simulation/state').json()
    expected_ids = [f'R-{index:03d}' for index in range(1, 26)]
    assert [robot['id'] for robot in state['robots']] == expected_ids
    assert [robot['id'] for robot in client.get('/api/robots').json()['items']] == expected_ids
    paused = client.post('/api/simulation/control', json={'running': False, 'speed': 2})
    assert paused.status_code == 200
    assert paused.json()['running'] is False
    resumed = client.post('/api/simulation/control', json={'running': True, 'speed': 4})
    assert resumed.json()['running'] is True
    assert resumed.json()['speed'] == 4.0
    assert resumed.json()['simulation_seconds'] == 0

def test_pause_resume_and_reset_preserve_backend_state(monkeypatch):
    clock = {'now': 100.0}
    monkeypatch.setattr(main, 'time', SimpleNamespace(monotonic=lambda: clock['now']))
    client.post('/api/theme4/reset')
    client.post('/api/simulation/control', json={'running': True, 'speed': 1})
    clock['now'] += 5
    moving = client.get('/api/simulation/state').json()
    progress = moving['tasks']['T-001']['progress']
    position = next(robot['position'] for robot in moving['robots'] if robot['id'] == 'R-001')
    assert progress > 0

    client.post('/api/simulation/control', json={'running': False})
    clock['now'] += 30
    paused = client.get('/api/simulation/state').json()
    paused_robot = next(robot for robot in paused['robots'] if robot['id'] == 'R-001')
    assert paused['tasks']['T-001']['progress'] == progress
    assert paused_robot['position'] == position

    client.post('/api/simulation/control', json={'running': True, 'speed': 2})
    clock['now'] += 5
    resumed = client.get('/api/simulation/state').json()
    assert resumed['tasks']['T-001']['progress'] > progress
    reset = client.post('/api/theme4/reset').json()['state']
    reset_robot = next(robot for robot in reset['robots'] if robot['id'] == 'R-001')
    assert reset['control']['running'] is False
    assert reset['control']['simulation_seconds'] == 0
    assert reset_robot['position'] == {'x': 12, 'y': 18}
    assert reset_robot['battery'] == 88
    assert reset['failures'] == []
    assert reset['notifications'] == []
    assert all(mission['progress'] == 0 for mission in reset['missions'])

def test_low_battery_charging_resumes_without_teleport_or_progress_loss(monkeypatch):
    clock = {'now': 200.0}
    monkeypatch.setattr(main, 'time', SimpleNamespace(monotonic=lambda: clock['now']))
    client.post('/api/theme4/reset')
    robot = next(robot for robot in main.simulation_state['robots'] if robot['id'] == 'R-001')
    robot['battery'] = 20.0
    initial_position = robot['position'].copy()
    client.post('/api/simulation/control', json={'running': True, 'speed': 1})

    clock['now'] += 1
    low_battery = client.get('/api/simulation/state').json()
    robot_state = next(robot for robot in low_battery['robots'] if robot['id'] == 'R-001')
    assert robot_state['status'] == 'charging'
    assert robot_state['charging_state'] == 'navigating_to_charger'
    assert robot_state['position'] == initial_position

    clock['now'] += 22
    at_charger = client.get('/api/simulation/state').json()
    robot_state = next(robot for robot in at_charger['robots'] if robot['id'] == 'R-001')
    assert robot_state['charging_state'] == 'charging'
    charger_position = robot_state['position'].copy()
    assert charger_position == at_charger['locations'][robot_state['charger_name']]

    clock['now'] += 16
    charged = client.get('/api/simulation/state').json()
    robot_state = next(robot for robot in charged['robots'] if robot['id'] == 'R-001')
    assert robot_state['battery'] >= 80
    assert robot_state['operating_state'] == 'RESUMING'
    assert robot_state['position'] == charger_position
    assert charged['tasks']['T-001']['progress'] == 0

    clock['now'] += 10
    returning = client.get('/api/simulation/state').json()
    robot_state = next(robot for robot in returning['robots'] if robot['id'] == 'R-001')
    assert robot_state['position'] != charger_position
    assert returning['tasks']['T-001']['progress'] == 0
    clock['now'] += 30
    resumed = client.get('/api/simulation/state').json()
    assert resumed['tasks']['T-001']['progress'] > 0

def test_websocket_streams_authoritative_fleet_state():
    client.post('/api/theme4/reset')
    with client.websocket_connect('/ws') as websocket:
        message = websocket.receive_json()
    assert message['type'] == 'STATE'
    assert [robot['id'] for robot in message['state']['robots']] == [f'R-{index:03d}' for index in range(1, 26)]
    assert message['evaluation']['robots'] == 25


def test_assign_task_sets_active_route_and_moves_when_simulation_runs():
    client.post('/api/theme4/reset')
    robot = next(item for item in client.get('/api/simulation/state').json()['robots'] if item['availability'] == 'AVAILABLE')
    assigned = client.post(f"/api/fleet/robots/{robot['id']}/assign-task", json={
        'task_id': 'T-250', 'mission_id': 'M-250', 'destination': 'WAREHOUSE B'
    })
    assert assigned.status_code == 200
    assigned_payload = assigned.json()['robot']
    assert assigned_payload['current_task'] == 'T-250'
    assert assigned_payload['task_id'] == 'T-250'
    assert assigned_payload['mission_id'] == 'M-250'
    duplicate = client.post(f"/api/fleet/robots/R-008/assign-task", json={
        'task_id': 'T-250', 'mission_id': 'M-250', 'destination': 'WAREHOUSE B'
    })
    assert duplicate.status_code == 409
    started = client.post('/api/simulation/control', json={'running': True, 'speed': 4.0})
    assert started.status_code == 200
    assert started.json()['running'] is True
    moved = next(item for item in client.get('/api/simulation/state').json()['robots'] if item['id'] == robot['id'])
    assert moved['current_task'] == 'T-250'
    assert moved['route_progress'] >= 0
    assert moved['speed'] >= 0


def test_recovery_candidates_target_migration_and_notification_clear():
    client.post('/api/theme4/reset')
    candidates = client.get('/api/recovery/candidates/R-004')
    assert candidates.status_code == 200
    target = candidates.json()['candidates'][0]['robot_id']
    migration = client.post('/api/fleet/robots/R-004/migrate-tasks', json={'target_robot': target})
    assert migration.status_code == 200
    assert migration.json()['migration']['destination_robot'] == target
    cleared = client.post('/api/simulation/notifications/clear')
    assert cleared.status_code == 200
    assert client.get('/api/simulation/state').json()['alerts_cleared_at']
    client.post('/api/theme4/reset')


def test_failure_propagation_and_dynamic_migration_have_one_owner():
    client.post('/api/theme4/reset')
    failure = client.post('/api/theme4/failures/inject', json={
        'robot_id': 'R-003', 'failure_type': 'motor', 'severity': 'critical', 'timing': 'progressive'
    })
    assert failure.status_code == 200
    state = failure.json()['state']
    assert state['tasks']['T-003']['status'] == 'AT RISK'
    assert state['tasks']['T-003']['recovery_recommendation']['robot_id']
    propagation = client.get('/api/propagation/INC-TEST').json()
    assert [node['id'] for node in propagation['nodes']] == ['R-003', 'T-003', 'M-003', 'FLEET CAPACITY']

    candidates = client.get('/api/recovery/candidates/R-003').json()['candidates']
    expected_destination = next(candidate['robot_id'] for candidate in candidates if candidate['eligible'])
    migration = client.post('/api/fleet/robots/R-003/migrate-tasks', json={}).json()
    assert migration['migration']['destination_robot'] == expected_destination
    assert migration['migration']['status'] == 'in_progress'
    owners = [robot['id'] for robot in migration['state']['robots'] if 'T-003' in robot['assigned_tasks']]
    assert owners == [expected_destination]
    assert migration['state']['tasks']['T-003']['assigned_robot'] == expected_destination
    propagation_status = {node['type']: node['status'] for node in migration['state']['propagation']}
    assert propagation_status['task'] == 'RECOVERING'
    assert propagation_status['mission'] == 'RECOVERING'
    client.post('/api/theme4/reset')


def test_recovery_route_preserves_task_progress_and_completes_mission(monkeypatch):
    clock = {'now': 100.0}
    monkeypatch.setattr(main, 'time', SimpleNamespace(monotonic=lambda: clock['now']))
    client.post('/api/theme4/reset')
    client.post('/api/simulation/control', json={'running': True, 'speed': 1})

    clock['now'] += 4
    before_failure = client.get('/api/simulation/state').json()
    preserved_progress = before_failure['tasks']['T-003']['progress']
    assert 0 < preserved_progress < 100

    failure = client.post('/api/theme4/failures/inject', json={
        'robot_id': 'R-003', 'failure_type': 'motor', 'severity': 'critical', 'timing': 'progressive'
    })
    assert failure.status_code == 200
    failed_robot = next(robot for robot in failure.json()['state']['robots'] if robot['id'] == 'R-003')
    failure_position = failed_robot['position'].copy()
    assert failed_robot['status'] == 'failed'
    assert failed_robot['speed'] == 0
    assert failure.json()['state']['tasks']['T-003']['status'] == 'AT RISK'
    assert failure.json()['state']['tasks']['T-003']['progress'] == preserved_progress
    migrated = client.post('/api/fleet/robots/R-003/migrate-tasks', json={'target_robot': 'R-007'}).json()
    assert migrated['migration']['destination_robot'] == 'R-007'
    assert migrated['migration']['status'] == 'in_progress'
    assert migrated['state']['missions'][0]['tasks'] == ['T-003']
    assert migrated['state']['tasks']['T-003']['recovery_start_progress'] == preserved_progress
    assert migrated['state']['tasks']['T-003']['recovery_started_at']
    assert migrated['state']['tasks']['T-003']['additional_travel_units'] >= 0

    clock['now'] += 2
    travelling = client.get('/api/simulation/state').json()
    replacement = next(robot for robot in travelling['robots'] if robot['id'] == 'R-007')
    assert replacement['position'] != travelling['tasks']['T-003']['interruption_point']
    assert travelling['tasks']['T-003']['progress'] == preserved_progress
    assert next(robot for robot in travelling['robots'] if robot['id'] == 'R-003')['position'] == failure_position

    clock['now'] += 5
    in_recovery = client.get('/api/simulation/state').json()
    assert preserved_progress < in_recovery['tasks']['T-003']['progress'] < 100
    assert in_recovery['tasks']['T-003']['status'] == 'RECOVERING'

    clock['now'] += 200
    recovered = client.get('/api/simulation/state').json()
    assert recovered['tasks']['T-003']['progress'] == 100
    assert recovered['tasks']['T-003']['remaining_progress'] == 0
    assert recovered['tasks']['T-003']['status'] == 'COMPLETED'
    assert recovered['tasks']['T-003']['recovery_completed_at']
    assert recovered['tasks']['T-003']['recovery_time_seconds'] >= 0
    assert recovered['missions'][0]['progress'] == 100
    assert recovered['missions'][0]['status'] == 'COMPLETED'
    propagation_status = {node['type']: node['status'] for node in recovered['propagation']}
    assert propagation_status['task'] == 'COMPLETED'
    assert propagation_status['mission'] == 'COMPLETED'
    assert recovered['migrations'][0]['status'] == 'completed'
    assert any(event['type'] == 'RECOVERY_COMPLETED' and event['robot'] == 'R-007' for event in recovered['events'])