"""Minimal FastAPI app for testing - will be fully implemented in Task 7."""
from fastapi import FastAPI
from backend.api.routes import router

app = FastAPI(title="Scryfall Collection Enhancer")
app.include_router(router)
