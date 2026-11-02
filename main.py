import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router
from backend.api.forge_routes import router as forge_router
from pathlib import Path


# Create FastAPI app
app = FastAPI(
    title="Grimoire",
    description="Offline MTG companion: enrich ManaBox exports with Scryfall data, "
                "browse your collection, and forge decks from cards you own",
    version="1.0.0"
)

# CORS middleware (localhost only)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8133", "http://127.0.0.1:8133"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes first (before static files)
app.include_router(router)
app.include_router(forge_router)

# Serve frontend static files last (catch-all)
frontend_path = Path(__file__).parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


def run():
    """Run the application."""
    import webbrowser
    import threading

    # Open browser after short delay
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://localhost:8133")

    threading.Thread(target=open_browser, daemon=True).start()

    # Start server
    # Bind to loopback only: the API has no auth and can delete local data
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8133,
        log_level="info"
    )


if __name__ == "__main__":
    run()
