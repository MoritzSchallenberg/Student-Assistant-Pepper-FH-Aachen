uint8 WAITING_FOR_WAKEWORD = 0
uint8 LISTENING = 1
uint8 TRANSCRIBING = 2
uint8 RETRIEVING = 3
uint8 THINKING = 4
uint8 SPEAKING = 5
uint8 WAITING_FOR_FOLLOWUP = 6
uint8 CANCELLED = 7
uint8 ERROR = 8
# Ergaenzungsauftrag 04-A: neu angehaengt (bestehende Werte 0-8 NICHT
# umnummeriert, damit vorhandene Vergleiche/Logs weiter gueltig bleiben).
uint8 ACKNOWLEDGING = 9        # kurzes Bestaetigungssignal direkt nach der Frage, vor der LLM-Pipeline
uint8 WAITING_FOR_RESPONSE = 10  # LLM-Pipeline laeuft laenger als thinking_loop_delay_s -- thinking_loop_subtle aktiv
uint8 ENDING = 11               # Dialog wird kontrolliert beendet (siehe Abschnitt "Gespraechslebenszyklus")
uint8 PERSON_LOST = 12          # Zielperson waehrend des Dialogs verloren -- bisher nur result.final_state, jetzt auch als Live-Feedback

std_msgs/Header header
uint8 state
string state_name
string session_id
string last_transcript
string last_response
string error_message
