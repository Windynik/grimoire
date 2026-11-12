import json
import socket

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.core.phone as phone
from backend.api.dependencies import get_phone_access
from backend.core.phone import COOKIE, PhoneAccess, PhoneGate, device_name
from main import app as main_app

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"


def access(tmp_path, enabled=True, port=8135):
    state = PhoneAccess(state_file=tmp_path / "phone.json", port=port)
    state._state["enabled"] = enabled
    return state


def inner_app():
    app = FastAPI()

    @app.get("/")
    def home():
        return {"page": "home"}

    @app.get("/api/phone")
    def settings():
        return {"secret": "settings"}

    return app


# ---- pairing ---------------------------------------------------------------------


def test_a_code_pairs_one_device_once_and_the_file_keeps_only_a_hash(tmp_path):
    state = access(tmp_path)
    code = state.new_pair_code()
    token = state.pair(code.lower(), IPHONE)
    assert token and state.is_paired(token)
    assert state.pair(code, IPHONE) is None  # used up
    saved = json.loads((tmp_path / "phone.json").read_text())
    assert token not in json.dumps(saved)
    assert saved["devices"][0]["name"] == "iPhone"
    assert [d["name"] for d in state.devices()] == ["iPhone"]
    assert "token" not in state.devices()[0]


def test_wrong_codes_end_the_live_code(tmp_path):
    state = access(tmp_path)
    code = state.new_pair_code()
    for _ in range(phone.MAX_PAIR_TRIES):
        assert state.pair("WRONG1") is None
    assert state.pair(code) is None


def test_a_code_expires(tmp_path, monkeypatch):
    state = access(tmp_path)
    code = state.new_pair_code()
    now = phone.time.time()
    monkeypatch.setattr(phone.time, "time", lambda: now + phone.PAIR_SECONDS + 1)
    assert state.pair(code) is None
    assert state.pair_info() is None


def test_nothing_pairs_or_passes_while_phone_access_is_off(tmp_path):
    state = access(tmp_path)
    token = state.pair(state.new_pair_code())
    state._state["enabled"] = False
    assert not state.is_paired(token)
    assert state.pair(state.new_pair_code()) is None


def test_forget_one_or_every_device(tmp_path):
    state = access(tmp_path)
    first = state.pair(state.new_pair_code(), IPHONE)
    second = state.pair(state.new_pair_code(), "Android")
    state.forget(state.devices()[0]["id"])
    assert not state.is_paired(first) and state.is_paired(second)
    state.forget()
    assert state.devices() == [] and not state.is_paired(second)


def test_device_names():
    assert device_name(IPHONE) == "iPhone"
    assert device_name("Linux; Android 14") == "Android phone"
    assert device_name("") == "Device"


# ---- the gate --------------------------------------------------------------------


def test_the_gate_lets_only_paired_phones_in(tmp_path):
    state = access(tmp_path)
    client = TestClient(PhoneGate(inner_app(), state))
    locked = client.get("/")
    assert locked.status_code == 401 and "not paired" in locked.text
    assert client.get("/api/decks").json()["detail"].startswith("This phone is not paired")
    bad = client.get("/pair?code=NOPE12", follow_redirects=False)
    assert bad.status_code == 403
    paired = client.get("/pair?code=%s" % state.new_pair_code(), follow_redirects=False,
                        headers={"user-agent": IPHONE})
    assert paired.status_code == 303 and paired.headers["location"] == "/"
    assert "HttpOnly" in paired.headers["set-cookie"]
    token = client.cookies.get(COOKIE)
    assert state.is_paired(token)
    assert client.get("/").json() == {"page": "home"}


def test_the_phone_settings_never_answer_on_the_phone_listener(tmp_path):
    state = access(tmp_path)
    token = state.pair(state.new_pair_code())
    client = TestClient(PhoneGate(inner_app(), state), cookies={COOKIE: token})
    assert client.get("/").status_code == 200
    blocked = client.get("/api/phone")
    assert blocked.status_code == 401 and "secret" not in blocked.text


# ---- the routes on this machine ----------------------------------------------------


@pytest.fixture
def phone_env(tmp_path, monkeypatch):
    state = access(tmp_path, enabled=False)
    calls = []

    async def fake_start(app):
        calls.append("start")
        state._task = None

    async def fake_stop():
        calls.append("stop")

    monkeypatch.setattr(state, "start", fake_start)
    monkeypatch.setattr(state, "stop", fake_stop)
    monkeypatch.setattr(PhoneAccess, "running", property(lambda self: self.enabled))
    monkeypatch.setattr(phone, "lan_addresses", lambda: ["192.168.1.20", "mac.local"])
    main_app.dependency_overrides[get_phone_access] = lambda: state
    yield state, calls
    main_app.dependency_overrides.pop(get_phone_access, None)


def test_turning_phone_access_on_makes_a_code_and_a_qr(phone_env):
    state, calls = phone_env
    client = TestClient(main_app)
    assert client.get("/api/phone").json()["enabled"] is False
    on = client.post("/api/phone", json={"enabled": True}).json()
    assert calls == ["start"] and on["enabled"] is True
    assert on["urls"] == ["http://192.168.1.20:8135", "http://mac.local:8135"]
    assert on["pair"]["url"] == "http://192.168.1.20:8135/pair?code=" + on["pair"]["code"]
    qr = client.get("/api/phone/qr.svg")
    assert qr.status_code == 200 and qr.text.startswith("<svg")
    # A standalone image needs the namespace, or the browser shows nothing.
    assert 'xmlns="http://www.w3.org/2000/svg"' in qr.text
    off = client.post("/api/phone", json={"enabled": False}).json()
    assert calls == ["start", "stop"] and off["pair"] is None
    assert client.get("/api/phone/qr.svg").status_code == 404
    assert client.post("/api/phone/pair-code").status_code == 409


def test_forgetting_devices_through_the_routes(phone_env):
    state, _ = phone_env
    state._state["enabled"] = True
    state.pair(state.new_pair_code(), IPHONE)
    client = TestClient(main_app)
    device = client.get("/api/phone").json()["devices"][0]
    assert client.delete("/api/phone/devices/%s" % device["id"]).json()["devices"] == []
    assert client.delete("/api/phone/devices/nope").status_code == 404


# ---- a real phone listener ---------------------------------------------------------


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.asyncio
async def test_the_phone_listener_starts_gates_and_stops(tmp_path):
    state = access(tmp_path, port=free_port())
    await state.start(inner_app())
    try:
        assert state.running and state.last_error is None
        async with httpx.AsyncClient(base_url="http://127.0.0.1:%d" % state.port,
                                     follow_redirects=True) as client:
            assert (await client.get("/")).status_code == 401
            code = state.new_pair_code()
            paired = await client.get("/pair?code=" + code)
            assert paired.status_code == 200 and paired.json() == {"page": "home"}
    finally:
        await state.stop()
    assert not state.running


@pytest.mark.asyncio
async def test_a_port_in_use_is_reported(tmp_path):
    with socket.socket() as taken:
        taken.bind(("0.0.0.0", 0))
        taken.listen()
        state = access(tmp_path, port=taken.getsockname()[1])
        await state.start(inner_app())
        assert not state.running
        assert "in use" in state.last_error


def test_firewall_note_reads_the_macos_firewall(monkeypatch):
    class Done:
        def __init__(self, out):
            self.stdout = out

    monkeypatch.setattr(phone.sys, "platform", "darwin")
    monkeypatch.setattr(phone.os.path, "exists", lambda path: True)
    monkeypatch.setattr(phone.subprocess, "run", lambda *a, **k: Done(
        "Incoming connection to /opt/py/python3.13 is blocked."))
    note = phone.firewall_note("/opt/py/python3.13")
    assert "blocks incoming connections to Python (/opt/py/python3.13)" in note
    monkeypatch.setattr(phone.subprocess, "run", lambda *a, **k: Done(
        "Incoming connection to /opt/py/python3.13 is permitted."))
    assert phone.firewall_note("/opt/py/python3.13") is None
    monkeypatch.setattr(phone.sys, "platform", "linux")
    assert phone.firewall_note("/opt/py/python3.13") is None
