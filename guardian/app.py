"""Small, in-memory web API for the Guardian simulator."""
import json
import re
import secrets
from collections import OrderedDict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import load_config, request_live
from .access import LiveDenied, SESSION_SECONDS, live_available, require_live, unlocked, unlock
from .models import Level, Turn
from .notify import send_family_alert, telegram_settings
from .pipeline import CallSession


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ROOT / "scenarios"
STATIC_DIR = Path(__file__).resolve().parent / "static"
EXAMPLES_PATH = ROOT / "messages" / "examples.json"
MAX_SESSIONS = 200
MAX_TURNS = 100

app = FastAPI(title="Guardian")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# OrderedDict makes eviction deterministic and bounds this demo process's memory.
sessions: OrderedDict[str, CallSession] = OrderedDict()


class CreateSessionRequest(BaseModel):
    scenario_id: str | None = None
    live: bool | None = None


class HistoryTurn(BaseModel):
    speaker: Literal["caller", "elder"]
    text: str = Field(min_length=1, max_length=2000)
    t: float = Field(ge=0)


class TurnRequest(HistoryTurn):
    live: bool | None = None
    history: list[HistoryTurn] = Field(default_factory=list, max_length=MAX_TURNS)


class MessageRequest(BaseModel):
    live: bool | None = None
    text: str = Field(min_length=1, max_length=2000)


@app.exception_handler(LiveDenied)
async def live_denied_handler(request: Request, exc: LiveDenied):
    return JSONResponse({"error": exc.error}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    # FastAPI's default error includes raw inputs, including passwords or transcripts.
    return JSONResponse({"error": "invalid_request"}, status_code=422)


@app.middleware("http")
async def offline_unless_authorized(request: Request, call_next):
    marker = request_live.set(False)
    try:
        return await call_next(request)
    finally:
        request_live.reset(marker)


@app.get("/api/config")
def public_config(request: Request):
    return {"live_available": live_available(), "live_unlocked": unlocked(request)}


@app.post("/api/unlock")
async def unlock_live(request: Request):
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        payload = {}
    token = unlock(request, payload.get("code") if isinstance(payload, dict) else None)
    response = JSONResponse({"ok": True})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip().lower() == "https"
    response.set_cookie("live_session", token, httponly=True, samesite="lax", secure=secure, max_age=SESSION_SECONDS)
    return response


def wants_live(value: bool | None) -> bool:
    return value if value is not None else load_config().get("LIVE", "0") == "1"


def load_scenarios() -> list[dict]:
    """Load public scenario data without retaining mutable request state."""
    result = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        result.append({
            "id": raw["id"],
            "title": raw["id"].replace("_", " ").title(),
            "expected": raw["expected"],
            "turns": raw["turns"],
        })
    return result


def load_message_examples() -> list[dict]:
    if not EXAMPLES_PATH.exists():
        return []
    return json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))


def create_session() -> str:
    while True:
        session_id = secrets.token_urlsafe(24)
        if session_id not in sessions:
            break
    store_session(session_id, CallSession())
    return session_id


def store_session(session_id: str, session: CallSession) -> None:
    sessions[session_id] = session
    while len(sessions) > MAX_SESSIONS:
        sessions.popitem(last=False)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/health")
def health(request: Request) -> dict[str, bool | str]:
    return {"ok": True, "live": unlocked(request), "family_alert": "telegram" if telegram_settings() else "off", "model": "nvidia/nemotron-3-super-120b-a12b", "provider": "Nebius Token Factory"}


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    return load_scenarios()


@app.get("/api/message-examples")
def message_examples() -> list[dict]:
    return load_message_examples()


@app.post("/api/sessions")
def start_session(request: CreateSessionRequest, http: Request) -> dict[str, str]:
    if request.scenario_id is not None and request.scenario_id not in {item["id"] for item in load_scenarios()}:
        raise HTTPException(status_code=404, detail="Unknown scenario")
    live = request.scenario_id is None and wants_live(request.live)
    if live:
        require_live(http)
    session_id = create_session()
    sessions[session_id].live_mode = live
    return {"session_id": session_id}


@app.post("/api/sessions/{session_id}/turns")
def add_turn(session_id: str, request: TurnRequest, http: Request) -> dict:
    session = sessions.get(session_id)
    live = getattr(session, "live_mode", wants_live(request.live))
    if live:
        require_live(http)
    request_live.set(live)
    if session is None:
        if live:
            raise HTTPException(status_code=404, detail="Unknown session")
        if re.fullmatch(r"[A-Za-z0-9_-]{32}", session_id) is None:
            raise HTTPException(status_code=404, detail="Unknown session")
        if len(request.history) >= MAX_TURNS:
            raise HTTPException(status_code=422, detail="Session turn limit reached")
        session = CallSession()
        session.live_mode = live
        for turn in request.history:
            session.on_turn(Turn(**turn.model_dump()))
        # The family already heard about this call before the instance forgot it.
        session.family_alerted = session.last_verdict.level == Level.SCAM
        store_session(session_id, session)
    if len(session.transcript) >= MAX_TURNS:
        raise HTTPException(status_code=422, detail="Session turn limit reached")
    if live and request.speaker == "caller":
        require_live(http, charge=True)
    verdict = session.on_turn(Turn(**request.model_dump(exclude={"history", "live"})))
    response = {"turn_index": len(session.transcript) - 1, "verdict": verdict.model_dump(mode="json")}
    if verdict.level == Level.SCAM and not session.family_alerted:
        session.family_alerted = True
        response["family_alert"] = send_family_alert(verdict)
    return response


@app.post("/api/message")
def analyse_message(request: MessageRequest, http: Request) -> dict:
    sample = any(item["text"] == request.text for item in load_message_examples())
    live = not sample and wants_live(request.live)
    if live:
        require_live(http, charge=True)
    request_live.set(live)
    session = CallSession()
    verdict = session.on_turn(Turn(speaker="caller", text=request.text, t=0))
    response: dict = {"verdict": verdict.model_dump(mode="json")}
    if verdict.signals_source == "rules":
        response["note"] = "No recorded Nemotron answer for this text, so Guardian used its offline rule-based detector (no AI model). Sources are real recorded Tavily results; the advice is a fixed template."
    if verdict.level == Level.SCAM:
        response["family_alert"] = send_family_alert(verdict, "message")
    return response
