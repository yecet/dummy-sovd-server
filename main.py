from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import random
import asyncio

app = FastAPI()

# console.sovd.io ve yerel web arayüzden gelen requestleri kabul et
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

# ---------------------
# Vehicle State
# ---------------------
vehicle_state = {
    "engine": "off",
    "brake": "released",
    "battery": {"voltage": 12.5, "status": "charging"},
    "rpm": 0,
    "temperature": 75,
    "speed": 0,
    "fuel_level": 100,   # %
    "lights": "off",
    "doors_locked": True
}

# ---------------------
# Utility function for realistic dummy updates
# ---------------------
def update_vehicle_state():
    if vehicle_state["engine"] == "running":
        # RPM ve sıcaklık simülasyonu
        vehicle_state["rpm"] = max(600, min(vehicle_state["rpm"] + random.randint(-200, 300), 6000))
        vehicle_state["battery"]["voltage"] = round(random.uniform(12.5, 14.4), 2)
        vehicle_state["temperature"] = round(random.uniform(80, 105), 1)

        # hız kontrolü
        if vehicle_state["brake"] == "released":
            vehicle_state["speed"] = min(vehicle_state["speed"] + random.randint(0, 5), 180)
        else:
            vehicle_state["speed"] = max(vehicle_state["speed"] - random.randint(5, 15), 0)

        # yakıt tüketimi
        vehicle_state["fuel_level"] = max(vehicle_state["fuel_level"] - 0.01, 0)
    else:
        vehicle_state["rpm"] = 0
        vehicle_state["speed"] = max(vehicle_state["speed"] - 2, 0)

# ---------------------
# Endpoints
# ---------------------
@app.get("/about")
def about():
    return {
        "name": "DemoCar",
        "version": "0.3",
        "description": "Realistic demo vehicle with simulated CAN/SOVD data"
    }

@app.get("/components")
def components():
    update_vehicle_state()
    return vehicle_state

@app.post("/command")
async def command(cmd: str = Form(...)):
    if cmd == "START_ENGINE":
        vehicle_state["engine"] = "running"
    elif cmd == "STOP_ENGINE":
        vehicle_state["engine"] = "off"
    elif cmd == "APPLY_BRAKE":
        vehicle_state["brake"] = "applied"
    elif cmd == "RELEASE_BRAKE":
        vehicle_state["brake"] = "released"
    elif cmd == "LIGHTS_ON":
        vehicle_state["lights"] = "on"
    elif cmd == "LIGHTS_OFF":
        vehicle_state["lights"] = "off"
    elif cmd == "LOCK_DOORS":
        vehicle_state["doors_locked"] = True
    elif cmd == "UNLOCK_DOORS":
        vehicle_state["doors_locked"] = False
    return {"status": "ok", "vehicle_state": vehicle_state}

# ---------------------
# Basit Web Arayüzü
# ---------------------
@app.get("/", response_class=HTMLResponse)
def web_interface():
    return """
    <html>
    <head>
        <title>Vehicle Control</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            button { margin: 5px; padding: 10px; font-size: 14px; }
            pre { background: #111; color: #0f0; padding: 10px; border-radius: 8px; }
        </style>
    </head>
    <body>
        <h1>🚗 DemoCar Control Panel</h1>
        <div>
            <button onclick="sendCommand('START_ENGINE')">Motoru Başlat</button>
            <button onclick="sendCommand('STOP_ENGINE')">Motoru Durdur</button>
            <button onclick="sendCommand('APPLY_BRAKE')">Fren Uygula</button>
            <button onclick="sendCommand('RELEASE_BRAKE')">Freni Bırak</button>
            <button onclick="sendCommand('LIGHTS_ON')">Farları Aç</button>
            <button onclick="sendCommand('LIGHTS_OFF')">Farları Kapat</button>
            <button onclick="sendCommand('LOCK_DOORS')">Kapıları Kilitle</button>
            <button onclick="sendCommand('UNLOCK_DOORS')">Kapıları Aç</button>
        </div>
        <h2>Current State</h2>
        <pre id="state"></pre>

        <script>
            async function fetchState(){
                const res = await fetch('/components');
                const data = await res.json();
                document.getElementById('state').innerText = JSON.stringify(data, null, 2);
            }

            async function sendCommand(cmd){
                const formData = new FormData();
                formData.append("cmd", cmd);
                await fetch('/command', { method: 'POST', body: formData });
                fetchState();
            }

            setInterval(fetchState, 1000); // her 1 saniye güncelle
            fetchState();
        </script>
    </body>
    </html>
    """
