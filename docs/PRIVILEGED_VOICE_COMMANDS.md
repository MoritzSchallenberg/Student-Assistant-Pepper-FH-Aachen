# Privilegierte Sprachbefehle (Codewörter)

Stand: 2026-09-10. Entwicklungsauftrag 04-B, AP7, Commit 4/11.
Implementierung: `ihk_pepper_interaction/codeword_config.py` +
`config/codewords.yaml`, `command_priority.py`,
`command_authorization_decision.py`, `command_router_node.py`,
`ihk_pepper_audio/audio_node.py` (`_publish_codeword_command_if_matched()`),
`sound_direction_transform_node.py`.

## Codewörter (aktuell konfiguriert)

- **"Eisenbahn"** → `interrupt_and_look` -- unterbricht die aktuelle
  Aktivität, Pepper sieht sich um. Kein privilegierter Bewegungsbefehl,
  keine Rollenprüfung nötig.
- **"Pepper komm mal mit"** → `follow_speaker` -- startet die
  Autorisierungsprüfung für `FollowPerson` (siehe
  `docs/FOLLOW_PERSON_RUNTIME.md`).

`codeword_config.py::VALID_COMMANDS` ist eine feste Allowlist -- ein
Codewort kann NUR auf einen dieser vordefinierten Befehle abgebildet
werden, niemals auf einen beliebigen ROS2-Aufruf, Shell-Befehl oder
LLM-Prompt. Das YAML selbst kann daher keine neue Angriffsfläche
öffnen, es kann nur bestehende Befehle umbenennen/neu zuordnen.

## Datenfluss

Codewörter laufen durch DIESELBE Roh-/kanonische-Pipeline wie
`WakewordEvent` (Auftrag AP6/AP6.1): `audio_node.py` erkennt ein
Codewort in einer Transkription und veröffentlicht
`/interaction/command_raw` (immer `frame_id=respeaker_link`),
`sound_direction_transform_node.py` transformiert nach `base_link` und
veröffentlicht das kanonische `/interaction/command`.
`command_router_node.py` abonniert nur das kanonische Topic und trifft
die endgültige Autorisierungsentscheidung.

## Priorität (`command_priority.py`)

Fest codierte Reihenfolge, in dieser Reihenfolge geprüft: Not-Halt >
Stopp-/Abbruch-Codewörter > Codewort-Unterbrechung > privilegierte
Sprachbewegung > laufender Dialogtext. Ein Codewort kann eine laufende
Konversation NICHT stillschweigend verlängern, ohne dass
`_conversation_confirmed_active()` (fail-closed, braucht einen
FRISCHEN, bestätigten `interaction_state`) das bestätigt -- zu
unterscheiden von `_conversation_active_for_gate()`, das für einen
anderen Zweck (Wakeword-Blockierung) absichtlich fail-offen ist. Beide
Helfer koexistieren bewusst in `audio_node.py`.

## Rollenprüfung: Code-Tabelle ist maßgeblich, NICHT das YAML

`roles.py::PRIVILEGED_COMMAND_MIN_ROLE` (fest im Python-Code) ist die
EINZIGE durchgesetzte Rollen-Grenze. Das YAML-Feld `required_role` in
`codewords.yaml` ist aktuell nur informativ/konsistenzgeprüft, aber
NICHT unabhängig durchgesetzt -- bewusste Entscheidung
(`command_authorization_decision.py`-Docstring), damit eine
sicherheitskritische Berechtigungsgrenze nicht allein durch Bearbeiten
einer YAML-Datei verschoben werden kann.

## Ehrlicher Stand

93 Tests über `codeword_config.py`/`command_priority.py`/
`command_authorization_decision.py`/`command_router_node.py`/
`audio_node.py`-Erweiterung. Kein echtes Mikrofon, kein echtes
Codewort-Erkennungsereignis in dieser Session verifiziert -- die
Whisper-Transkriptions-Erkennung selbst (`_publish_codeword_command_if_matched()`)
ist gegen einen Fake-Whisper-Text getestet, nicht gegen echte Audio.
