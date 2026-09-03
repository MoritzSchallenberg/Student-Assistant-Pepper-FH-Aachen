# Konfiguration

## Nicht-geheime Werte

`ansible/inventory/group_vars/all/vars.yml` (versioniert, sichere
Standardwerte) -- überschreibbar pro Host in
`ansible/inventory/production.yml`:

| Variable | Bedeutung | Standard |
|---|---|---|
| `pepper_qi_host` | Pepper-IP im LAN | **muss** in `production.yml` gesetzt werden |
| `pepper_qi_port` | NAOqi-Port | `9503` (NAOqi-2.9-Quirk, siehe `STATUS.md`) |
| `pepper_qi_user` | SSH-Login-Nutzer auf Pepper | `nao` |
| `ros_domain_id` | ROS_DOMAIN_ID | `0` |
| `ros_distro` | ROS2-Distribution | `jazzy` |
| `anythingllm_api_base_url` | AnythingLLM-URL | `http://localhost:3001/api/v1` |
| `anythingllm_workspace` | genutzter Workspace-Name | `""` |
| `audio_source_kind` | Audioquelle (`pepper_pulseaudio`\|`microphone`\|`file`) | `pepper_pulseaudio` |
| `whisper_model` / `whisper_language` | Faster-Whisper-Modell/Sprache | `small` / `de` |
| `camera_image_topic` | Kamera-Quelltopic | `/camera/front/image_raw` |
| `realsense_enabled` | RealSense-Unterstützung installieren | `false` |
| `deploy_revision` | Standard-Branch/Tag/Commit für Deployment | `main` |
| `deploy_keep_releases` | Anzahl aufbewahrter Releases | `5` |
| **`allow_motion`** | **Bewegung überhaupt möglich** | **`false`** |
| **`enable_autostart`** | **Dienste nach Boot automatisch starten** | **`false`** |

Diese beiden letzten Werte sind absichtlich fett hervorgehoben --
siehe Abschnitt "Sicherheitskritische Werte" unten.

## Geheimnisse (Ansible Vault)

`ansible/inventory/group_vars/all/vault.yml` (verschlüsselt, **nicht**
versioniert -- Vorlage: `vault.yml.example`). **Muss** im Unterordner
`all/` liegen, nicht als flache Datei `group_vars/vault.yml` -- sonst
wird sie von Ansible nie geladen (Dateiname = Gruppenname-Konvention,
siehe `docs/nuc-bootstrap.md`):

| Variable | Bedeutung |
|---|---|
| `vault_pepper_qi_password` | SSH/NAOqi-Passwort für Pepper |
| `vault_anythingllm_api_token` | AnythingLLM-API-Token |
| `vault_phone_ip` | optional, ADB-Telefonwahl-Feature |

Einrichtung: siehe `docs/nuc-bootstrap.md`, Abschnitt 2.

## Wo die Werte zur Laufzeit ankommen

`ansible/roles/pepper_services/templates/env.j2` (nicht-geheim) und
`env_secrets.j2` (geheim, Modus `0600`) werden nach
`/etc/ihk-pepper/env` bzw. `/etc/ihk-pepper/env_secrets` geschrieben
und von den systemd-Units per `EnvironmentFile` geladen (siehe
`docs/operations.md`).

## Laufzeitdaten-Pfade

| Pfad | Inhalt |
|---|---|
| `/etc/ihk-pepper/` | Konfiguration (env, env_secrets) |
| `/var/lib/ihk-pepper/faq_cache/` | FAQ-Cache-SQLite-Datenbank |
| `/var/lib/ihk-pepper/media/` | Präsentations-Videos/Untertitel |
| `/var/lib/ihk-pepper/maps/` | Nav2/SLAM-Karten |
| `/var/log/ihk-pepper/` | Logs, `deployments.log` |
| `/opt/ihk-pepper/releases/<commit>/` | Code je Release |
| `/opt/ihk-pepper/shared/venv_dialog/` | dediziertes venv für `ihk_pepper_dialog` (siehe unten) |

## Modelle & Medien (nicht im Git-Repository)

Große/ladbare Artefakte werden **nicht** versioniert (siehe
`.gitignore`):

| Artefakt | Woher | Wohin |
|---|---|---|
| `yolov8n-pose.pt` (YOLOv8-Pose) | lädt sich beim ersten Start von `ultralytics` automatisch herunter | Arbeitsverzeichnis des startenden Prozesses |
| Faster-Whisper-Modell (`small` o.ä.) | lädt sich beim ersten Start automatisch herunter (HuggingFace Hub) | `~/.cache/huggingface` |
| `sentence-transformers`-Modell (`paraphrase-multilingual-MiniLM-L12-v2`) | dito | `~/.cache/huggingface` |
| Tagesthema-Videos/Untertitel | manuell bereitstellen | `/var/lib/ihk-pepper/media/` |
| Nav2/SLAM-Karten | mit `slam_toolbox` selbst erzeugen | `/var/lib/ihk-pepper/maps/` |

Kleine Konfigurations-/Themendateien (Tagesthema-YAML, Gesten-YAML,
Zonen-YAML) **sind** versioniert (siehe
`ros2/autonomy_ws/src/ihk_pepper_presentation/content/daily_topics/`
u.ä.).

## Python-Abhängigkeiten

| Komponente | Datei | Besonderheit |
|---|---|---|
| `apps/web` | `apps/web/requirements.txt` | `numpy<2` (cv_bridge-Kompatibilität) |
| `vision` | `vision/requirements.txt` | dito |
| `ros2/autonomy_ws` (außer `ihk_pepper_dialog`) | `ros2/autonomy_ws/requirements.txt` | dito |
| `ihk_pepper_dialog` | `ros2/autonomy_ws/requirements-dialog.txt` | **eigenes venv** `venv_dialog` (braucht `numpy>=2` für `sentence-transformers`) |

Siehe `IMPLEMENTATION_REPORT.md` für die genaue Erklärung des
numpy-Konflikts.

## Sicherheitskritische Werte -- niemals leichtfertig ändern

- **`allow_motion: false`**: Ohne diesen Wert auf `true` (Launch-
  Parameter, propagiert bis zum `SafetyGate`, siehe
  `ihk_pepper_interaction/safety_gate.py`) kann Pepper sich **nicht**
  bewegen -- unabhängig davon, was ein Service/das LLM anfragt.
- **`enable_autostart: false`**: Verhindert, dass das System nach
  einem unbeaufsichtigten Neustart des NUC von selbst hochfährt.

Beide Werte bewusst ändern, niemals als Nebeneffekt eines anderen
Deployments.
