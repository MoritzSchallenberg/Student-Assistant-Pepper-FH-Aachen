# Netzwerk und Zugriff

{{ documented }}

## Was diese Seite ist

Wie dieses Projekt Pepper überhaupt erreicht, und warum es dabei
absichtlich SSH statt einer direkten `qi`-Python-Verbindung nutzt.

## Netzwerk-Grundaufbau

- Pepper feste IP im Kabel-Setup: `192.168.100.50` (DHCP-Reservierung
  per MAC-Adresse, NetworkManager "shared"-Modus).
- Entwicklungsrechner auf demselben Kabel: `192.168.100.1`.
- SSH-Login: Benutzer `nao`, Passwort ausschließlich über eine
  Umgebungsvariable/einen Secret-Store — **niemals im Klartext in Code
  oder Dokumentation**, siehe `docs/STATUS.md`s eigene
  `<PEPPER_QI_PASSWORD>`-Konvention, die dieses Tutorial durchgehend
  übernimmt.
- Ohne Kabel: Pepper braucht WLAN — laut `docs/STATUS.md` **noch nicht
  konfiguriert/getestet**, ehrlich als offener Punkt markiert, nicht als
  fertig dargestellt.

## Architektur-Entscheidung: SSH + `qicli` statt direktem `qi`-Python

Ein direkter `qi`-Python-Verbindungsversuch (Port 9503, ohne SSH) wurde
geprüft, um Text-Parsing zu vermeiden und echte Signal-Subscription zu
ermöglichen — **scheiterte am TLS-Handshake**: Port 9503 nutzt ein
echtes, selbstsigniertes Aldebaran-Zertifikat
(`qi.private.aldebaran.lan`), dem der `qi`-Python-Client nicht vertraut.
Der `nao`-Benutzer hat kein `sudo` (getestet, explizit verweigert) — für
eine Root-Lösung bräuchte es entweder das echte Root-Passwort oder
Zugriff über die offizielle SoftBank-Robotics-"Robot Settings"-Software.

**Entscheidung**: nicht weiterverfolgt. Der bereits vorhandene Weg (SSH-
Login als `nao` + `qicli`-CLI-Kommandos) reicht für alles Benötigte und
läuft komplett auf dem Entwicklungsrechner (SSH ist nur der
Transportweg, die eigentliche Logik ist Python-Code in
`apps/web/pepper/qicli.py`). Root/TLS wäre nur für die rohe
`HumanPerception`-Signal-Subscription nötig gewesen — ein Nice-to-have,
kein Blocker (deshalb baut dieses Projekt eigene, YOLOv8-basierte
Personenwahrnehmung statt sich darauf zu verlassen, siehe
[Wahrnehmung und Interaktion](../perception-interaction/index.md)).

## Port-9503-Besonderheit

NAOqi 2.9 bindet Port 9559 nur noch NAOqi-intern (`localhost`). Der
extern erreichbare Zugangspunkt ist stattdessen **Port 9503** (Prozess
`qi-secure`). Für `naoqi_driver2` (ROS2-Anbindung) muss deshalb explizit
`nao_port:=9503` statt des Default-Werts (9559) gesetzt werden:

```bash
ros2 launch naoqi_driver naoqi_driver.launch.py \
  nao_ip:=192.168.100.50 nao_port:=9503 \
  network_interface:=eno1 \
  password:=<PEPPER_QI_PASSWORD> \
  qi_listen_url:=tcp://192.168.100.1:0
```

Kein Root, kein WLAN-Aus, kein Kabel-Timing-Trick nötig — nachweislich
per [naoqi_driver2 Issue #5](https://github.com/ros-naoqi/naoqi_driver2/issues/5#issuecomment-1934253818)
bestätigtes, bekanntes NAOqi-2.9-Verhalten, nicht ein projektspezifisches
Setup-Problem.

## `qicli.py` als Bausteinsammlung

Alle in [Fähigkeiten und Grenzen](capabilities-and-limits.md) genannten
Methoden sind fertige, wiederverwendbare Python-Methoden in
`apps/web/pepper/qicli.py`, direkt nutzbar als Bausteine für
Behavior-Tree-Knoten:

```python
from pepper.qicli import qicli
c = qicli("192.168.100.50", "nao", "<PEPPER_QI_PASSWORD>")
c.connect()
c.get_battery()   # -> 100
```

Seit Entwicklungsauftrag 3 zusätzlich (nicht anstatt) über
`ihk_pepper_bridge`s `Say`-/`PlayGesture`-Actions und `gesturectl`
nutzbar — siehe [Gesten und Kinematik](../gestures-kinematics/index.md).

## Verifikationsstand, Sicherheit und Einschränkungen

{{ documented }} Alle Aussagen dieser Seite stammen aus
`docs/STATUS.md`/`docs/CAPABILITIES.md`; die TLS-/Port-Befunde sind
dort als real recherchiert/getestet dokumentiert.

## Nächster Schritt

[RealSense und Koordinatenrahmen](../realsense-frames/index.md).
