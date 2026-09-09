# Ein einzelnes Suchergebnis aus der Gesten-Vektordatenbank
# (Ergaenzungsauftrag 04-A, Abschnitt "Gesten-Vektordatenbank"). Rein
# beschreibend -- niemals Gelenkwinkel/Trajektorien/Befehle, dieselbe
# Trennung wie beim LLM-2-Ausgabeschema (nur ein Gestenname, keine
# Kinematik).

string name
string description
float32 score                       # semantische Aehnlichkeit zur Suchanfrage, 0..1
string tested_status                # draft | dry_run_validated | live_validated
float32 duration_s
string[] allowed_interaction_states  # leer = in jedem Zustand erlaubt
bool requires_stationary
bool affects_head            # true = bewegt Kopfgelenke, waehrend mapping_active gesperrt
bool system_only            # true = nur interne/Systemablaeufe, nie LLM-waehlbar
bool selectable_by_llm       # false = strukturell nie an LLM 2 als Option gegeben
