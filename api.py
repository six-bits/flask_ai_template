"""Main entry point forwarding to the app.service.api service."""

from app.service.api import app

if __name__ == "__main__":
    app.run(port=5001, debug=True)
