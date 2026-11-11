"""api-handler: the FastAPI app behind API Gateway (HTTP API, payload v2) via Mangum."""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="auto")
