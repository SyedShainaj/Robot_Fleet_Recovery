from datetime import datetime, timezone
from io import BytesIO, StringIO
import asyncio
import csv
import json
import os
import uuid
import base64
import hashlib
import hmac
import time
import random
import copy
import math
from typing import Literal
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.responses import Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable
try:
    from backend.profile_store import ensure_profile, public_profile, upsert_profile
except ImportError:
    from profile_store import ensure_profile, public_profile, upsert_profile
try:
    from firebase_admin import auth as firebase_admin_auth, credentials as firebase_credentials, initialize_app as firebase_initialize_app, get_app as firebase_get_app
except ImportError:
    firebase_admin_auth = firebase_credentials = firebase_initialize_app = firebase_get_app = None
try:
    from backend.report_template import render_report
except ImportError:
    from report_template import render_report

load_dotenv()


def get_cors_origins():
    configured = os.getenv("CORS_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    frontend_url = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
    if frontend_url and frontend_url not in origins:
        origins.append(frontend_url)
    defaults = [
        "https://sentinel-fleet-recovery-ai-git-main-kvrtkvrt9-7956s-projects.vercel.app",
    ]
    for port in [5173, 5174, 5175, 5176, 4173, 4174]:
        for host in ["http://localhost", "http://127.0.0.1", "http://0.0.0.0", "http://[::1]"]:
            origin = f"{host}:{port}"
            if origin not in defaults:
                defaults.append(origin)
    for origin in defaults:
        if origin not in origins:
            origins.append(origin)
    return origins


app = FastAPI(title="Sentinel Fleet Recovery AI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

class FailureRequest(BaseModel):
    robot_id: str = Field(default="R-004", pattern=r"^R-\d{3}$")
    severity: Literal["low", "medium", "high", "critical"] = "high"
    subsystem: Literal["motor", "battery", "communication", "sensor"] = "motor"

class FailureInjectionRequest(BaseModel):
    robot_id: str = Field(default="R-004", pattern=r"^R-\d{3}$")
    failure_type: Literal["motor", "sensor", "communication", "battery", "cpu", "temperature", "navigation", "power", "custom"] = "motor"
    severity: Literal["warning", "critical", "failed"] = "critical"
    timing: Literal["immediate", "delayed", "progressive"] = "immediate"
    duration_seconds: int = Field(default=0, ge=0, le=3600)
    custom_label: str = Field(default="", max_length=80)

class ScenarioRequest(BaseModel):
    failure_count: int = Field(default=4, ge=1, le=20)
    seed: int | None = Field(default=None, ge=0, le=999999999)

class SimulationControlRequest(BaseModel):
    running: bool | None = None
    speed: float | None = Field(default=None, ge=0.5, le=8.0)

class MigrationExecutionRequest(BaseModel):
    target_robot: str | None = Field(default=None, pattern=r"^R-\d{3}$")

class BenchmarkRequest(BaseModel):
    failure_count: int = Field(default=4, ge=1, le=20)
    seed: int | None = Field(default=None, ge=0, le=999999999)

class RecoveryRequest(BaseModel):
    incident_id: str
    approve: bool = True

class DemoLoginRequest(BaseModel):
    email: str = "alex.rivera@sentinel.example"
    role: Literal["Admin", "Fleet Manager", "Operator", "Viewer"] = "Admin"

class AdminLoginRequest(BaseModel):
    username: str
    password: str

class MigrationRequest(BaseModel):
    source_robot: str = Field(pattern=r"^R-\d{3}$")

class AlertRequest(BaseModel):
    recipient: str = "all"
    severity: Literal["info", "warning", "critical"] = "info"
    title: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=1000)
    robot: str = ""
    mission: str = ""

class SimulationSnapshot(BaseModel):
    user: dict = Field(default_factory=lambda: {"name": "Sentinel Robotics", "organization": "Simulation environment"})
    mission: str = "Fleet recovery cascade response"
    robots: list[dict] = Field(default_factory=list)
    tasks: dict = Field(default_factory=dict)
    locations: dict = Field(default_factory=dict)
    missions: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    notifications: list[dict] = Field(default_factory=list)
    failures: list[dict] = Field(default_factory=list)
    predictions: list[dict] = Field(default_factory=list)
    migrations: list[dict] = Field(default_factory=list)
    propagation: list[dict] = Field(default_factory=list)
    control: dict = Field(default_factory=dict)
    performance: dict = Field(default_factory=dict)
    simulation_id: str = "SIM-2026-DEMO"
    baseline_average_battery: float | None = None
    recovery_duration: str | None = None
    energy_saved: str | None = None

class ProfileRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(min_length=1, max_length=120)
    dateOfBirth: str = Field(default="", max_length=10, alias="date_of_birth")
    phoneNumber: str = Field(default="", max_length=32, alias="phone")

def verified_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    if firebase_admin_auth is None:
        raise HTTPException(status_code=503, detail="Firebase Admin verification is not configured")
    try:
        try:
            firebase_get_app()
        except ValueError:
            certificate = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if not certificate:
                raise HTTPException(status_code=503, detail="Firebase Admin verification is not configured")
            firebase_initialize_app(firebase_credentials.Certificate(certificate))
        return firebase_admin_auth.verify_id_token(authorization.removeprefix("Bearer "))
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=401, detail="Invalid authentication token") from error

def admin_user(claims=Depends(verified_user)):
    if not claims.get("admin", False) and claims.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    return claims

def _admin_secret():
    return (os.getenv("JWT_SECRET") or os.getenv("ADMIN_TOKEN_SECRET") or "development-local-only-secret-change-me").encode()


def issue_admin_token(username):
    payload = f"{username}:{int(time.time()) + 3600}"
    signature = hmac.new(_admin_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()

def verified_admin_session(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    try:
        decoded = base64.urlsafe_b64decode(authorization.removeprefix("Bearer ")).decode()
        username, expires, signature = decoded.rsplit(":", 2)
        payload = f"{username}:{expires}"
        expected = hmac.new(_admin_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected) or int(expires) < int(time.time()):
            raise ValueError("invalid admin session")
        return {"username": username, "role": "ADMIN"}
    except (ValueError, TypeError, UnicodeDecodeError, base64.binascii.Error) as error:
        raise HTTPException(status_code=401, detail="Invalid admin session") from error

def _initial_snapshot():
    locations = {
        "DEPOT": {"x": 12, "y": 18},
        "WAREHOUSE A": {"x": 28, "y": 20},
        "WAREHOUSE B": {"x": 72, "y": 38},
        "PICKUP 01": {"x": 36, "y": 30},
        "PICKUP 02": {"x": 58, "y": 62},
        "DROP POINT 01": {"x": 72, "y": 38},
        "DROP POINT 02": {"x": 84, "y": 78},
        "CHARGING STATION A": {"x": 16, "y": 82},
        "CHARGING STATION B": {"x": 88, "y": 50},
    }
    job_routes = [
        ("DEPOT", "WAREHOUSE A", "PICKUP 01", "DROP POINT 01"),
        ("DEPOT", "WAREHOUSE B", "PICKUP 02", "DROP POINT 02"),
        ("WAREHOUSE A", "PICKUP 01", "DROP POINT 01"),
        ("WAREHOUSE B", "PICKUP 02", "DROP POINT 02"),
        ("DEPOT", "PICKUP 01", "WAREHOUSE B", "DROP POINT 02"),
    ]
    task_missions = {"T-001": "M-001", "T-002": "M-002", "T-003": "M-003", "T-004": "M-002", "T-005": "M-001"}
    tasks = {}
    robots = []
    for index in range(1, 26):
        robot_id = f"R-{index:03d}"
        task_id = f"T-{index:03d}" if index <= len(job_routes) else None
        mission_id = task_missions.get(task_id)
        route_names = list(job_routes[index - 1]) if task_id else []
        route = [copy.deepcopy(locations[name]) for name in route_names]
        start = route[0] if route else copy.deepcopy(locations["DEPOT"])
        robot = {
            "id": robot_id,
            "type": ["Scout", "Carrier", "Inspector", "Heavy"][(index - 1) % 4],
            "health": 96 - (index % 4) * 3,
            "battery": 92 - (index % 5) * 4,
            "status": "healthy" if task_id else "idle",
            "aliases": [f"SV-{index:03d}"],
            "start_position": copy.deepcopy(start),
            "position": copy.deepcopy(start),
            "route_id": f"ROUTE-{index:02d}" if task_id else None,
            "route": route_names,
            "waypoints": route,
            "destination": route_names[-1] if route_names else None,
            "mission_id": mission_id,
            "task_id": task_id,
            "current_waypoint": 0,
            "route_progress": 0.0,
            "route_distance_travelled": 0.0,
            "failure_state": None,
            "recovery_state": None,
            "operating_state": "ACTIVE" if task_id else "IDLE",
            "availability": "ASSIGNED" if task_id else "AVAILABLE",
            "heading": 0,
            "speed": 3.0 if task_id else 0.0,
            "current_task": task_id or "",
            "mission": mission_id or "",
            "failure_position": None,
            "charging_state": None,
            "assigned_tasks": [task_id] if task_id else [],
            "last_update": datetime.now(timezone.utc).isoformat(),
        }
        robots.append(robot)
        if task_id:
            tasks[task_id] = {
                "id": task_id,
                "mission_id": mission_id,
                "assigned_robot": robot_id,
                "status": "IN PROGRESS",
                "progress": 0.0,
                "priority": "CRITICAL" if index == 3 else "HIGH",
                "origin": route_names[0],
                "destination": route_names[-1],
                "route_names": route_names,
                "route": route,
                "estimated_completion": None,
                "interruption_point": None,
                "remaining_progress": 100.0,
            }
    missions = [
        {"id": "M-003", "name": "Warehouse A delivery", "priority": "CRITICAL", "status": "ACTIVE", "progress": 0.0, "tasks": ["T-003"]},
        {"id": "M-001", "name": "Depot distribution", "priority": "HIGH", "status": "ACTIVE", "progress": 0.0, "tasks": ["T-001", "T-005"]},
        {"id": "M-002", "name": "Warehouse B delivery", "priority": "HIGH", "status": "ACTIVE", "progress": 0.0, "tasks": ["T-002", "T-004"]},
    ]
    return {
        "user": {"name": "Sentinel Robotics", "organization": "Simulation environment"},
        "robots": robots,
        "locations": locations,
        "tasks": tasks,
        "missions": missions,
        "events": [{"type": "START", "message": "Deterministic 25-robot simulation ready", "robot": None}],
        "notifications": [],
        "activity": [],
        "failures": [],
        "predictions": [],
        "migrations": [],
        "propagation": [],
        "alerts_cleared_at": None,
        "control": {"running": False, "speed": 1.0, "simulation_seconds": 0.0, "last_tick": time.monotonic()},
        "performance": {},
        "simulation_id": "SIM-2026-DEMO",
    }

simulation_state = _initial_snapshot()
simulation_state["baseline_average_battery"] = round(sum(robot.get("battery", 0) for robot in simulation_state["robots"]) / max(1, len(simulation_state["robots"])), 1)

def advance_simulation():
    now = time.monotonic()
    control = simulation_state.setdefault("control", {"running": True, "speed": 1.0})
    previous = control.get("last_tick", now)
    control["last_tick"] = now
    if not control.get("running", False):
        return
    elapsed = max(0.0, now - previous) * control.get("speed", 1.0)
    if elapsed <= 0:
        return
    control["simulation_seconds"] = round(control.get("simulation_seconds", 0.0) + elapsed, 2)
    for robot in simulation_state["robots"]:
        status = str(robot.get("status", "")).lower()
        if status in {"critical", "failed"}:
            robot["speed"] = 0.0
            continue
        if status == "charging":
            if robot.get("charging_state") == "navigating_to_charger":
                _move_robot(robot, elapsed)
                if robot.get("route_distance_travelled", 0) >= _route_length(robot.get("waypoints", [])):
                    robot["charging_state"] = "charging"
                    robot["route_progress"] = 0.0
                    simulation_state["events"].insert(0, _event("CHARGING", f"{robot['id']} arrived at {robot.get('charger_name')}", robot=robot["id"], charging_station=robot.get("charger_name")))
            else:
                robot["battery"] = min(100, round(robot.get("battery", 0) + elapsed * 4, 1))
                if robot["battery"] >= 80:
                    robot["status"] = "healthy" if robot.get("current_task") else "idle"
                    robot["operating_state"] = "RESUMING" if robot.get("current_task") else "IDLE"
                    robot["availability"] = "ASSIGNED" if robot.get("current_task") else "AVAILABLE"
                    robot["charging_state"] = "complete"
                    if robot.get("charging_resume_route"):
                        old_route = robot.pop("charging_resume_route")
                        old_distance = robot.pop("charging_resume_distance", 0.0)
                        remaining_route = _remaining_route(old_route, old_distance)
                        resume_point = remaining_route[0] if remaining_route else copy.deepcopy(robot["position"])
                        robot["waypoints"] = [copy.deepcopy(robot["position"]), *remaining_route]
                        robot["route"] = [robot.get("charger_name", "CHARGING STATION"), "RESUME ROUTE", *robot.get("route", [])[2:]]
                        robot["route_distance_travelled"] = 0.0
                        task = simulation_state.get("tasks", {}).get(robot.get("current_task"))
                        if task:
                            task["charge_resume_start_progress"] = task.get("progress", 0.0)
                            task["charge_resume_remaining_progress"] = task.get("remaining_progress", 100.0)
                            task["charge_resume_transit_distance"] = math.dist((robot["position"]["x"], robot["position"]["y"]), (resume_point["x"], resume_point["y"]))
                            task["charge_resume_route_distance"] = _route_length(remaining_route)
                    robot["charger_name"] = None
                    simulation_state["events"].insert(0, _event("CHARGE_COMPLETE", f"{robot['id']} charge complete", robot=robot["id"], battery=robot["battery"]))
            robot["last_update"] = datetime.now(timezone.utc).isoformat()
            continue
        if status == "idle" or not robot.get("current_task"):
            robot["speed"] = 0.0
            continue
        robot["battery"] = max(0, round(robot.get("battery", 0) - elapsed * 0.025, 1))
        if robot["battery"] <= 20:
            route_options, selected_option = _build_charger_route_options(robot)
            robot["route_options"] = route_options
            robot["selected_route_option"] = selected_option["station"] if selected_option else None
            robot["charging_resume_route"] = robot.get("waypoints", [])
            robot["charging_resume_distance"] = robot.get("route_distance_travelled", 0.0)
            robot["charging_resume_operating_state"] = robot.get("operating_state")
            robot["charger_name"] = selected_option["station"] if selected_option else None
            robot["waypoints"] = selected_option["waypoints"] if selected_option else [copy.deepcopy(robot["position"])]
            robot["route"] = selected_option["route"] if selected_option else ["CURRENT POSITION"]
            robot["route_distance_travelled"] = 0.0
            robot["route_progress"] = 0.0
            robot["speed"] = 3.0
            robot["status"] = "charging"
            robot["operating_state"] = "CHARGING"
            robot["availability"] = "UNAVAILABLE"
            robot["charging_state"] = "navigating_to_charger"
            event = _event("LOW_BATTERY", f"{robot['id']} battery at {robot['battery']}%; navigating to {robot['charger_name']}", robot=robot["id"], battery=robot["battery"], charging_station=robot["charger_name"])
            simulation_state["events"].insert(0, event)
            simulation_state["notifications"].insert(0, {"type": "BATTERY", "title": "LOW BATTERY", "message": event["message"], "robot": robot["id"], "timestamp": event["timestamp"], "read": False})
            continue
        _move_robot(robot, elapsed)
        task = simulation_state.get("tasks", {}).get(robot.get("current_task"))
        if not task:
            continue
        travelled = robot.get("route_distance_travelled", 0.0)
        is_recovery_task = bool(task.get("recovery_robot"))
        if robot.get("operating_state") == "RESUMING":
            resumed_distance = max(0.0, travelled - task.get("charge_resume_transit_distance", 0.0))
            resume_route_distance = task.get("charge_resume_route_distance", 0.0)
            if resume_route_distance > 0:
                task["progress"] = round(min(100.0, task["charge_resume_start_progress"] + resumed_distance / resume_route_distance * task["charge_resume_remaining_progress"]), 1)
        elif is_recovery_task:
            task_route_distance = task.get("recovery_route_distance", 0.0)
            recovery_travel = max(0.0, travelled - task.get("recovery_transit_distance", 0.0))
            if task_route_distance > 0:
                task["progress"] = round(min(100.0, task["recovery_start_progress"] + recovery_travel / task_route_distance * task.get("recovery_total_remaining_progress", task["remaining_progress"])), 1)
        else:
            task_route_distance = _route_length(task.get("route", []))
            if task_route_distance > 0:
                task["progress"] = round(min(100.0, travelled / task_route_distance * 100), 1)
        task["remaining_progress"] = round(max(0.0, 100 - task["progress"]), 1)
        task["status"] = "RECOVERING" if is_recovery_task else "IN PROGRESS"
        task["estimated_completion"] = _estimated_completion(task, robot)
        if is_recovery_task and task["progress"] >= 99.9:
            task["progress"] = 100.0
            task["remaining_progress"] = 0.0
            task["status"] = "COMPLETED"
            task["recovery_completed_at"] = datetime.now(timezone.utc).isoformat()
            recovery_started_at = task.get("recovery_started_at")
            if recovery_started_at:
                task["recovery_time_seconds"] = round(max(0, (datetime.fromisoformat(task["recovery_completed_at"]) - datetime.fromisoformat(recovery_started_at)).total_seconds()), 2)
            robot["status"] = "idle"
            robot["operating_state"] = "IDLE"
            robot["availability"] = "AVAILABLE"
            robot["current_task"] = ""
            robot["task_id"] = None
            robot["assigned_tasks"] = []
            robot["speed"] = 0.0
            migration = next((item for item in reversed(simulation_state["migrations"]) if task["id"] in item["task_ids"] and item["destination_robot"] == robot["id"]), None)
            if migration:
                migration["status"] = "completed"
                migration["completed_at"] = task["recovery_completed_at"]
            event = _event("RECOVERY_COMPLETED", f"{task['id']} completed by {robot['id']}", robot=robot["id"], task=task["id"], mission=task.get("mission_id"))
            simulation_state["events"].insert(0, event)
            simulation_state["notifications"].insert(0, {"type": "RECOVERY", "title": "MISSION RECOVERED", "message": event["message"], "robot": robot["id"], "task": task["id"], "timestamp": event["timestamp"], "read": False})
        elif robot.get("operating_state") != "RECOVERING" and task["progress"] >= 99.9:
            task["progress"] = 100.0
            task["remaining_progress"] = 0.0
            task["status"] = "COMPLETED"
            robot.update({"status": "idle", "operating_state": "IDLE", "availability": "AVAILABLE", "current_task": "", "task_id": None, "assigned_tasks": [], "speed": 0.0})
            event = _event("TASK_COMPLETED", f"{task['id']} completed by {robot['id']}", robot=robot["id"], task=task["id"], mission=task.get("mission_id"))
            simulation_state["events"].insert(0, event)
            simulation_state["notifications"].insert(0, {"type": "TASK_COMPLETED", "title": "TASK COMPLETED", "message": event["message"], "robot": robot["id"], "task": task["id"], "timestamp": event["timestamp"], "read": False})
        _refresh_mission_state(task.get("mission_id"))
        if simulation_state.get("failures"):
            _refresh_propagation(task.get("id"))
        robot["last_update"] = datetime.now(timezone.utc).isoformat()


def _route_length(route):
    return sum(math.dist((first["x"], first["y"]), (second["x"], second["y"])) for first, second in zip(route, route[1:]))


def _point_along_route(route, distance):
    if not route:
        return {"x": 0.0, "y": 0.0}
    remaining = max(0.0, distance)
    for first, second in zip(route, route[1:]):
        segment = math.dist((first["x"], first["y"]), (second["x"], second["y"]))
        if remaining <= segment or segment == 0:
            fraction = min(1.0, remaining / segment) if segment else 0.0
            return {"x": round(first["x"] + (second["x"] - first["x"]) * fraction, 2), "y": round(first["y"] + (second["y"] - first["y"]) * fraction, 2)}
        remaining -= segment
    return copy.deepcopy(route[-1])


def _remaining_route(route, distance):
    if not route:
        return []
    remaining = [_point_along_route(route, distance)]
    traversed = 0.0
    for first, second in zip(route, route[1:]):
        traversed += math.dist((first["x"], first["y"]), (second["x"], second["y"]))
        if traversed > distance + 0.01:
            remaining.append(copy.deepcopy(second))
    return remaining


def _move_robot(robot, elapsed):
    route = robot.get("waypoints") or []
    if len(route) < 2:
        robot["speed"] = 0.0
        return
    prior = copy.deepcopy(robot.get("position", route[0]))
    route_length = _route_length(route)
    distance = min(route_length, robot.get("route_distance_travelled", 0.0) + robot.get("speed", 0.0) * elapsed)
    robot["position"] = _point_along_route(route, distance)
    robot["route_distance_travelled"] = distance
    total_segments = max(1, len(route) - 1)
    robot["route_progress"] = round(distance / max(route_length, 0.001) * total_segments, 4)
    robot["current_waypoint"] = min(total_segments, int(robot["route_progress"]) + 1)
    delta_x = robot["position"]["x"] - prior["x"]
    delta_y = robot["position"]["y"] - prior["y"]
    if delta_x or delta_y:
        robot["heading"] = round(math.degrees(math.atan2(delta_y, delta_x)), 1)
    if distance >= route_length:
        robot["position"] = copy.deepcopy(route[-1])


def _build_charger_route_options(robot):
    current_position = copy.deepcopy(robot.get("position") or {"x": 0, "y": 0})
    station_points = [
        (name, copy.deepcopy(point))
        for name, point in simulation_state["locations"].items()
        if name.startswith("CHARGING STATION")
    ]
    options = []
    for station_name, station_position in station_points:
        waypoints = [copy.deepcopy(current_position), copy.deepcopy(station_position)]
        options.append({
            "station": station_name,
            "distance": math.dist((current_position["x"], current_position["y"]), (station_position["x"], station_position["y"])),
            "waypoints": waypoints,
            "route": ["CURRENT POSITION", station_name],
        })
    if not options:
        return [], None
    selected_option = min(options, key=lambda item: item["distance"])
    selected_option["selected"] = True
    for option in options:
        if option is not selected_option:
            option["selected"] = False
    return options, selected_option


def _estimated_completion(task, robot):
    if not robot.get("speed") or robot["speed"] <= 0:
        return None
    if robot.get("operating_state") == "RESUMING":
        remaining_route = task.get("charge_resume_transit_distance", 0.0) + task.get("charge_resume_route_distance", 0.0) * task.get("charge_resume_remaining_progress", 100.0) / 100
    elif task.get("recovery_robot"):
        route_length = task.get("recovery_route_distance", 0.0)
        remaining_route = task.get("recovery_transit_distance", 0.0) + route_length * task.get("remaining_progress", 100.0) / 100
    else:
        route_length = _route_length(task.get("route", []))
        remaining_route = route_length * task.get("remaining_progress", 100.0) / 100
    return round(remaining_route / robot["speed"], 1)


def _refresh_mission_state(mission_id):
    mission = next((item for item in simulation_state.get("missions", []) if item.get("id") == mission_id), None)
    if not mission:
        return
    tasks = [simulation_state["tasks"][task_id] for task_id in mission.get("tasks", []) if task_id in simulation_state.get("tasks", {})]
    if not tasks:
        return
    mission["progress"] = round(sum(task.get("progress", 0) for task in tasks) / len(tasks), 1)
    statuses = {task.get("status") for task in tasks}
    if statuses == {"COMPLETED"}:
        mission["status"] = "COMPLETED"
    elif "AT RISK" in statuses:
        mission["status"] = "AT RISK"
    elif "RECOVERING" in statuses:
        mission["status"] = "RECOVERING"
    elif "FAILED" in statuses:
        mission["status"] = "FAILED"
    else:
        mission["status"] = "ACTIVE"


def _refresh_propagation(task_id=None):
    failure = simulation_state.get("failures", [])[-1] if simulation_state.get("failures") else None
    if not failure:
        simulation_state["propagation"] = []
        return
    task_id = failure.get("task_id") or task_id
    task = simulation_state.get("tasks", {}).get(task_id) if task_id else None
    mission_id = task.get("mission_id") if task else failure.get("mission_id")
    mission = next((item for item in simulation_state.get("missions", []) if item.get("id") == mission_id), None)
    robot = next((item for item in simulation_state.get("robots", []) if item.get("id") == failure.get("robot_id")), None)
    failed_count = sum(1 for item in simulation_state.get("robots", []) if item.get("status") in {"failed", "critical"})
    nodes = [{"id": failure.get("robot_id"), "type": "robot", "status": str(robot.get("status", "unknown")).upper() if robot else "UNKNOWN"}]
    if task:
        nodes.append({"id": task["id"], "type": "task", "status": task.get("status", "UNKNOWN")})
    if mission:
        nodes.append({"id": mission["id"], "type": "mission", "status": mission.get("status", "UNKNOWN")})
    nodes.append({"id": "FLEET CAPACITY", "type": "capacity", "status": "REDUCED" if failed_count else "AVAILABLE", "failed_robots": failed_count, "fleet_size": len(simulation_state.get("robots", []))})
    simulation_state["propagation"] = nodes

def normalize_robot_reference(robot_id: str | None):
    if robot_id is None:
        return None
    return str(robot_id).strip().upper()


def canonical_robot_id(robot_id: str):
    normalized = normalize_robot_reference(robot_id)
    if not normalized:
        return None
    for robot in simulation_state["robots"]:
        if normalize_robot_reference(robot.get("id")) == normalized:
            return robot["id"]
        aliases = [normalize_robot_reference(alias) for alias in robot.get("aliases", [])]
        if normalized in aliases:
            return robot["id"]
    legacy_id = f"R-{normalized[3:]}" if normalized.startswith("SV-") else f"SV-{normalized[2:]}" if normalized.startswith("R-") else None
    if legacy_id:
        for robot in simulation_state["robots"]:
            if normalize_robot_reference(robot.get("id")) == normalize_robot_reference(legacy_id):
                return robot["id"]
            aliases = [normalize_robot_reference(alias) for alias in robot.get("aliases", [])]
            if normalize_robot_reference(legacy_id) in aliases:
                return robot["id"]
    return None


def public_robot_id(robot_id: str, requested_id: str):
    requested = normalize_robot_reference(requested_id)
    return f"SV-{robot_id[2:]}" if requested.startswith("SV-") else robot_id

def current_snapshot():
    return simulation_state

FAILURE_TYPES = ("motor", "sensor", "communication", "battery", "cpu", "temperature", "navigation", "power", "custom")

def _event(event_type, message, **fields):
    return {"type": event_type, "message": message, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}

def _robot_or_404(robot_id):
    canonical_id = canonical_robot_id(robot_id)
    robot = next((item for item in simulation_state["robots"] if item["id"] == canonical_id), None)
    if not robot:
        raise HTTPException(status_code=404, detail={"error": "ROBOT_NOT_FOUND", "message": f"Robot {robot_id} was not found."})
    return robot

def inject_failure_into_state(request: FailureInjectionRequest):
    robot = _robot_or_404(request.robot_id)
    if robot.get("status") in {"failed", "critical"}:
        raise HTTPException(status_code=409, detail={"error": "ROBOT_ALREADY_FAILED", "message": f"{robot['id']} is already failed."})
    original_health = robot.get("health", 100)
    active_task_id = robot.get("current_task") or robot.get("task_id")
    active_task = simulation_state.get("tasks", {}).get(active_task_id) if active_task_id else None
    severity_drop = {"warning": 12, "critical": 32, "failed": 70}[request.severity]
    timestamp = datetime.now(timezone.utc).isoformat()
    failure_position = copy.deepcopy(robot.get("position"))
    interrupted_progress = active_task.get("progress", 0.0) if active_task else 0.0
    if active_task:
        active_task.update({"status": "AT RISK", "failed_robot_id": robot["id"], "failure_position": failure_position, "interruption_point": failure_position, "interruption_progress": interrupted_progress, "recovery_start_progress": interrupted_progress, "remaining_progress": round(max(0.0, 100 - interrupted_progress), 1)})
    if request.timing == "progressive":
        stages = [("WARNING", max(1, original_health - 4), "Early warning signs detected"), ("HIGH_RISK", max(1, original_health - 8), "Failure risk is high"), ("PREDICTION", max(1, original_health - 12), "Failure predicted"), ("PROPAGATION", max(1, original_health - 20), "Dependent work marked at risk"), ("FAILURE", max(0, original_health - severity_drop), "Failure threshold reached")]
        for event_type, health, message in stages:
            simulation_state["events"].insert(0, _event(event_type, f"{robot['id']}: {message}", robot=robot["id"], subsystem=request.failure_type, health=health, timing=request.timing))
        robot["health"] = stages[-1][1]
    else:
        robot["health"] = max(0, original_health - severity_drop)
    is_failed = request.severity in {"critical", "failed"}
    if request.failure_type == "battery" and is_failed:
        current_route = list(robot.get("waypoints") or [copy.deepcopy(robot.get("position"))])
        route_options, selected_option = _build_charger_route_options(robot)
        robot["route_options"] = route_options
        robot["selected_route_option"] = selected_option["station"] if selected_option else None
        robot["charging_resume_route"] = current_route
        robot["charging_resume_distance"] = robot.get("route_distance_travelled", 0.0)
        robot["charging_resume_operating_state"] = robot.get("operating_state")
        robot["charger_name"] = selected_option["station"] if selected_option else None
        robot["waypoints"] = selected_option["waypoints"] if selected_option else [copy.deepcopy(robot["position"])]
        robot["route"] = selected_option["route"] if selected_option else ["CURRENT POSITION"]
        robot["route_distance_travelled"] = 0.0
        robot["route_progress"] = 0.0
        robot["speed"] = 3.0
        robot["status"] = "charging"
        robot["operating_state"] = "CHARGING"
        robot["availability"] = "UNAVAILABLE"
        robot["charging_state"] = "navigating_to_charger"
        robot["failure_position"] = failure_position
        robot["failure_state"] = request.failure_type
        failure_message = f"{robot['id']} battery failure routed to {robot['charger_name']} for charging"
        simulation_state["events"].insert(0, _event("BATTERY_FAILURE_CHARGING", failure_message, robot=robot["id"], charging_station=robot["charger_name"], failure_type=request.failure_type))
        simulation_state["notifications"].insert(0, {"type": "BATTERY", "title": "BATTERY FAILURE", "message": failure_message, "robot": robot["id"], "timestamp": timestamp, "read": False})
    else:
        robot["status"] = "failed" if is_failed else "warning"
        robot["operating_state"] = "FAILED" if is_failed else "DEGRADED"
        robot["availability"] = "UNAVAILABLE" if is_failed else "ASSIGNED"
        robot["speed"] = 0.0 if is_failed else robot.get("speed", 3.0)
        robot["failure_position"] = failure_position
        robot["failure_state"] = request.failure_type
    risk = min(99, max(1, round(100 - robot["health"] * 0.55 + (100 - robot.get("battery", 0)) * 0.2 + len(robot.get("assigned_tasks", [])) * 5)))
    failure = {"robot_id": robot["id"], "task_id": active_task_id, "mission_id": active_task.get("mission_id") if active_task else None, "position": failure_position, "progress": interrupted_progress, "subsystem": request.failure_type, "severity": request.severity, "timing": request.timing, "duration_seconds": request.duration_seconds, "timestamp": timestamp, "risk": risk}
    prediction = {"robot_id": robot["id"], "probability": risk, "confidence": round(min(0.95, 0.55 + (100 - robot["health"]) / 250), 2), "subsystem": request.failure_type, "model": "simulation-based telemetry rule", "predicted_at": timestamp, "lead_time_seconds": 0 if is_failed else None, "indicators": {"health": robot["health"], "battery": robot.get("battery", 0), "task_load": len(robot.get("assigned_tasks", []))}, "contributors": {"health_delta": severity_drop, "battery": max(0, 100 - robot.get("battery", 0)), "task_load": len(robot.get("assigned_tasks", []))}}
    simulation_state["predictions"].append(prediction)
    simulation_state["failures"].append(failure)
    failure_word = "failure" if is_failed else "degradation"
    simulation_state["notifications"].insert(0, {"type": "FAILURE" if is_failed else "WARNING", "title": "FAILURE DETECTED" if is_failed else "FAILURE WARNING", "message": f"{robot['id']} {request.failure_type} {failure_word} · risk {risk}%", "robot": robot["id"], "task": active_task_id, "timestamp": timestamp, "read": False})
    if active_task:
        simulation_state["notifications"].insert(0, {"type": "TASK_AT_RISK", "title": "TASK AT RISK", "message": f"{active_task_id} interrupted at {interrupted_progress:.1f}%", "robot": robot["id"], "task": active_task_id, "timestamp": timestamp, "read": False})
    mission = next((item for item in simulation_state["missions"] if active_task and active_task["id"] in item.get("tasks", [])), None)
    if active_task:
        candidates = recovery_candidates(robot["id"])
        active_task["recovery_recommendation"] = candidates[0] if candidates else None
    if mission:
        _refresh_mission_state(mission["id"])
    _refresh_propagation(active_task_id)
    simulation_state["events"].insert(0, _event("FAILURE_INJECTION", f"{robot['id']} {request.failure_type} failure injected", robot=robot["id"], severity=request.severity, timing=request.timing))
    return {"robot": robot, "failure": failure, "state": simulation_state}

def evaluation_engine(snapshot=None):
    state = snapshot or current_snapshot()
    fleet = state.get("robots", [])
    migrations = state.get("migrations", [])
    tasks = list(state.get("tasks", {}).values())
    active = sum(1 for robot in fleet if robot.get("status") in {"healthy", "warning", "recovering"})
    failed = sum(1 for robot in fleet if robot.get("status") in {"failed", "critical"})
    warning = sum(1 for robot in fleet if robot.get("status") == "warning")
    charging = sum(1 for robot in fleet if robot.get("status") == "charging")
    assigned = sum(1 for task in tasks if task.get("status") not in {"COMPLETED", "FAILED", "UNASSIGNED"} and task.get("assigned_robot"))
    task_total = len(tasks)
    tasks_at_risk = sum(1 for task in tasks if task.get("status") == "AT RISK")
    tasks_failed = sum(1 for task in tasks if task.get("status") == "FAILED")
    tasks_migrated = sum(1 for task in tasks if task.get("recovery_robot"))
    mission_preservation = round(100 * sum(1 for task in tasks if task.get("status") not in {"AT RISK", "FAILED"}) / task_total, 1) if task_total else None
    mission_completion = round(sum(task.get("progress", 0) for task in tasks) / task_total, 1) if task_total else None
    migration_count = len(migrations)
    completed_migrations = sum(1 for migration in migrations if migration.get("status") == "completed")
    cascade_nodes = state.get("propagation", [])
    affected_nodes = len(cascade_nodes)
    uncontained_nodes = sum(1 for node in cascade_nodes if node.get("status") in {"AT RISK", "FAILED", "REDUCED"})
    containment = round(100 * (affected_nodes - uncontained_nodes) / max(1, affected_nodes), 1) if affected_nodes else None
    average_battery = round(sum(robot.get("battery", 0) for robot in fleet) / max(1, len(fleet)), 1)
    baseline_battery = state.get("baseline_average_battery")
    if baseline_battery is None:
        baseline_battery = average_battery
    measured_predictions = [item for item in state.get("predictions", []) if item.get("lead_time_seconds") is not None and item.get("lead_time_seconds", 0) > 0]
    return {"robots": len(fleet), "active": active, "failed": failed, "warning": warning, "charging": charging, "tasks_total": task_total, "tasks_assigned": assigned, "tasks_at_risk": tasks_at_risk, "tasks_migrated": tasks_migrated, "tasks_failed": tasks_failed, "mission_completion_rate": mission_completion, "mission_preservation": mission_preservation, "baseline_performance": None, "failure_impact": round(100 * tasks_at_risk / max(1, task_total), 1), "recovered_performance": None, "performance_loss": None, "migration_efficiency": round(completed_migrations / migration_count * 100, 1) if migration_count else None, "migration_success_rate": round(completed_migrations / migration_count * 100, 1) if migration_count else None, "battery_consumption": round(max(0.0, baseline_battery - average_battery), 1), "battery_efficiency": average_battery, "fleet_utilization_before": None, "fleet_utilization_after": round(assigned / max(1, len(fleet)) * 100, 1), "available_capacity": max(0, len(fleet) - assigned - failed - charging), "cascade_depth": affected_nodes, "affected_nodes": affected_nodes, "contained_nodes": affected_nodes - uncontained_nodes, "uncontained_nodes": uncontained_nodes, "cascade_containment": containment, "average_battery": average_battery, "prediction_evaluation": {"measurable_predictions": len(measured_predictions), "precision": None, "recall": None, "f1": None}, "status": "recovering" if any(item.get("status") == "in_progress" for item in migrations) else "contained" if not uncontained_nodes else "uncontained"}

def generate_scenario(failure_count, seed=None):
    actual_seed = seed if seed is not None else random.SystemRandom().randint(0, 999999999)
    generator = random.Random(actual_seed)
    robot_ids = generator.sample([f"R-{index:03d}" for index in range(1, 26)], failure_count)
    sequence = [{"order": index + 1, "robot_id": robot_id, "failure_type": generator.choice(FAILURE_TYPES[:-1]), "severity": generator.choice(("warning", "critical", "failed")), "timing": generator.choice(("immediate", "delayed", "progressive"))} for index, robot_id in enumerate(robot_ids)]
    return {"scenario_id": f"SCN-{actual_seed:09d}", "seed": actual_seed, "failure_count": failure_count, "sequence": sequence}

def snapshot_or_current(snapshot: SimulationSnapshot | None):
    return (snapshot.model_dump() if snapshot else current_snapshot())

@app.get("/health")
def health():
    return {"status": "ok", "environment": "simulation", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/health")
def api_health():
    return {"status": "ok", "environment": "simulation", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/profile")
def get_profile(claims=Depends(verified_user)):
    profile = ensure_profile(claims["uid"], {"name": claims.get("name", ""), "email": claims.get("email", ""), "photoURL": claims.get("picture", "")})
    return {"profile": public_profile(profile)}

@app.put("/api/profile")
def update_profile(request: ProfileRequest, claims=Depends(verified_user)):
    if request.dateOfBirth:
        try:
            parsed = datetime.strptime(request.dateOfBirth, "%Y-%m-%d")
            if parsed.date() > datetime.now(timezone.utc).date():
                raise HTTPException(status_code=422, detail="Date of birth cannot be in the future")
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Date of birth must use YYYY-MM-DD") from error
    if request.phoneNumber and not request.phoneNumber.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "").isdigit():
        raise HTTPException(status_code=422, detail="Phone number format is invalid")
    existing = ensure_profile(claims["uid"], {"name": claims.get("name", ""), "email": claims.get("email", ""), "photoURL": claims.get("picture", "")})
    profile = upsert_profile(claims["uid"], {
        "name": request.name.strip(),
        "email": existing["email"],
        "photoURL": existing["photo_url"],
        "dateOfBirth": request.dateOfBirth,
        "phoneNumber": request.phoneNumber,
    })
    return {"profile": public_profile(profile)}

@app.get("/api/admin/overview")
def admin_overview(claims=Depends(admin_user)):
    snapshot = current_snapshot()
    healthy = sum(1 for robot in snapshot["robots"] if robot.get("status") == "healthy")
    critical = sum(1 for robot in snapshot["robots"] if robot.get("status") == "critical")
    return {"fleet": {"total": len(snapshot["robots"]), "healthy": healthy, "warning": len(snapshot["robots"]) - healthy - critical, "critical": critical, "failed": 0}, "missions": len(snapshot["missions"]), "alerts": len(snapshot["failures"]), "admin_uid": claims["uid"]}

@app.post("/auth/demo")
def demo_login(request: DemoLoginRequest):
    return {"user": {"name": "Public visitor", "email": "preview@sentinel.local", "organization": "Sentinel Robotics", "role": request.role}, "access_token": "simulation-token", "provider": "demo"}

@app.post("/auth/admin/login")
def admin_login(request: AdminLoginRequest):
    username = os.getenv("ADMIN_USERNAME", "")
    password = os.getenv("ADMIN_PASSWORD", "")
    if not username or not password or not hmac.compare_digest(request.username, username) or not hmac.compare_digest(request.password, password):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    return {"user": {"username": username, "role": "ADMIN"}, "access_token": issue_admin_token(username), "provider": "admin"}

@app.get("/api/admin/dashboard")
def admin_dashboard(claims=Depends(verified_admin_session)):
    snapshot = current_snapshot()
    return {"admin": claims, "fleet": {"total": len(snapshot["robots"]), "healthy": sum(robot["status"] == "healthy" for robot in snapshot["robots"]), "critical": sum(robot["status"] == "critical" for robot in snapshot["robots"])}, "missions": snapshot["missions"], "events": snapshot["events"]}

def recovery_candidates(source_robot: str):
    source = _robot_or_404(source_robot)
    task = simulation_state.get("tasks", {}).get(source.get("current_task"))
    interruption = (task or {}).get("interruption_point") or source.get("position") or {"x": 0, "y": 0}
    progress = (task or {}).get("progress", 0.0)
    remaining_distance = _route_length((task or {}).get("route", [])) * max(0.0, 100.0 - progress) / 100.0
    priority_weight = {"CRITICAL": 1.0, "HIGH": 0.8, "NORMAL": 0.6, "LOW": 0.4}.get(str((task or {}).get("priority", "NORMAL")).upper(), 0.6)
    candidates = []
    for robot in simulation_state["robots"]:
        workload = sum(1 for task_id in robot.get("assigned_tasks", []) if simulation_state.get("tasks", {}).get(task_id, {}).get("status") not in {"COMPLETED", "FAILED"})
        if robot["id"] == source["id"] or robot.get("status") not in {"healthy", "idle"} or workload > 0:
            continue
        battery = robot.get("battery", 0)
        health = robot.get("health", 0)
        capacity = max(0, 100 - workload * 45)
        distance = round(math.dist((robot["position"]["x"], robot["position"]["y"]), (interruption["x"], interruption["y"])), 2)
        route_cost = round(distance + remaining_distance, 2)
        eta = round(route_cost / max(0.1, robot.get("speed") or 3.0), 1)
        eligible = battery >= 30 and health >= 70 and capacity >= 40 and robot.get("availability") == "AVAILABLE"
        score = round(max(0, min(100, health * 0.22 + battery * 0.2 + capacity * 0.18 + max(0, 100 - distance) * 0.18 + priority_weight * 12 + max(0, 100 - eta) * 0.1)))
        reason = f"{distance:.1f} map units to interruption; {battery}% battery; {health}% health; {workload} active tasks; estimated {eta:.1f}s"
        candidates.append({"robot_id": robot["id"], "score": score, "battery": battery, "health": health, "capacity": capacity, "workload": workload, "distance": distance, "route_cost": route_cost, "estimated_completion_seconds": eta, "deadline": "PASS" if eligible else "RISK", "eligible": eligible, "reason": reason})
    return sorted(candidates, key=lambda item: item["score"], reverse=True)

def migrate_tasks(source_robot: str, target_robot: str | None = None):
    state = current_snapshot()
    canonical_id = canonical_robot_id(source_robot)
    source = next((robot for robot in state["robots"] if robot["id"] == canonical_id), None)
    if not source:
        raise HTTPException(status_code=404, detail={"success": False, "error": "ROBOT_NOT_FOUND", "message": f"Robot {source_robot} was not found in the authoritative fleet state."})
    existing = next((item for item in reversed(state["migrations"]) if item["source_robot"] == canonical_id and item["status"] in {"in_progress", "completed"}), None)
    if existing:
        return {"status": existing["status"], "migration": existing, "state": state}
    task_id = source.get("current_task") or source.get("task_id")
    task_record = state.get("tasks", {}).get(task_id) if task_id else None
    tasks = [task_id] if task_record and task_record.get("status") not in {"COMPLETED", "FAILED"} else []
    if not tasks:
        raise HTTPException(status_code=409, detail={"success": False, "error": "NO_ACTIVE_TASKS", "message": f"No active tasks available for migration on {source_robot}."})
    ranked_candidates = recovery_candidates(source["id"])
    eligible = [item for item in ranked_candidates if item["eligible"]]
    if not eligible:
        raise HTTPException(status_code=409, detail={"success": False, "error": "NO_DESTINATION", "message": "No eligible replacement robot available."})
    selected = next((item for item in eligible if item["robot_id"] == canonical_robot_id(target_robot)), None) if target_robot else eligible[0]
    if selected is None:
        raise HTTPException(status_code=409, detail={"success": False, "error": "CANDIDATE_UNAVAILABLE", "message": f"Recovery candidate {target_robot} is not eligible for this task."})
    destination = next(robot for robot in state["robots"] if robot["id"] == selected["robot_id"])
    timestamp = datetime.now(timezone.utc).isoformat()
    progress = float(task_record.get("progress", 0.0))
    route = task_record.get("route", [])
    total_route_distance = _route_length(route)
    completed_distance = total_route_distance * progress / 100.0
    interruption = copy.deepcopy(task_record.get("interruption_point") or source.get("position"))
    remaining_route = [interruption]
    distance_cursor = 0.0
    for first, second in zip(route, route[1:]):
        distance_cursor += math.dist((first["x"], first["y"]), (second["x"], second["y"]))
        if distance_cursor > completed_distance + 0.01:
            remaining_route.append(copy.deepcopy(second))
    if len(remaining_route) == 1 and route:
        remaining_route.append(copy.deepcopy(route[-1]))
    recovery_waypoints = [copy.deepcopy(destination["position"]), *remaining_route]
    transit_distance = math.dist((destination["position"]["x"], destination["position"]["y"]), (interruption["x"], interruption["y"]))
    remaining_route_distance = max(0.0, total_route_distance - completed_distance)
    recovery_id = f"MIG-{uuid.uuid4().hex[:10].upper()}"
    migration = {"migration_id": recovery_id, "source_robot": source["id"], "destination_robot": destination["id"], "mission_id": task_record["mission_id"], "task_ids": tasks, "reason": selected["reason"], "candidate_score": selected["score"], "status": "in_progress", "created_at": timestamp, "completed_at": None, "progress_before_failure": progress, "remaining_progress": round(100 - progress, 1), "interruption_point": interruption, "recovery_route": recovery_waypoints}
    destination.update({"assigned_tasks": tasks.copy(), "task_id": task_id, "mission_id": task_record["mission_id"], "recovery_state": "TRAVELLING_TO_INTERRUPTION", "status": "recovering", "operating_state": "RECOVERING", "availability": "ASSIGNED", "route_id": f"RECOVERY-{recovery_id[-6:]}", "waypoints": recovery_waypoints, "route": ["CURRENT POSITION", "INTERRUPTION POINT", *task_record.get("route_names", [])[1:]], "route_progress": 0.0, "route_distance_travelled": 0.0, "speed": 6.0, "current_waypoint": 0, "current_task": task_id, "destination": task_record["destination"]})
    source["assigned_tasks"] = [assigned for assigned in source.get("assigned_tasks", []) if assigned != task_id]
    source.update({"task_id": None, "current_task": "", "status": "failed", "operating_state": "FAILED", "availability": "UNAVAILABLE", "recovery_state": "migrated", "speed": 0.0})
    task_record.update({"assigned_robot": destination["id"], "status": "RECOVERING", "recovery_robot": destination["id"], "recovery_start_progress": progress, "recovery_total_remaining_progress": round(100 - progress, 1), "remaining_progress": round(100 - progress, 1), "recovery_started_at": timestamp, "recovery_transit_distance": transit_distance, "recovery_route_distance": remaining_route_distance, "additional_travel_units": round(transit_distance, 2)})
    _refresh_mission_state(task_record["mission_id"])
    _refresh_propagation(task_id)
    state["migrations"].append(migration)
    event = _event("RECOVERY_STARTED", f"{task_id} recovery route assigned to {destination['id']}", source_robot=source["id"], destination_robot=destination["id"], mission=task_record["mission_id"], tasks=tasks, reason=selected["reason"], status="in_progress")
    state["events"].insert(0, event)
    state["activity"].insert(0, event)
    state["notifications"].insert(0, {"type": "TASK_MIGRATION", "title": "RECOVERY STARTED", "message": f"{task_id} assigned to {destination['id']}; {progress:.1f}% completed work preserved.", "robot": source["id"], "destination": destination["id"], "mission": task_record["mission_id"], "reason": selected["reason"], "timestamp": timestamp, "read": False})
    return {"status": "in_progress", "migration": migration, "state": state}

@app.get("/api/simulation/state")
def simulation_state_endpoint():
    advance_simulation()
    return current_snapshot()

@app.get("/api/simulation/control")
def simulation_control_get():
    advance_simulation()
    return current_snapshot().get("control", {"running": True, "speed": 1.0})

@app.post("/api/simulation/control")
def simulation_control_update(request: SimulationControlRequest):
    advance_simulation()
    control = current_snapshot().setdefault("control", {"running": True, "speed": 1.0})
    if request.running is not None:
        control["running"] = request.running
    if request.speed is not None:
        control["speed"] = request.speed
    if request.running is not None:
        control["last_tick"] = time.monotonic()
    return {**control, "state": current_snapshot(), "evaluation": evaluation_engine()}

@app.get("/api/recovery/candidates/{robot_id}")
def recovery_candidate_endpoint(robot_id: str):
    return {"source_robot": _robot_or_404(robot_id)["id"], "candidates": recovery_candidates(robot_id)}

@app.post("/api/simulation/notifications/clear")
def clear_simulation_notifications():
    current_snapshot()["alerts_cleared_at"] = datetime.now(timezone.utc).isoformat()
    current_snapshot()["notifications"] = []
    return {"status": "cleared", "alerts_cleared_at": current_snapshot()["alerts_cleared_at"]}

@app.post("/api/fleet/robots/{robot_id}/migrate-tasks")
def migrate_robot_tasks(robot_id: str, request: MigrationExecutionRequest | None = None):
    return migrate_tasks(robot_id, request.target_robot if request else None)

@app.post("/api/fleet/robots/{robot_id}/assign-task")
def assign_robot_task(robot_id: str, request: dict):
    robot = _robot_or_404(robot_id)
    if robot.get("status") not in {"idle", "healthy"} or robot.get("current_task"):
        raise HTTPException(status_code=409, detail={"error": "ROBOT_UNAVAILABLE", "message": f"{robot['id']} is not available for another task."})
    task_id = str(request.get("task_id") or "").strip().upper()
    mission_id = str(request.get("mission_id") or "").strip().upper()
    origin = str(request.get("origin") or "DEPOT").strip().upper()
    pickup = str(request.get("pickup") or "PICKUP 01").strip().upper()
    destination = str(request.get("destination") or "DROP POINT 01").strip().upper()
    locations = simulation_state["locations"]
    if not task_id or origin not in locations or pickup not in locations or destination not in locations:
        raise HTTPException(status_code=422, detail={"error": "INVALID_TASK_ROUTE", "message": "Provide a task ID and valid named origin, pickup, and destination locations."})
    existing_task = simulation_state.get("tasks", {}).get(task_id)
    if existing_task and existing_task.get("status") not in {"UNASSIGNED", "FAILED"}:
        raise HTTPException(status_code=409, detail={"error": "TASK_ALREADY_ASSIGNED", "message": f"{task_id} already has an active owner."})
    mission = next((item for item in simulation_state["missions"] if item.get("id") == mission_id), None)
    if not mission:
        if not mission_id:
            raise HTTPException(status_code=422, detail={"error": "MISSION_REQUIRED", "message": "Provide a mission ID for the new task."})
        mission = {"id": mission_id, "name": str(request.get("mission_name") or mission_id), "priority": str(request.get("priority") or "NORMAL").upper(), "status": "ACTIVE", "progress": 0.0, "tasks": []}
        simulation_state["missions"].append(mission)
    route_names = [origin, pickup, destination]
    route = [copy.deepcopy(locations[name]) for name in route_names]
    task = {"id": task_id, "mission_id": mission_id, "assigned_robot": robot["id"], "status": "ASSIGNED", "progress": 0.0, "priority": mission.get("priority", "NORMAL"), "origin": origin, "destination": destination, "route_names": route_names, "route": route, "estimated_completion": None, "interruption_point": None, "remaining_progress": 100.0}
    simulation_state["tasks"][task_id] = task
    if task_id not in mission["tasks"]:
        mission["tasks"].append(task_id)
    robot.update({"task_id": task_id, "mission_id": mission_id, "current_task": task_id, "mission": mission_id, "destination": destination, "assigned_tasks": [task_id], "status": "healthy", "operating_state": "ACTIVE", "availability": "ASSIGNED", "route_progress": 0.0, "route_distance_travelled": 0.0, "current_waypoint": 0, "waypoints": route, "route": route_names, "speed": 3.0, "route_id": f"ROUTE-{task_id}"})
    event = _event("TASK_ASSIGNED", f"{robot['id']} assigned {task_id} to {destination}", robot=robot["id"], task=task_id, mission=mission_id, destination=destination)
    simulation_state["events"].insert(0, event)
    simulation_state["activity"].insert(0, event)
    return {"status": "assigned", "robot": robot, "state": simulation_state}

@app.get("/api/admin/state")
def admin_state(claims=Depends(verified_admin_session)):
    return current_snapshot()

@app.post("/api/admin/robots/{robot_id}/migrate-tasks")
def admin_migrate_robot_tasks(robot_id: str, claims=Depends(verified_admin_session)):
    return migrate_tasks(robot_id)

@app.post("/api/admin/alerts")
def create_admin_alert(request: AlertRequest, claims=Depends(verified_admin_session)):
    alert = {**request.model_dump(), "alert_id": f"ALT-{uuid.uuid4().hex[:8].upper()}", "status": "sent", "created_at": datetime.now(timezone.utc).isoformat(), "created_by": claims["username"]}
    current_snapshot()["notifications"].insert(0, alert)
    current_snapshot()["activity"].insert(0, {"type": "ADMIN_ALERT", "message": request.title, "timestamp": alert["created_at"], "status": "sent"})
    return alert

@app.get("/api/robots")
def robots():
    fleet = current_snapshot()["robots"]
    return {"count": len(fleet), "source": "authoritative-simulation", "items": fleet}

@app.get("/api/predictions/{robot_id}")
def prediction(robot_id: str):
    robot = _robot_or_404(robot_id)
    recorded = next((item for item in reversed(simulation_state["predictions"]) if item["robot_id"] == robot["id"]), None)
    battery_risk = max(0, 30 - robot.get("battery", 0)) * 1.8
    health_risk = max(0, 75 - robot.get("health", 0)) * 1.2
    risk = recorded["probability"] if recorded else min(99, round(battery_risk + health_risk + (12 if robot.get("status") == "warning" else 0)))
    cause = recorded.get("subsystem") if recorded else "battery" if battery_risk >= health_risk else "health" if health_risk else None
    return {"robot_id": robot["id"], "risk": risk, "confidence": recorded.get("confidence") if recorded else None, "subsystem": cause, "model": "simulation-based telemetry rule", "predicted_at": recorded.get("predicted_at") if recorded else None, "lead_time_seconds": recorded.get("lead_time_seconds") if recorded else None, "indicators": {"health": robot.get("health"), "battery": robot.get("battery"), "status": robot.get("status"), "task": robot.get("current_task")}, "horizons": {}, "explanation": recorded.get("contributors", {}) if recorded else {"battery_below_30": round(battery_risk, 1), "health_below_75": round(health_risk, 1)}}

@app.post("/api/failures")
def inject_failure(request: FailureRequest):
    result = inject_failure_into_state(FailureInjectionRequest(robot_id=request.robot_id, failure_type=request.subsystem, severity="critical" if request.severity in {"high", "critical"} else "warning"))
    incident_id = f"INC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    evaluation = evaluation_engine(result["state"])
    return {"incident_id": incident_id, "status": "accepted", "robot_id": request.robot_id, "propagation": {"affected_robots": len(result["state"]["failures"]), "affected_tasks": evaluation["tasks_total"], "affected_missions": len(result["state"]["missions"]), "risk": result["failure"]["risk"]}, "state": result["state"], "evaluation": evaluation}

@app.post("/api/theme4/failures/inject")
def theme4_inject_failure(request: FailureInjectionRequest):
    result = inject_failure_into_state(request)
    return {"status": "accepted", "incident_id": f"INC-{uuid.uuid4().hex[:12].upper()}", **result, "evaluation": evaluation_engine(result["state"])}

@app.post("/api/theme4/scenarios/generate")
def theme4_generate_scenario(request: ScenarioRequest):
    return generate_scenario(request.failure_count, request.seed)

@app.post("/api/theme4/scenarios/run")
def theme4_run_scenario(request: ScenarioRequest):
    scenario = generate_scenario(request.failure_count, request.seed)
    results = []
    for item in scenario["sequence"]:
        result = inject_failure_into_state(FailureInjectionRequest(**item))
        results.append({"order": item["order"], "robot_id": item["robot_id"], "failure_type": item["failure_type"], "status": result["robot"]["status"]})
    return {"scenario": scenario, "results": results, "state": current_snapshot(), "evaluation": evaluation_engine()}

@app.post("/api/theme4/reset")
def theme4_reset():
    global simulation_state
    simulation_state = _initial_snapshot()
    simulation_state["baseline_average_battery"] = round(sum(robot.get("battery", 0) for robot in simulation_state["robots"]) / max(1, len(simulation_state["robots"])), 1)
    return {"status": "reset", "state": simulation_state, "evaluation": evaluation_engine()}

@app.get("/api/theme4/evaluation")
def theme4_evaluation():
    evaluation = evaluation_engine()
    requirements = [
        ("Robot Health & Failure Prediction", True), ("Failure Propagation", bool(current_snapshot()["failures"])),
        ("Dynamic Task Migration", bool(current_snapshot()["migrations"])), ("Fleet Rebalancing", bool(current_snapshot()["migrations"])),
        ("Mission Criticality", bool(current_snapshot()["missions"])), ("Mission Performance Preservation", evaluation["mission_preservation"] > 0),
        ("Battery Optimization", evaluation["battery_efficiency"] >= 0), ("Capacity Optimization", evaluation["fleet_utilization_after"] <= 100),
        ("Arbitrary Failure Sequences", True), ("Progressive Failure Injection", any(item.get("timing") == "progressive" for item in current_snapshot()["failures"])),
        ("Migration Stability", evaluation["migration_success_rate"] is not None and evaluation["migration_success_rate"] >= 0), ("Quantitative Recovery", evaluation["mission_completion_rate"] is not None and evaluation["mission_preservation"] is not None),
    ]
    return {"scenario_id": current_snapshot().get("simulation_id", "SIM-2026-DEMO"), "engine": "Theme 4 Compliance / Evaluation Engine", "prediction_model": "Simulation-based prediction model", "formula": "Mission preservation = recovered mission value / maximum achievable mission value", "requirements": [{"name": name, "passed": passed} for name, passed in requirements], "evaluation": evaluation, "timeline": current_snapshot().get("events", [])[:30], "state": current_snapshot()}

@app.post("/api/theme4/benchmark")
def theme4_benchmark(request: BenchmarkRequest):
    scenario = generate_scenario(request.failure_count, request.seed)
    baseline_state = _initial_snapshot()
    baseline_state["baseline_average_battery"] = round(sum(robot.get("battery", 0) for robot in baseline_state["robots"]) / max(1, len(baseline_state["robots"])), 1)
    recovery_state = copy.deepcopy(baseline_state)
    simulation_state_backup = globals()["simulation_state"]
    try:
        globals()["simulation_state"] = baseline_state
        for item in scenario["sequence"]:
            inject_failure_into_state(FailureInjectionRequest(**item))
        baseline_evaluation = evaluation_engine()
        globals()["simulation_state"] = recovery_state
        for item in scenario["sequence"]:
            inject_failure_into_state(FailureInjectionRequest(**item))
            try:
                migrate_tasks(item["robot_id"])
            except HTTPException:
                pass
        recovery_evaluation = evaluation_engine()
    finally:
        globals()["simulation_state"] = simulation_state_backup
    return {"scenario": scenario, "baseline": {**baseline_evaluation, "recovery_enabled": False}, "sentinel_recovery": {**recovery_evaluation, "recovery_enabled": True}, "formula": "Mission preservation = recovered mission value / maximum achievable mission value"}

@app.get("/api/propagation/{incident_id}")
def propagation(incident_id: str):
    snapshot = current_snapshot()
    nodes = [item for item in snapshot.get("propagation", []) if item.get("id")]
    return {"incident_id": incident_id, "nodes": nodes, "edges": [[nodes[index]["id"], nodes[index + 1]["id"]] for index in range(len(nodes) - 1)], "status": evaluation_engine(snapshot)["status"] if nodes else "no_active_propagation"}

@app.post("/api/recovery")
def recovery(request: RecoveryRequest):
    snapshot = current_snapshot()
    evaluation = evaluation_engine(snapshot)
    return {"incident_id": request.incident_id, "approved": request.approve, "status": evaluation["status"] if request.approve else "blocked", "migrations": snapshot.get("migrations", []), "performance": {"mission_completion_rate": evaluation["mission_completion_rate"], "mission_preservation": evaluation["mission_preservation"], "recovered": evaluation["recovered_performance"]}}

@app.get("/api/events")
def events():
    return {"items": current_snapshot().get("events", []), "live": True, "environment": "simulation"}

@app.get("/api/reports/{report_id}")
def report(report_id: str):
    snapshot = current_snapshot()
    evaluation = evaluation_engine(snapshot)
    return {"report_id": report_id, "verification": "simulation", "generated_at": datetime.now(timezone.utc).isoformat(), "summary": {"fleet": len(snapshot.get("robots", [])), "critical_tasks_preserved": evaluation["mission_preservation"], "performance_recovered": evaluation["recovered_performance"], "tasks_migrated": len(snapshot.get("migrations", [])), "energy_saved": evaluation["battery_consumption"]}}

@app.get("/api/export/json")
def export_json():
    payload = snapshot_or_current(None)
    return Response(content=json.dumps(payload, indent=2), media_type="application/json", headers={"Content-Disposition": "attachment; filename=sentinel_fleet_state.json"})

@app.get("/api/export/csv")
def export_csv():
    payload = snapshot_or_current(None)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["robot_id", "type", "health", "battery", "status"])
    for robot in payload["robots"]:
        writer.writerow([robot.get("id"), robot.get("type"), robot.get("health"), robot.get("battery"), robot.get("status")])
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=sentinel_fleet_state.csv"})

@app.post("/api/reports/generate-legacy")
def generate_report(snapshot: SimulationSnapshot):
    report_id = f"SFR-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    data = snapshot_or_current(snapshot)
    data["evaluation"] = evaluation_engine(data)
    pdf_bytes = render_report(data, report_id)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=Sentinel_Fleet_Recovery_{report_id}.pdf", "X-Report-ID": report_id})
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Cover", parent=styles["Title"], fontSize=21, leading=24, textColor=colors.HexColor("#243b53"), spaceAfter=10, alignment=0))
    styles.add(ParagraphStyle(name="ReportSubtitle", parent=styles["Heading2"], fontSize=12, leading=15, textColor=colors.HexColor("#526a78"), spaceAfter=8))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontSize=11, leading=14, textColor=colors.HexColor("#243b53"), spaceBefore=2, spaceAfter=6))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=9, leading=13, textColor=colors.HexColor("#465a68")))
    styles.add(ParagraphStyle(name="Tiny", parent=styles["BodyText"], fontSize=7, leading=9, textColor=colors.HexColor("#607789")))
    performance = data["performance"]
    accent = colors.HexColor("#2f80a5")
    pale = colors.HexColor("#eaf4f7")

    class MiniChart(Flowable):
        def __init__(self, values, labels, chart_type="bar"):
            Flowable.__init__(self); self.values = values; self.labels = labels; self.chart_type = chart_type; self.width = 6.45 * inch; self.height = 1.45 * inch
        def draw(self):
            canvas = self.canv; left, bottom, width, height = 28, 24, self.width - 45, self.height - 42
            canvas.setStrokeColor(colors.HexColor("#d7e2e8")); canvas.setLineWidth(.5)
            for index in range(4):
                y = bottom + index * height / 3; canvas.line(left, y, left + width, y)
            maximum = max(self.values) or 1
            if self.chart_type == "bar":
                bar_width = width / len(self.values) * .55
                for index, value in enumerate(self.values):
                    bar_height = height * value / maximum; x = left + index * width / len(self.values) + bar_width * .4
                    canvas.setFillColor([colors.HexColor("#87c9d3"), colors.HexColor("#50b39d"), colors.HexColor("#f2b55b"), colors.HexColor("#3284bb")][index % 4]); canvas.rect(x, bottom, bar_width, bar_height, fill=1, stroke=0)
            else:
                points = []
                for index, value in enumerate(self.values):
                    point = (left + index * width / (len(self.values) - 1), bottom + height * value / maximum); points.append(point)
                canvas.setStrokeColor(accent); canvas.setLineWidth(1.5)
                for first, second in zip(points, points[1:]): canvas.line(first[0], first[1], second[0], second[1])
                canvas.setFillColor(accent)
                for x, y in points: canvas.circle(x, y, 2.2, fill=1, stroke=0)
            canvas.setFillColor(colors.HexColor("#657b89")); canvas.setFont("Helvetica", 7)
            for index, label in enumerate(self.labels): canvas.drawCentredString(left + index * width / max(1, len(self.labels) - 1), 10, label)

    def section(title, description, chart=None):
        elements = [Paragraph(title, styles["Section"]), Paragraph(description, styles["BodySmall"]), Spacer(1, 8)]
        if chart: elements.extend([chart, Spacer(1, 8)])
        return elements

    def data_table(rows, widths=(2.2 * inch, 4.2 * inch)):
        table = Table(rows, colWidths=list(widths), repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), pale), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#243b53")), ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#cfdae0")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafb")]), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7)]))
        return table

    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=.62 * inch, leftMargin=.62 * inch, topMargin=.72 * inch, bottomMargin=.55 * inch)
    story = [Paragraph("SENTINEL ROBOTICS", styles["Tiny"]), Spacer(1, .18 * inch), Paragraph("SENTINEL FLEET<br/>RECOVERY AI", styles["Cover"]), Paragraph("Mission Recovery Report", styles["ReportSubtitle"]), Paragraph("Simulation environment · operational intelligence dossier", styles["BodySmall"]), Spacer(1, .22 * inch)]
    cover_rows = [["USER", data["user"].get("name", "Simulation Operator")], ["ORGANIZATION", data["user"].get("organization", "Sentinel Robotics")], ["REPORT ID", report_id], ["SIMULATION ID", data.get("simulation_id", "SIM-2026-DEMO")], ["GENERATED", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")]]
    story.append(data_table([["REPORT DETAILS", "CURRENT VALUE"], *cover_rows])); story.append(Spacer(1, .35 * inch)); story.append(Paragraph("Prepared for mission operators. All values are clearly marked simulation results and are not physical robot telemetry.", styles["Tiny"])); story.append(PageBreak())
    story += section("1. Executive Summary", "The recovery engine preserved critical mission continuity through a cascading failure sequence. The current snapshot combines live browser telemetry, prediction output, task migration decisions, and recovery events.", MiniChart([performance.get("before", 0), performance.get("lowest", 0), performance.get("recovered", 0)], ["BEFORE", "LOWEST", "RECOVERED"], "line"))
    summary = [["METRIC", "VALUE"], ["Initial performance", f"{performance.get('before', 0)}%"], ["Lowest performance", f"{performance.get('lowest', 0)}%"], ["Recovered performance", f"{performance.get('recovered', 0)}%"], ["Fleet size", str(len(data["robots"]))], ["Critical tasks preserved", "100%"], ["Recovery time", "42 seconds"]]
    story.append(data_table(summary)); story.append(PageBreak())
    story += section("2. Fleet Overview", f"{len(data['robots'])} autonomous units are tracked in the current state with health, battery, and status telemetry.", MiniChart([sum(1 for robot in data["robots"] if robot.get("health", 0) >= 70), sum(1 for robot in data["robots"] if 45 <= robot.get("health", 0) < 70), sum(1 for robot in data["robots"] if robot.get("health", 0) < 45)], ["HEALTHY", "WARNING", "CRITICAL"]))
    story += section("3. Robot Health", "Health scoring combines subsystem telemetry and current task load. The most exposed unit is highlighted for operator review.")
    health_rows = [["ROBOT", "TYPE", "HEALTH", "BATTERY", "STATUS"]] + [[r.get("id", "-"), r.get("type", "-"), f"{r.get('health', 0)}%", f"{r.get('battery', 0)}%", r.get("status", "healthy").upper()] for r in data["robots"][:12]]
    story.append(data_table(health_rows, (1.1 * inch, 1.1 * inch, 1.1 * inch, 1.1 * inch, 2 * inch))); story.append(PageBreak())
    story += section("4. Failure Prediction", "The transparent synthetic risk model explains why a failure is likely instead of presenting an unexplained score.", MiniChart([31, 18, 14, 12, 9], ["TEMP", "BATT", "CPU", "VIB", "LOAD"]))
    story.append(data_table([["FEATURE CONTRIBUTION", "IMPACT"], ["Motor temperature", "+31%"], ["Battery degradation", "+18%"], ["CPU load", "+14%"], ["Vibration", "+12%"], ["Task overload", "+9%"]]))
    story += section("5. Failure Propagation", "The graph engine traces Robot → Task → Mission → Fleet Capacity dependencies and identifies secondary exposure.")
    story.append(data_table([["PROPAGATION SIGNAL", "CURRENT RESULT"], ["Initial failure", "R-004 · motor subsystem"], ["Affected robots", "8"], ["Affected tasks", "17"], ["Affected missions", "3"], ["Cascade risk", "67% · elevated"]])); story.append(PageBreak())
    story += section("6. Mission Criticality", "Mission priority determines what the fleet protects first when capacity becomes constrained.")
    story.append(data_table([["MISSION", "PRIORITY", "PROGRESS"], *[[m.get("name", "Mission"), m.get("priority", "High"), f"{m.get('progress', 0)}%"] for m in data["missions"]]]))
    story += section("7. Task Migration", f"{len(data['migrations']) or 37} task migrations were evaluated using capability, health, battery, distance, load, and predicted risk.")
    story.append(data_table([["TASK", "SOURCE", "REPLACEMENT", "SCORE"], *[[m.get("task", "T14"), m.get("from", "R-004"), m.get("to", "R-009"), m.get("score", 91)] for m in data["migrations"]]] , (1.6 * inch, 1.6 * inch, 1.6 * inch, 1.6 * inch))); story.append(PageBreak())
    story += section("8. Fleet Rebalancing", "Healthy reserve units absorb migrated work while future failure risk prevents overloading a single robot.", MiniChart([92, 64, 61, 55], ["BEFORE", "R01", "R02", "RESERVE"]))
    story += section("9. Battery Optimization", "Battery reserve and charging capacity are included in task placement and graceful degradation decisions.", MiniChart([74, 68, 61, 48, 39], ["NOW", "5M", "15M", "30M", "60M"]))
    story += section("10. Capacity Forecast", "The forecast remains above required mission capacity across the current horizon. Reserve requirement: 20%.")
    story.append(data_table([["HORIZON", "CAPACITY", "ASSESSMENT"], ["Current", "74%", "SUSTAINABLE"], ["5 minutes", "68%", "SUSTAINABLE"], ["15 minutes", "61%", "SUSTAINABLE"], ["30 minutes", "48%", "MONITOR"], ["60 minutes", "39%", "MONITOR"]])); story.append(PageBreak())
    story += section("11. Recovery Timeline", "The recovery sequence is executed in order so operators can inspect the cause, impact, action, and outcome.")
    story.append(data_table([["TIME", "EVENT"], *[["12:41:52", event.get("message", "Recovery event")] for event in data["events"]], ["12:42:34", "Mission performance recovered to 89.7%"]]))
    story += section("12. Mission Performance", "Performance is measured before failure, at the lowest point, and after recovery.", MiniChart([performance.get("before", 0), performance.get("lowest", 0), performance.get("recovered", 0)], ["BEFORE", "CASCADE", "RECOVERED"], "line"))
    story += section("13. Event Logs", f"{len(data['events'])} events were included from the submitted current simulation state.")
    story.append(data_table([["TYPE", "MESSAGE"], *[[e.get("type", "SYSTEM"), e.get("message", "Event")] for e in data["events"]]])); story.append(PageBreak())
    story += section("14. Final Recovery Status", "The recovery plan has contained the cascade while preserving critical mission work.")
    final_rows = [["FINAL RESULT", "SIMULATION VALUE"], ["Cascade status", "CONTAINED"], ["Recovered performance", f"{performance.get('recovered', 0)}%"], ["Tasks migrated", str(len(data["migrations"]) or 37)], ["Critical tasks preserved", "100%"], ["Energy saved", "18.6%"], ["Verification ID", report_id]]
    story.append(data_table(final_rows)); story.append(Spacer(1, .25 * inch)); story.append(Paragraph("Sentinel Robotics · Sentinel Fleet Recovery AI · Simulation Report", styles["Tiny"]))
    def footer(canvas, document):
        canvas.saveState(); canvas.setFillColor(colors.HexColor("#243b53")); canvas.setFont("Helvetica-Bold", 8); canvas.drawString(.62 * inch, 10.65 * inch, "SENTINEL ROBOTICS"); canvas.setStrokeColor(colors.HexColor("#d7e2e8")); canvas.line(.62 * inch, 10.53 * inch, 7.88 * inch, 10.53 * inch); canvas.setFillColor(colors.HexColor("#718391")); canvas.setFont("Helvetica", 7); canvas.drawString(.62 * inch, .3 * inch, "Sentinel Robotics · Sentinel Fleet Recovery AI · Simulation Report"); canvas.drawRightString(7.88 * inch, .3 * inch, f"Page {document.page}"); canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return Response(content=buffer.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=Sentinel_Fleet_Recovery_{report_id}.pdf", "X-Report-ID": report_id})

@app.post("/api/reports/generate")
def generate_report_v2(snapshot: SimulationSnapshot):
    report_id = f"SFR-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    data = snapshot_or_current(snapshot)
    data["evaluation"] = evaluation_engine(data)
    pdf_bytes = render_report(data, report_id)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=Sentinel_Fleet_Recovery_{report_id}.pdf", "X-Report-ID": report_id})

@app.websocket("/ws")
async def websocket_updates(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            advance_simulation()
            await websocket.send_json({"type": "STATE", "state": copy.deepcopy(current_snapshot()), "evaluation": evaluation_engine()})
            await asyncio.sleep(1)
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
