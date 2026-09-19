"""入口：uv run python main.py → Web 面板 http://127.0.0.1:8000"""

import uvicorn

from web.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
