"""
Konfiguration -- laedt alle Zugangsdaten/IPs aus Umgebungsvariablen
(bzw. einer .env-Datei), statt sie fest im Code zu hinterlegen.

Setup: .env.example nach .env kopieren und mit echten Werten fuellen.
    cp .env.example .env

Diese Datei selbst enthaelt KEINE echten Zugangsdaten mehr und ist daher
unbedenklich fuer Git. .env liegt in .gitignore und wird nie eingecheckt.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# .env liegt im apps/web-Wurzelverzeichnis (eine Ebene ueber config/)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)


def _require(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(
            f"Umgebungsvariable {name} fehlt. Siehe .env.example, "
            f".env-Datei anlegen unter {_ENV_PATH}"
        )
    return value


# ADB Settings (Tablet, optional -- Feature funktioniert auch ohne):
ADB_PORT = int(os.environ.get("ADB_PORT", "5555"))
PHONE_IP = os.environ.get("PHONE_IP", "")

# QICLI/NAOqi Settings
PC_IP = _require("PEPPER_PC_IP", "192.168.100.1")
QI_HOST = _require("PEPPER_QI_HOST", "192.168.100.50")
QI_USER = _require("PEPPER_QI_USER", "nao")
QI_PW = _require("PEPPER_QI_PASSWORD")

# AnythingLLM Settings
API_BASE_URL = os.environ.get("ANYTHINGLLM_API_BASE_URL", "http://localhost:3001/api/v1")
API_TOKEN = _require("ANYTHINGLLM_API_TOKEN")
ANYTHINGLLM_WORKSPACE = os.environ.get("ANYTHINGLLM_WORKSPACE", "")
