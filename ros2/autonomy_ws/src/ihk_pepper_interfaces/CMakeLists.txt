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
  "msg/GestureCandidate.msg"
  "msg/GestureCandidateArray.msg"
  "msg/ActuatorLease.msg"
  "msg/ActuatorResourceState.msg"
  "msg/ActuatorState.msg"
  "msg/SoundDirection.msg"
  "msg/WakewordEvent.msg"
  "msg/AudioFocusState.msg"
  "msg/AudioVisualTarget.msg"
  "msg/PersonIdentity.msg"
  "msg/PersonIdentityArray.msg"
  "msg/InteractionCommand.msg"
  "msg/AuthorizationGrant.msg"
  "msg/ConversationGroup.msg"
  "msg/ConversationGroupArray.msg"
  "msg/InteractionLifecycleState.msg"
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
  "srv/SearchGestures.srv"
  "srv/ReindexGestureDatabase.srv"
  "srv/AcquireActuatorLease.srv"
  "srv/RenewActuatorLease.srv"
  "srv/ReleaseActuatorLease.srv"
  "srv/CancelActuation.srv"
  "srv/AssociatePersonWithSound.srv"
  "srv/CaptureOrigin.srv"
  "srv/EnrollPerson.srv"
  "srv/GetEffectiveRole.srv"
  "srv/ConfirmAuthorization.srv"
  "srv/PlanGroupObservationPose.srv"
  "msg/AuthorizationRequest.msg"
  "msg/AuthorizationDecision.msg"
  "action/Say.action"
  "action/RunDialogue.action"
  "action/PlayPresentation.action"
  "action/ApproachPerson.action"
  "action/GuidePerson.action"
  "action/FollowPerson.action"
  "action/PlayGesture.action"
  "action/SetHeadPose.action"
  "action/OrientToSound.action"
  "action/ReturnToOrigin.action"
  "action/PositionForGroup.action"
  DEPENDENCIES std_msgs geometry_msgs builtin_interfaces action_msgs
)

ament_package()
