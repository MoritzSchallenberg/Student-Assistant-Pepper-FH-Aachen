cmake_minimum_required(VERSION 3.8)
project(ihk_pepper_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(action_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/PersonTrack.msg"
  "msg/PersonTrackArray.msg"
  "msg/WaveGestureEvent.msg"
  "msg/DialogueState.msg"
  "msg/PresentationState.msg"
  "msg/SafetyState.msg"
  "msg/SystemHealth.msg"
  "srv/SetSystemMode.srv"
  "srv/SelectDailyTopic.srv"
  "srv/ReloadKnowledge.srv"
  "srv/CancelInteraction.srv"
  "srv/SetMotionPermission.srv"
  "srv/SetInteractionState.srv"
  "srv/LookupPerson.srv"
  "srv/SetConsent.srv"
  "srv/SetDisplayName.srv"
  "srv/DeletePerson.srv"
  "srv/GetPersonContext.srv"
  "srv/WriteMemorySummary.srv"
  "action/Say.action"
  "action/RunDialogue.action"
  "action/PlayPresentation.action"
  "action/ApproachPerson.action"
  "action/GuidePerson.action"
  "action/FollowPerson.action"
  "action/PlayGesture.action"
  DEPENDENCIES std_msgs geometry_msgs builtin_interfaces action_msgs
)

ament_package()
