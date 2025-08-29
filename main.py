from fastapi import FastAPI, Request, Form, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
import asyncio
import random
import time

app = FastAPI(title="DemoCar SOVD Training Server", version="0.4")

# console.sovd.io ve yerel web arayüz
origins = [
    "https://console.sovd.io",
    "http://localhost",
    "http://127.0.0.1"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# 0) SIMÜLE ARAÇ DURUMU + YARDIMCI FONKSİYONLAR
# ------------------------------------------------------------------------------

class Battery(BaseModel):
    voltage: float = 12.6
    status: str = "charging"

class VehicleState(BaseModel):
    engine: str = "off"                # "off" | "running"
    brake: str = "released"            # "released" | "applied"
    rpm: int = 0
    temperature: float = 75.0
    speed: int = 0
    fuel_level: float = 100.0          # %
    lights: str = "off"
    doors_locked: bool = True
    battery: Battery = Battery()

vehicle_state = VehicleState()

def update_vehicle_state():
    """Motor çalışıyorsa gerçekçi dalgalanmalar oluştur."""
    if vehicle_state.engine == "running":
        vehicle_state.rpm = max(650, min(vehicle_state.rpm + random.randint(-200, 350), 6000))
        vehicle_state.temperature = round(random.uniform(80, 105), 1)
        vehicle_state.battery.voltage = round(random.uniform(12.6, 14.6), 2)

        if vehicle_state.brake == "released":
            vehicle_state.speed = min(vehicle_state.speed + random.randint(0, 6), 180)
        else:
            vehicle_state.speed = max(vehicle_state.speed - random.randint(5, 15), 0)

        vehicle_state.fuel_level = max(vehicle_state.fuel_level - 0.02, 0.0)
    else:
        vehicle_state.rpm = 0
        vehicle_state.speed = max(vehicle_state.speed - 2, 0)

# ------------------------------------------------------------------------------
# 1) SOVD-vari ENTITY MODELİ (çok basit)
# ------------------------------------------------------------------------------

# Entity ağacı: vehicle -> engine, battery, brakes, lights, doors
ENTITIES = {
    "vehicle": {"type": "Vehicle", "name": "DemoCar", "children": ["engine", "battery", "brakes", "lights", "doors"]},
    "engine": {"type": "Component", "name": "ICE", "children": []},
    "battery": {"type": "Component", "name": "12V Battery", "children": []},
    "brakes": {"type": "Component", "name": "ServiceBrake", "children": []},
    "lights": {"type": "Component", "name": "ExteriorLights", "children": []},
    "doors": {"type": "Component", "name": "DoorLock", "children": []},
}

# Her entity için data-resources
DATA_RESOURCES = {
    "vehicle": {
        "speed": {"unit": "km/h", "rw": "r"},
        "fuel_level": {"unit": "%", "rw": "r"},
        "temperature": {"unit": "°C", "rw": "r"},
        "mode": {"enum": ["drive", "service", "transport"], "rw": "rw", "value": "drive"},
    },
    "engine": {
        "rpm": {"unit": "rpm", "rw": "r"},
        "state": {"enum": ["off", "running"], "rw": "r"},
    },
    "battery": {
        "voltage": {"unit": "V", "rw": "r"},
        "status": {"enum": ["charging", "discharging"], "rw": "r"},
    },
    "brakes": {
        "brake": {"enum": ["applied", "released"], "rw": "rw", "value": "released"},
    },
    "lights": {
        "lights": {"enum": ["off", "on"], "rw": "rw", "value": "off"},
    },
    "doors": {
        "doors_locked": {"type": "bool", "rw": "rw", "value": True},
    },
}

# Basit fault listesi (dtc benzeri)
FAULTS: Dict[str, List[Dict[str, Any]]] = {
    "vehicle": [],
    "engine": [{"id": "P0420", "text": "Catalyst System Efficiency Below Threshold", "status": "stored"}],
    "battery": [],
    "brakes": [],
    "lights": [{"id": "B1234", "text": "Low Beam Left Failure", "status": "active"}],
    "doors": [],
}

# Operations: uzun süren işleri simüle edelim
OPERATIONS: Dict[str, Dict[str, Any]] = {}   # op_id -> {entity, name, status, started_at, progress}
_op_counter = 0

def new_op(entity_id: str, name: str) -> str:
    global _op_counter
    _op_counter += 1
    op_id = f"op-{_op_counter}"
    OPERATIONS[op_id] = {"entity": entity_id, "name": name, "status": "running", "progress": 0, "started_at": time.time()}
    return op_id

async def simulate_operation(op_id: str, steps: int = 10, delay_s: float = 0.3):
    for i in range(steps):
        await asyncio.sleep(delay_s)
        if op_id not in OPERATIONS or OPERATIONS[op_id]["status"] == "stopped":
            return
        OPERATIONS[op_id]["progress"] = int((i + 1) * 100 / steps)
    OPERATIONS[op_id]["status"] = "completed"

# Locks: yazma/tehlikeli işler için kilit
LOCKS: Dict[str, Dict[str, Any]] = {}  # entity_id -> {"token": str, "expires": float}

def require_lock(entity_id: str, token: Optional[str]):
    current = LOCKS.get(entity_id)
    if not current or current["expires"] < time.time() or current["token"] != token:
        raise HTTPException(status_code=423, detail="Lock required or invalid/expired lock")

# ------------------------------------------------------------------------------
# 2) BASİT BİLGİ ENDPOINTLERİ (SOVD’ye benzer)
# ------------------------------------------------------------------------------

@app.get("/about")
def about():
    return {"name": "DemoCar", "version": "0.4", "description": "SOVD training server with realistic simulation"}

@app.get("/sovd/v1/entities")
def list_entities():
    """Kök altındaki tüm entity’leri döndür."""
    return {"root": "vehicle", "entities": ENTITIES}

@app.get("/sovd/v1/entities/{entity_id}")
def get_entity(entity_id: str):
    if entity_id not in ENTITIES:
        raise HTTPException(404, "entity not found")
    return {"id": entity_id, **ENTITIES[entity_id]}

# ------------------------------------------------------------------------------
# 3) DATA-RESOURCE READ/WRITE (GET/PUT/PATCH)
# ------------------------------------------------------------------------------

@app.get("/sovd/v1/entities/{entity_id}/data-resources")
def list_data_resources(entity_id: str):
    if entity_id not in DATA_RESOURCES:
        raise HTTPException(404, "entity not found")
    update_vehicle_state()
    # canlı değerleri state’den bind edelim
    live = {
        "vehicle": {"speed": vehicle_state.speed, "fuel_level": vehicle_state.fuel_level,
                    "temperature": vehicle_state.temperature, "mode": DATA_RESOURCES["vehicle"]["mode"]["value"]},
        "engine": {"rpm": vehicle_state.rpm, "state": vehicle_state.engine},
        "battery": {"voltage": vehicle_state.battery.voltage, "status": vehicle_state.battery.status},
        "brakes": {"brake": vehicle_state.brake},
        "lights": {"lights": vehicle_state.lights},
        "doors": {"doors_locked": vehicle_state.doors_locked},
    }.get(entity_id, {})
    return {"resources": DATA_RESOURCES[entity_id], "values": live}

@app.get("/sovd/v1/entities/{entity_id}/data/{name}")
def read_single(entity_id: str, name: str):
    if entity_id not in DATA_RESOURCES or name not in DATA_RESOURCES[entity_id]:
        raise HTTPException(404, "resource not found")
    # canlı değer üret
    list_data_resources(entity_id)  # update
    values = {
        "vehicle": {"speed": vehicle_state.speed, "fuel_level": vehicle_state.fuel_level,
                    "temperature": vehicle_state.temperature, "mode": DATA_RESOURCES["vehicle"]["mode"]["value"]},
        "engine": {"rpm": vehicle_state.rpm, "state": vehicle_state.engine},
        "battery": {"voltage": vehicle_state.battery.voltage, "status": vehicle_state.battery.status},
        "brakes": {"brake": vehicle_state.brake},
        "lights": {"lights": vehicle_state.lights},
        "doors": {"doors_locked": vehicle_state.doors_locked},
    }[entity_id]
    return {"name": name, "value": values[name]}

class WriteValue(BaseModel):
    value: Any
    lockToken: Optional[str] = None

@app.put("/sovd/v1/entities/{entity_id}/data/{name}")
def write_single(entity_id: str, name: str, payload: WriteValue):
    """Yazılabilir bir data-resource’u PUT ile ayarla (tam güncelleme)."""
    if entity_id not in DATA_RESOURCES or name not in DATA_RESOURCES[entity_id]:
        raise HTTPException(404, "resource not found")
    meta = DATA_RESOURCES[entity_id][name]
    if "w" not in meta.get("rw", ""):
        raise HTTPException(405, "resource is read-only")
    # kilit zorunlu kılalım (gerçekçi)
    require_lock(entity_id, payload.lockToken)

    # değer ata + canlı state’e uygula
    meta["value"] = payload.value
    apply_to_live_state(entity_id, name, payload.value)
    return {"status": "ok", "name": name, "value": payload.value}

@app.patch("/sovd/v1/entities/{entity_id}/data/{name}")
def patch_single(entity_id: str, name: str, payload: WriteValue):
    """PATCH ile kısmi güncelleme (bizim örnekte PUT ile aynı davranır)."""
    return write_single(entity_id, name, payload)

def apply_to_live_state(entity_id: str, name: str, value: Any):
    if entity_id == "vehicle" and name == "mode":
        DATA_RESOURCES["vehicle"]["mode"]["value"] = value
    if entity_id == "brakes" and name == "brake":
        vehicle_state.brake = value
    if entity_id == "lights" and name == "lights":
        vehicle_state.lights = value
    if entity_id == "doors" and name == "doors_locked":
        vehicle_state.doors_locked = bool(value)

# ------------------------------------------------------------------------------
# 4) FAULT HANDLING (GET/DELETE)
# ------------------------------------------------------------------------------

@app.get("/sovd/v1/entities/{entity_id}/faults")
def list_faults(entity_id: str):
    if entity_id not in ENTITIES:
        raise HTTPException(404, "entity not found")
    # ufak olasılıkla yeni arıza üretelim ki dinamik olsun
    if entity_id == "engine" and random.random() < 0.02:
        FAULTS["engine"].append({"id": "P0301", "text": "Cylinder 1 Misfire Detected", "status": "active"})
    return {"faults": FAULTS.get(entity_id, [])}

@app.delete("/sovd/v1/entities/{entity_id}/faults")
def clear_faults(entity_id: str, lockToken: Optional[str] = None):
    require_lock(entity_id, lockToken)
    FAULTS[entity_id] = []
    return {"status": "deleted"}

# ------------------------------------------------------------------------------
# 5) OPERATIONS (POST başlat, GET status, DELETE stop)
# ------------------------------------------------------------------------------

class StartOperation(BaseModel):
    name: str = Field(..., examples=["startEngine", "stopEngine", "flashLights"])
    params: Dict[str, Any] = {}
    lockToken: Optional[str] = None

@app.get("/sovd/v1/entities/{entity_id}/operations")
def list_operations(entity_id: str):
    items = [{"id": op_id, **info} for op_id, info in OPERATIONS.items() if info["entity"] == entity_id]
    return {"operations": items}

@app.post("/sovd/v1/entities/{entity_id}/operations")
async def start_operation(entity_id: str, spec: StartOperation):
    # bazı op'lar lock gerektirsin
    if spec.name in {"resetECU", "flashLights", "setSpeedLimiter"}:
        require_lock(entity_id, spec.lockToken)

    # gerçek etkiler
    if spec.name == "startEngine":
        vehicle_state.engine = "running"
    elif spec.name == "stopEngine":
        vehicle_state.engine = "off"
    elif spec.name == "flashLights":
        # kısa bir göz kırpma simülasyonu (arkaplan task)
        pass
    elif spec.name == "setSpeedLimiter":
        # params: {"limit": 120}
        limit = int(spec.params.get("limit", 120))
        DATA_RESOURCES["vehicle"]["speed_limit"] = {"unit": "km/h", "rw": "rw", "value": limit}
    elif spec.name == "resetECU":
        # fault’ları temizle vb.
        for k in FAULTS:
            FAULTS[k] = []

    op_id = new_op(entity_id, spec.name)
    task = asyncio.create_task(simulate_operation(op_id))
    # flashLights ek etkisi
    if spec.name == "flashLights":
        async def blink():
            on = vehicle_state.lights
            for _ in range(6):
                vehicle_state.lights = "on"
                await asyncio.sleep(0.2)
                vehicle_state.lights = "off"
                await asyncio.sleep(0.2)
            vehicle_state.lights = on
        asyncio.create_task(blink())
    return {"opId": op_id, "status": "running"}

@app.get("/sovd/v1/operations/{op_id}")
def get_operation(op_id: str):
    if op_id not in OPERATIONS:
        raise HTTPException(404, "op not found")
    return OPERATIONS[op_id]

@app.delete("/sovd/v1/operations/{op_id}")
def stop_operation(op_id: str, lockToken: Optional[str] = None):
    op = OPERATIONS.get(op_id)
    if not op:
        raise HTTPException(404, "op not found")
    require_lock(op["entity"], lockToken)
    op["status"] = "stopped"
    return {"status": "stopped", "opId": op_id}

# ------------------------------------------------------------------------------
# 6) MODES (GET/POST) – entity state makarası
# ------------------------------------------------------------------------------

@app.get("/sovd/v1/entities/{entity_id}/modes")
def get_modes(entity_id: str):
    allowed = DATA_RESOURCES["vehicle"]["mode"]["enum"] if entity_id == "vehicle" else ["default"]
    current = DATA_RESOURCES["vehicle"]["mode"]["value"] if entity_id == "vehicle" else "default"
    return {"supported": allowed, "current": current}

class SetMode(BaseModel):
    mode: str
    lockToken: Optional[str] = None

@app.post("/sovd/v1/entities/{entity_id}/modes")
def set_mode(entity_id: str, body: SetMode):
    if entity_id != "vehicle":
        raise HTTPException(400, "only vehicle mode is supported in demo")
    require_lock(entity_id, body.lockToken)
    if body.mode not in DATA_RESOURCES["vehicle"]["mode"]["enum"]:
        raise HTTPException(400, "unsupported mode")
    DATA_RESOURCES["vehicle"]["mode"]["value"] = body.mode
    return {"status": "ok", "current": body.mode}

# ------------------------------------------------------------------------------
# 7) LOCKS (POST acquire, GET list, DELETE release)
# ------------------------------------------------------------------------------

class AcquireLock(BaseModel):
    ttlSec: int = 30

@app.post("/sovd/v1/entities/{entity_id}/locks")
def acquire_lock(entity_id: str, body: AcquireLock):
    token = f"lock-{random.randint(100000, 999999)}"
    LOCKS[entity_id] = {"token": token, "expires": time.time() + body.ttlSec}
    return {"entity": entity_id, "lockToken": token, "expiresIn": body.ttlSec}

@app.get("/sovd/v1/entities/{entity_id}/locks")
def list_locks(entity_id: str):
    lock = LOCKS.get(entity_id)
    if not lock or lock["expires"] < time.time():
        return {"locks": []}
    return {"locks": [{"token": lock["token"], "expiresIn": int(lock["expires"] - time.time())}]}

@app.delete("/sovd/v1/entities/{entity_id}/locks")
def release_lock(entity_id: str, lockToken: Optional[str] = None):
    require_lock(entity_id, lockToken)
    LOCKS.pop(entity_id, None)
    return {"status": "released"}

# ------------------------------------------------------------------------------
# 8) TÜM HTTP METODLARI İÇİN DEMO ROUTE’LAR (HEAD/OPTIONS/TRACE/CONNECT/CUSTOM)
# ------------------------------------------------------------------------------

# HEAD: FastAPI GET ile otomatik gelir; ama göstermek için özel bir endpoint ekleyelim
@app.head("/debug/ping")
def debug_head():
    # HEAD body dönmez; status ve header yeter
    return PlainTextResponse(content="", status_code=204)

# OPTIONS: Hangi metodlar var? (CORS zaten ekler ama biz de gösterebiliriz)
@app.options("/debug/ping")
def debug_options():
    hdrs = {"Allow": "GET,POST,PUT,PATCH,DELETE,HEAD,OPTIONS,TRACE,CONNECT,CUSTOM"}
    return PlainTextResponse(content="", headers=hdrs)

# TRACE/CONNECT/CUSTOM gibi default dışı metodları tek handler ile ele alalım
async def debug_echo(request: Request):
    method = request.method
    body = (await request.body() or b"").decode(errors="ignore")
    info = {
        "method": method,
        "path": request.url.path,
        "query": dict(request.query_params),
        "headers": {k: v for k, v in request.headers.items()},
        "body": body,
        "note": "TRACE returns what we received; CONNECT not supported in REST, but echoed for education; CUSTOM shows non-standard method handling."
    }
    # CONNECT için 501 de dönebilirdik; eğitim için echo yapıyoruz
    return JSONResponse(info)

# Starlette/FastAPI unknown method kabul edebiliyor -> manuel route ekleyelim
app.add_api_route("/debug/echo", debug_echo, methods=["TRACE", "CONNECT", "CUSTOM"])

# ------------------------------------------------------------------------------
# 9) BASİT WEB ARAYÜZ (tek sayfa, dark, yeni sekme yok)
# ------------------------------------------------------------------------------

DASHBOARD = """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>DemoCar – SOVD Training</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  :root { --bg:#0b0f14; --panel:#121821; --accent:#4ade80; --muted:#9aa4b2; --danger:#ef4444; --warn:#f59e0b;}
  body{margin:0;background:var(--bg);color:#e5e7eb;font-family:Inter,system-ui,Arial,sans-serif}
  .wrap{max-width:1100px;margin:0 auto;padding:24px}
  h1{font-size:24px;margin:0 0 16px}
  .grid{display:grid;grid-template-columns:1.2fr 1fr;gap:16px}
  .card{background:var(--panel);border-radius:16px;padding:16px;box-shadow:0 10px 30px rgba(0,0,0,.2)}
  .row{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
  button{border:0;border-radius:10px;padding:10px 12px;cursor:pointer;background:#1f2937;color:#e5e7eb}
  button.primary{background:var(--accent);color:#0a0a0a;font-weight:600}
  button.warn{background:var(--warn);color:#111827}
  button.danger{background:var(--danger);color:white}
  pre{background:#0b1020;color:#9ae6b4;border-radius:10px;padding:12px;overflow:auto;max-height:360px}
  .pill{display:inline-block;padding:4px 10px;border-radius:9999px;background:#1f2937;color:#e5e7eb;font-size:12px}
  .muted{color:var(--muted);font-size:13px}
  .two{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  input,select{background:#0b1020;border:1px solid #1f2937;color:#e5e7eb;border-radius:10px;padding:8px}
  label{font-size:12px;color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
  <h1>🚗 DemoCar – <span class="pill">SOVD Training</span></h1>

  <div class="grid">
    <div class="card">
      <h3>Controls</h3>
      <div class="row">
        <button class="primary" onclick="startOp('vehicle','startEngine')">Start Engine</button>
        <button onclick="startOp('vehicle','stopEngine')">Stop Engine</button>
        <button onclick="writeDR('brakes','brake','applied')">Apply Brake</button>
        <button onclick="writeDR('brakes','brake','released')">Release Brake</button>
        <button onclick="startOp('vehicle','flashLights')">Flash Lights</button>
      </div>
      <div class="row">
        <button onclick="setMode('vehicle','drive')">Mode: Drive</button>
        <button onclick="setMode('vehicle','service')">Mode: Service</button>
        <button onclick="setMode('vehicle','transport')">Mode: Transport</button>
      </div>
      <div class="row">
        <button class="warn" onclick="acquireLock('vehicle')">Acquire Lock (vehicle)</button>
        <button class="danger" onclick="releaseLock('vehicle')">Release Lock</button>
        <span class="muted" id="lockInfo"></span>
      </div>
      <div class="two">
        <div>
          <label>Speed Limiter (via operation)</label>
          <div class="row">
            <input id="limit" type="number" min="30" max="180" step="5" value="120"/>
            <button onclick="startOp('vehicle','setSpeedLimiter',{limit:+document.getElementById('limit').value})">Apply</button>
          </div>
        </div>
        <div>
          <label>Faults</label>
          <div class="row">
            <button onclick="loadFaults()">List Faults</button>
            <button class="danger" onclick="clearFaults()">Clear Faults</button>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>State</h3>
      <pre id="state">loading...</pre>
    </div>
  </div>

  <div class="card" style="margin-top:16px">
    <h3>Logs</h3>
    <pre id="log"></pre>
  </div>
</div>

<script>
  let lockToken = null;
  const log = (x) => { const el = document.getElementById('log'); el.textContent += x + "\\n"; el.scrollTop = el.scrollHeight; }

  async function fetchJSON(url, options={}){
    const res = await fetch(url, {headers: {"Content-Type":"application/json"}, ...options});
    if(!res.ok){ const t = await res.text(); throw new Error(res.status+" "+t); }
    return res.json();
  }

  async function refresh(){
    const v = await fetchJSON('/sovd/v1/entities/vehicle/data-resources');
    document.getElementById('state').textContent = JSON.stringify(v.values, null, 2);
  }

  async function acquireLock(entity){
    const r = await fetchJSON(`/sovd/v1/entities/${entity}/locks`, {method:'POST', body: JSON.stringify({ttlSec:30})});
    lockToken = r.lockToken;
    document.getElementById('lockInfo').textContent = 'lockToken='+lockToken;
    log('Lock acquired: '+lockToken);
  }
  async function releaseLock(entity){
    if(!lockToken) return;
    await fetchJSON(`/sovd/v1/entities/${entity}/locks?lockToken=${lockToken}`, {method:'DELETE'});
    log('Lock released'); lockToken=null; document.getElementById('lockInfo').textContent='';
  }

  async function writeDR(entity,name,value){
    if(lockToken==null){ log('Need lock to write'); return; }
    await fetchJSON(`/sovd/v1/entities/${entity}/data/${name}`, {method:'PUT', body: JSON.stringify({value,lockToken})});
    log(`PUT ${entity}/${name}=${value}`);
    refresh();
  }

  async function setMode(entity,mode){
    if(lockToken==null){ log('Need lock to change mode'); return; }
    await fetchJSON(`/sovd/v1/entities/${entity}/modes`, {method:'POST', body: JSON.stringify({mode,lockToken})});
    log('Mode set to '+mode);
    refresh();
  }

  async function startOp(entity,name,params={}){
    const body = {name, params};
    if(['resetECU','flashLights','setSpeedLimiter'].includes(name)){ if(!lockToken){ log('Need lock for this op'); return; } body.lockToken = lockToken; }
    const r = await fetchJSON(`/sovd/v1/entities/${entity}/operations`, {method:'POST', body: JSON.stringify(body)});
    log('Operation started: '+r.opId+' ('+name+')');
  }

  async function loadFaults(){
    const r = await fetchJSON('/sovd/v1/entities/engine/faults');
    log('Faults: '+JSON.stringify(r.faults));
  }
  async function clearFaults(){
    if(!lockToken){ log('Need lock'); return; }
    await fetchJSON(`/sovd/v1/entities/engine/faults?lockToken=${lockToken}`, {method:'DELETE'});
    log('Faults cleared');
  }

  setInterval(refresh, 1000);
  refresh();
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=DASHBOARD)

# ------------------------------------------------------------------------------
# 10) ESKİ BASİT ENDPOINTLER (geri uyum)
# ------------------------------------------------------------------------------

@app.get("/components")
def components():
    update_vehicle_state()
    return vehicle_state.model_dump()

@app.post("/command")
def command(cmd: str = Form(...)):
    if cmd == "START_ENGINE":
        vehicle_state.engine = "running"
    elif cmd == "STOP_ENGINE":
        vehicle_state.engine = "off"
    elif cmd == "APPLY_BRAKE":
        vehicle_state.brake = "applied"
    elif cmd == "RELEASE_BRAKE":
        vehicle_state.brake = "released"
    elif cmd == "LIGHTS_ON":
        vehicle_state.lights = "on"
    elif cmd == "LIGHTS_OFF":
        vehicle_state.lights = "off"
    elif cmd == "LOCK_DOORS":
        vehicle_state.doors_locked = True
    elif cmd == "UNLOCK_DOORS":
        vehicle_state.doors_locked = False
    return {"status": "ok", "vehicle_state": vehicle_state.model_dump()}
