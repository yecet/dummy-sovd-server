from fastapi import FastAPI, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import random
import asyncio

app = FastAPI()

# console.sovd.io ve yerel web arayüzden gelen requestleri kabul et
origins = [
    "https://console.sovd.io",
    "http://localhost",  # web arayüz için
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
    "temperature": 75
}

# ---------------------
# Utility function for realistic dummy updates
# ---------------------
def update_vehicle_state():
    if vehicle_state["engine"] == "running":
        # RPM ve batarya voltajını simüle et
        vehicle_state["rpm"] = max(0, min(vehicle_state["rpm"] + random.randint(-100, 100), 6000))
        vehicle_state["battery"]["voltage"] = round(random.uniform(12.0, 14.0), 2)
        vehicle_state["temperature"] = round(random.uniform(70, 90), 1)
    else:
        vehicle_state["rpm"] = 0

# ---------------------
# Endpoints
# ---------------------
@app.get("/about")
def about():
    return {
        "name": "DemoCar",
        "version": "0.2",
        "description": "Realistic demo vehicle with simulated CAN data"
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
    </head>
    <body>
        <h1>DemoCar Control Panel</h1>
        <form action="/command" method="post">
            <button name="cmd" value="START_ENGINE">Motoru Başlat</button>
            <button name="cmd" value="STOP_ENGINE">Motoru Durdur</button>
            <button name="cmd" value="APPLY_BRAKE">Fren Uygula</button>
            <button name="cmd" value="RELEASE_BRAKE">Freni Bırak</button>
        </form>
        <h2>Current State</h2>
        <div id="state"></div>

        <script>
            async function fetchState(){
                const res = await fetch('/components');
                const data = await res.json();
                document.getElementById('state').innerText = JSON.stringify(data, null, 2);
            }
            setInterval(fetchState, 1000); // her 1 saniye güncelle
            fetchState();
        </script>
    </body>
    </html>
    """
