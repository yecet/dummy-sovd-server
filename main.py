from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# console.sovd.io’dan gelen requestleri kabul et
origins = [
    "https://console.sovd.io"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/about")
def about():
    return {
        "name": "DemoCar",
        "version": "0.1",
        "description": "Test vehicle"
    }

@app.get("/components")
def components():
    return {
        "engine": {"status": "ok"},
        "battery": {"status": "charging"}
    }
