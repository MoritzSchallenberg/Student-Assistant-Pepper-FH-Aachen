# Personen-Rollen und Autorisierung

Stand: 2026-09-10. Entwicklungsauftrag 04-B, AP7, Commit 1-2/11.
Implementierung: `ihk_pepper_interaction/roles.py`,
`authorization_policy.py`, `command_priority.py`,
`command_authorization_decision.py`, `command_router_node.py`,
`ihk_pepper_person_memory/identity_registry_db.py` (Rollen-Spalten),
`peoplectl.py`.

## Rollenmodell

Drei Rollen mit fester Rangfolge: `STUDENT < EMPLOYEE < ADMIN`
(`roles.py::role_at_least()`). Jede Rolle hat ein optionales
Ablaufdatum (`role_valid_until_iso`); `effective_role()` fällt bei
fehlender/abgelaufener/unbekannter Rolle IMMER auf `STUDENT` zurück --
nie ein automatisches Hochstufen, nie eine stillschweigende
Fortführung einer abgelaufenen Rolle.

**Rollen werden AUSSCHLIESSLICH über das lokale CLI `peoplectl` auf
dem NUC gesetzt** (`peoplectl set-role <person_id> <role> --reason
"..." --valid-until ...`). Es gibt KEINEN ROS2-Service dafür und
KEINEN Pfad, über den ein LLM oder ein Sprachbefehl eine Rolle ändern
könnte -- das ist eine bewusste, strukturelle Grenze (kein Service
existiert, den man versehentlich freigeben könnte). Jede Rollenänderung
verlangt `--reason` und wird in `audit_log_for()` protokolliert;
`delete` verlangt zusätzlich `--yes`.

## Autorisierungsrichtlinien (`authorization_policy.py`)

- `POLICY_DISABLED` -- privilegierte Sprachbewegungen sind komplett
  gesperrt.
- `POLICY_ROLE_PLUS_CONFIRMATION` -- Produktions-Default. Verlangt
  ALLE sieben Bedingungen (siehe unten).
- `POLICY_ROLE_ONLY_DEVELOPMENT` -- nur für Entwicklung, **hart
  gesperrt sobald `production_mode=true`** (gleiches Muster wie
  `audio_node.py`s `continuous_development`-Guard). Ein Startversuch
  mit dieser Policy in Produktion bricht sofort ab.

## `check_authorization()` -- sieben Bedingungen in fester Reihenfolge

1. bekannte Identität (`known_identity`)
2. Rolle ausreichend für den angeforderten Befehl
   (`PRIVILEGED_COMMAND_MIN_ROLE`-Tabelle in `roles.py`, fest im Code,
   NICHT aus dem YAML des Codeworts -- siehe
   `docs/PRIVILEGED_VOICE_COMMANDS.md`)
3. Erkennungs-Konfidenz über einer Mindestschwelle
4. Liveness bestanden (siehe `docs/FACE_IDENTITY_AND_PRIVACY.md`)
5. Track-Übereinstimmung (dieselbe Person, die den Befehl gab)
6. sekundäre Bestätigung (zweiter Kanal, z.B. Codewort + Geste)
7. aktueller Sicherheitszustand gültig (`SafetyState`)

**Kein einzelner Kanal reicht je allein aus** -- insbesondere NIE
Gesichtserkennung allein, da Fotos/Bildschirme eine reine
Bilderkennung täuschen können (deshalb Bedingung 4/6 zusätzlich zu 1/2).
Die erste verletzte Bedingung entscheidet den Ablehnungsgrund
(`command_authorization_decision.py::decide_command_authorization()`,
fail-closed).

## AuthorizationGrant-Lebenszyklus

Bei `authorization_status == "granted"` stellt `command_router_node.py`
ein `AuthorizationGrant` aus (`grant_id` per UUID, gebunden an
`person_id`+`track_id`+`command`, Standard-Gültigkeit 30s, KEIN
Geheimmaterial) und veröffentlicht es auf `/authorization/grants` --
Broadcast-Topic statt gemeinsamem Prozessspeicher (gleiches Prinzip wie
`SafetyState`). Der Konsument (aktuell `person_approach_node.py`, siehe
`docs/FOLLOW_PERSON_RUNTIME.md`) cached eingehende Grants lokal
(`authorization_grant_cache.py`) und verbraucht einen Grant EINMALIG
bei erfolgreicher Validierung (Grant-ID, Track-ID UND Befehl müssen
exakt passen) -- ein wiederverwendeter oder für einen anderen
Track/Befehl vorgelegter Grant wird abgelehnt.

## Ehrlicher Stand

Vollständig getestet gegen Mocks/Duck-Typing (117 Tests über
`roles.py`/`authorization_policy.py`/`command_priority.py`/
`command_authorization_decision.py`/`command_router_node.py`/
`identity_registry_db.py`/`authorization_grant_cache.py`, siehe
`docs/DEVELOPMENT_ORDER_04_B_REPORT.md`, AP7 Commit 1/2/4/8). Kein
echter Sprachbefehl, keine echte Person, kein echtes Nav2 in dieser
Session verifiziert. Das Behavior Tree selbst konsumiert
`command_router_node`s Ausgaben aktuell NICHT (siehe
`docs/INTERACTION_LIFECYCLE.md`, "Nicht Teil von AP7").
