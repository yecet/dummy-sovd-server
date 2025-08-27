from fastapi import FastAPI

app = FastAPI()

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
