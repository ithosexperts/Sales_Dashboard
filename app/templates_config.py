"""
Jinja2 template environment configuration.
"""
from pathlib import Path
from starlette.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
