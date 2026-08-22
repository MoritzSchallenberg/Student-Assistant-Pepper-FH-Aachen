uint8 IDLE = 0
uint8 SELECTING_TOPIC = 1
uint8 SHOWING_PREVIEW = 2
uint8 SPEAKING_INTRO = 3
uint8 PLAYING_VIDEO = 4
uint8 SHOWING_SUBTITLES = 5
uint8 VIDEO_ENDED = 6
uint8 SPEAKING_SUMMARY = 7
uint8 QUIZ = 8
uint8 QA = 9
uint8 RETURNING = 10
uint8 PAUSED = 11
uint8 CANCELLED = 12
uint8 ERROR = 13

std_msgs/Header header
uint8 state
string state_name
string topic_id
float32 progress_seconds
