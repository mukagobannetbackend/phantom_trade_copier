import os

from phantom.app import create_app

app = create_app()


if __name__ == "__main__":
    host = os.getenv("PHANTOM_HOST", "127.0.0.1")
    port = int(os.getenv("PHANTOM_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
