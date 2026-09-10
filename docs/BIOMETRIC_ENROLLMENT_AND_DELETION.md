# Biometric Enrollment and Deletion (AP7.1)

Ergänzt `docs/FACE_IDENTITY_AND_PRIVACY.md` (AP7, Grundkonzept) um den
tatsächlich implementierten Einschreibe-/Löschmechanismus (AP7.1.3).

## Einschreibung (`enrollment_session.py` + `face_identity_node.py::/enroll_person`)

Enrollment startet **ausschließlich** über den Service `/enroll_person`
(`EnrollPerson.srv`), NIE automatisch während eines normalen Gesprächs.
Vorbedingungen, alle vor Sessionstart geprüft, sonst sofortige
Ablehnung (kein stiller Fehlschlag):

- Person existiert bereits im Registrierungssystem (`IdentityRegistryStore`).
- Gültige Einwilligung liegt vor (`consent_status == GRANTED`).
- Aktuelle Kameradaten sind vorhanden.
- Liveness ausreichend.

`EnrollmentState`/`observe_enrollment_frame()` (reine Logik, KEIN ROS):
ein Frame zählt nur, wenn **genau eine** Person sichtbar ist
(Mehrdeutigkeit → Frame überspringen, kein Fehlschlag), Liveness besteht
UND das neue Embedding ausreichend kosinus-ähnlich zum ERSTEN Embedding
der Session ist (Inkonsistenz → **gesamte Session scheitert**, da das
auf zwei verschiedene Personen vor der Kamera hindeutet). Nach
`enrollment_required_observations` (Standard 5) konsistenten Frames ist
die Session abgeschlossen; das gespeicherte Template ist der Mittelwert
aller gesammelten Embeddings. `face_identity_node.py::_on_enroll_request`
pollt bis zu `enrollment_default_timeout_s` (Standard 20s).

**Keine dauerhafte Speicherung von Gesichtsbildern** -- nur das
resultierende Embedding/Template.

## Speicherung (`biometric_template_store.py`)

Verschlüsselt (siehe Konstruktor-Docstring für das Verschlüsselungs-
verfahren), Schlüssel **nicht im Repository** (Dateipfad konfigurierbar,
Standard außerhalb des versionierten Baums). Der Store prüft
Dateiberechtigungen. Ein **nicht entschlüsselbarer Store gilt als
fail-closed** -- `identityctl validate-store` prüft das explizit
(`cmd_validate_store`, siehe unten), `production_readiness.py`
(AP7.1.12) macht dieselbe Prüfung zur Voraussetzung für den
Produktionsstart der persistenten Zuordnung.

## `identityctl` (erweitert `peoplectl`)

`ihk_pepper_identity/identityctl.py`, Unterbefehle:

| Befehl | Wirkung |
|---|---|
| `status` | Übersicht (Anzahl Personen/Templates, Store-Zustand) |
| `list` | Registrierte Personen |
| `enroll --person-id <ID>` | Ruft `/enroll_person` (einziger ROS-abhängiger Befehl) |
| `revoke --person-id <ID>` | Setzt Consent auf `WITHDRAWN` -- Template bleibt zunächst gespeichert |
| `delete --person-id <ID> --yes` | Entfernt das Template endgültig |
| `validate-store` | Prüft ALLE Templates auf Entschlüsselbarkeit |

**Wirkung von Revoke/Delete ist sofort**: `identify_persistent()`/
`role_resolution.py` prüfen den Consent-Status bei JEDER Verwendung neu
(nie zwischengespeichert) -- ein widerrufenes Template wird beim
nächsten Matching-Versuch nicht mehr geladen (`role_resolution.py`
liefert dann `known=True, consent_granted=False` → laut Rollentabelle
UNKNOWN + STUDENT, siehe `docs/PERSON_ROLES_AND_AUTHORIZATION.md`).

## Aufbewahrung/Consent -- dokumentierbar

`IdentityRegistryStore` (AP7) führt Aufbewahrungsfristen
(`retention_days`) und Consent-Status je Person -- beides über
`identityctl status`/`list` einsehbar.

## Verwandte Dokumente

`IDENTITY_RUNTIME.md`, `docs/FACE_IDENTITY_AND_PRIVACY.md`,
`docs/PERSON_ROLES_AND_AUTHORIZATION.md`.
