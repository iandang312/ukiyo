from fastapi import FastAPI

from ukiyo_service.application.routes import health

app = FastAPI(title="Ukiyo")
app.include_router(health.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Ukiyo Service is running"}
