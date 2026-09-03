uint8 WAITING_FOR_WAKEWORD = 0
uint8 LISTENING = 1
uint8 TRANSCRIBING = 2
uint8 RETRIEVING = 3
uint8 THINKING = 4
uint8 SPEAKING = 5
uint8 WAITING_FOR_FOLLOWUP = 6
uint8 CANCELLED = 7
uint8 ERROR = 8

std_msgs/Header header
uint8 state
string state_name
string session_id
string last_transcript
string last_response
string error_message
