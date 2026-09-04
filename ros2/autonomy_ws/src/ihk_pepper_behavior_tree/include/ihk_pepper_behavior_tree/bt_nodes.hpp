// ihk_pepper_behavior_tree: Custom-BT.CPP-Knoten, die die bereits
// existierenden, getesteten ROS2-Actions/Services/Topics aufrufen (Say,
// PlayGesture, PlayPresentation, ApproachPerson, /safety_state,
// /interaction_state, /system_health, /perception_node/person_tracks,
// /wave_gesture_events, /set_interaction_state).
//
// Erstmals erfolgreich gebaut gegen behaviortree_cpp 4.9.0
// (Entwicklungsauftrag 1, Abschnitt "AP2") -- `colcon build
// --packages-select ihk_pepper_behavior_tree` lief ohne Fehler/Warnungen
// durch, siehe docs/DEVELOPMENT_ORDER_01_REPORT.md fuer den genauen
// Build-Nachweis und was NICHT live gegen echten Pepper getestet wurde
// (kein Roboter/keine RealSense in dieser Session erreichbar).
#pragma once

#include <atomic>
#include <chrono>
#include <map>
#include <string>

#include <behaviortree_cpp/behavior_tree.h>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>

#include <ihk_pepper_interfaces/action/say.hpp>
#include <ihk_pepper_interfaces/action/play_gesture.hpp>
#include <ihk_pepper_interfaces/action/play_presentation.hpp>
#include <ihk_pepper_interfaces/action/approach_person.hpp>
#include <ihk_pepper_interfaces/action/run_dialogue.hpp>
#include <ihk_pepper_interfaces/msg/safety_state.hpp>
#include <ihk_pepper_interfaces/msg/system_health.hpp>
#include <ihk_pepper_interfaces/msg/person_track_array.hpp>
#include <ihk_pepper_interfaces/msg/wave_gesture_event.hpp>
#include <ihk_pepper_interfaces/srv/cancel_interaction.hpp>
#include <ihk_pepper_interfaces/srv/set_interaction_state.hpp>
#include <action_msgs/srv/cancel_goal.hpp>
#include <std_msgs/msg/u_int8.hpp>

namespace ihk_pepper_bt
{

// Kein gueltiger Track hat eine negative ID -- Sentinel fuer "keine
// Zielperson ausgewaehlt" im Blackboard-Feld target_track_id.
constexpr int kNoSelectedTrackId = -1;

// ---- Bedingungen (lesen nur, keine Seiteneffekte) ----------------------

/// Basisklasse fuer Bedingungen, die einen einzelnen Topic-Wert
/// beobachten. Haelt selbst KEINE Executor-Instanz -- bt_executor_node.cpp
/// spinnt den gemeinsamen rclcpp::Node in der Tick-Schleife
/// (spin_some()), siehe dortige Kommentare.
class TopicWatchingCondition : public BT::ConditionNode
{
public:
  TopicWatchingCondition(const std::string & name, const BT::NodeConfig & config)
  : BT::ConditionNode(name, config) {}
};

class IsSafetyTriggered : public TopicWatchingCondition
{
public:
  IsSafetyTriggered(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override;

private:
  rclcpp::Subscription<ihk_pepper_interfaces::msg::SafetyState>::SharedPtr sub_;
  bool triggered_ {false};
};

class IsBatteryLow : public TopicWatchingCondition
{
public:
  IsBatteryLow(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<double>("threshold", 15.0, "Akku-Prozent-Schwelle")};
  }
  BT::NodeStatus tick() override;

private:
  rclcpp::Subscription<ihk_pepper_interfaces::msg::SystemHealth>::SharedPtr sub_;
  double battery_percent_ {100.0};
  bool have_reading_ {false};
};

/// Gemeinsame Basis fuer die vier interaction_state-basierten Bedingungen
/// (IsPersonEngaged/ShouldShowPresentation/IsPersonAttracted/
/// IsNavigationTaskActive) -- alle lesen denselben UInt8-Topic
/// /interaction_state (siehe ihk_pepper_interaction/supervisor_node.py).
class InteractionStateCondition : public TopicWatchingCondition
{
public:
  InteractionStateCondition(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node, uint8_t expected_state);
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override;

private:
  rclcpp::Subscription<std_msgs::msg::UInt8>::SharedPtr sub_;
  uint8_t expected_state_;
  uint8_t current_state_ {0};   // 0 == IDLE (InteractionState-IntEnum)
  bool have_reading_ {false};
};

// Werte aus ihk_pepper_interaction/interaction_state.py::InteractionState
constexpr uint8_t INTERACTION_STATE_IDLE = 0;
constexpr uint8_t INTERACTION_STATE_ATTRACT = 1;
constexpr uint8_t INTERACTION_STATE_ENGAGED = 2;
constexpr uint8_t INTERACTION_STATE_NAVIGATING = 4;
// Entwicklungsauftrag 3, AP11: Zielzustand nach erfolgreicher Mock-
// Annaeherung (siehe ihk_pepper_interaction/interaction_state.py).
constexpr uint8_t INTERACTION_STATE_CONVERSATION_READY = 7;

/// SUCCESS nur, wenn /safety_state aktuell (nicht aelter als max_age_s)
/// UND weder emergency_stop noch compute_power_invalid gemeldet ist.
/// Das ist die Systemvoraussetzung fuer den Beguessen-Teilbaum -- NICHT
/// dasselbe wie Bewegungsfreigabe (siehe IsApproachAllowed), Gruessen/
/// Winken braucht keine allow_motion-Freigabe.
class IsSystemReady : public TopicWatchingCondition
{
public:
  IsSystemReady(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<double>("max_age_s", 3.0,
          "Maximales Alter der letzten /safety_state-Nachricht")};
  }
  BT::NodeStatus tick() override;

private:
  rclcpp::Subscription<ihk_pepper_interfaces::msg::SafetyState>::SharedPtr sub_;
  bool emergency_stop_ {true};        // sicherer Default, bis die erste Nachricht kommt
  bool compute_power_valid_ {false};  // dito
  std::chrono::steady_clock::time_point last_received_;
  bool have_reading_ {false};
};

/// SUCCESS wenn /safety_state.allow_person_approach true ist.
class IsApproachAllowed : public TopicWatchingCondition
{
public:
  IsApproachAllowed(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override;

private:
  rclcpp::Subscription<ihk_pepper_interfaces::msg::SafetyState>::SharedPtr sub_;
  bool allow_person_approach_ {false};
};

/// Waehlt bei leerem Blackboard-Slot die Person mit dem besten
/// interest_score aus /perception_node/person_tracks (nur stabile
/// Tracks mit gueltiger 3D-Position und ausreichender Konfidenz).
/// Ist bereits eine Person ausgewaehlt (selected_track_id im
/// Blackboard != kNoSelectedTrackId), validiert DERSELBE Knoten jeden
/// Tick weiter, ob dieser Track noch vorhanden/aktuell ist, und loescht
/// bei Verlust den Blackboard-Eintrag selbst (FAILURE) -- vermeidet
/// einen separaten Validierungsknoten (Entwicklungsauftrag 1, Abschnitt 6).
class SelectStablePerson : public BT::SyncActionNode
{
public:
  SelectStablePerson(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::BidirectionalPort<int>("selected_track_id",
          "Blackboard-Feld fuer die gewaehlte Zielperson"),
      BT::InputPort<double>("min_interest_score", 0.5, ""),
      BT::InputPort<double>("max_track_age_s", 2.0, "")
    };
  }
  BT::NodeStatus tick() override;

private:
  rclcpp::Node::SharedPtr node_;
  rclcpp::Subscription<ihk_pepper_interfaces::msg::PersonTrackArray>::SharedPtr sub_;
  ihk_pepper_interfaces::msg::PersonTrackArray::SharedPtr latest_tracks_;
};

/// SUCCESS wenn fuer die uebergebene track_id noch nie gegruesst wurde
/// ODER der konfigurierte Cooldown seit dem letzten Gruss abgelaufen ist.
/// Haelt die Cooldown-Historie INTERN (ueberlebt also nur, solange
/// derselbe bt_executor_node-Prozess laeuft, wie der Rest des Baums).
class HasGreetingCooldownExpired : public BT::ConditionNode
{
public:
  HasGreetingCooldownExpired(const std::string & name, const BT::NodeConfig & config);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<int>("track_id"),
      BT::InputPort<double>("cooldown_s", 60.0, "")
    };
  }
  BT::NodeStatus tick() override;

private:
  std::map<int, std::chrono::steady_clock::time_point> last_greeted_;
};

// ---- Aktionen (rufen echte ROS2-Actions/Services auf) -------------------

/// Ruft /pepper_bridge/say auf und wartet auf das Ergebnis.
class SpeakText : public BT::StatefulActionNode
{
public:
  SpeakText(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<std::string>("text")};
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using SayAction = ihk_pepper_interfaces::action::Say;
  using GoalHandle = rclcpp_action::ClientGoalHandle<SayAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<SayAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
};

/// Ruft /pepper_bridge/play_gesture mit einem Namen aus dem Gestenkatalog
/// auf (Entwicklungsauftrag 1, Abschnitt 6: generalisiert von der
/// urspruenglichen WaveGesture-Klasse, die NUR winken konnte -- jetzt
/// jede Katalog-Geste ueber den gesture_name-Port).
class PlayCatalogGesture : public BT::StatefulActionNode
{
public:
  PlayCatalogGesture(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>("gesture_name", "wave_right", "Name aus dem Gesten-Katalog"),
      BT::InputPort<double>("speed_scale", 1.0, "")
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using GestureAction = ihk_pepper_interfaces::action::PlayGesture;
  using GoalHandle = rclcpp_action::ClientGoalHandle<GestureAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<GestureAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
};

/// Ruft /play_presentation auf (ihk_pepper_presentation).
class PlayDailyPresentation : public BT::StatefulActionNode
{
public:
  PlayDailyPresentation(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>("topic_id", "", "Leer = automatische Auswahl"),
      BT::InputPort<bool>("allow_qa", true, "")
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using PresentationAction = ihk_pepper_interfaces::action::PlayPresentation;
  using GoalHandle = rclcpp_action::ClientGoalHandle<PresentationAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<PresentationAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
};

/// Wartet, bis fuer EXAKT die uebergebene track_id ein
/// WaveGestureEvent mit stable=true auf /wave_gesture_events eintrifft,
/// oder bis timeout_s ueberschritten ist (-> FAILURE). Ein Winken einer
/// ANDEREN track_id wird ignoriert (Entwicklungsauftrag 1, Abschnitt 6:
/// "ein Winken einer anderen Person darf die Annaeherung nicht ausloesen").
class WaitForGestureFromTrack : public BT::StatefulActionNode
{
public:
  WaitForGestureFromTrack(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<int>("track_id"),
      BT::InputPort<double>("timeout_s", 8.0, "")
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  rclcpp::Node::SharedPtr node_;
  rclcpp::Subscription<ihk_pepper_interfaces::msg::WaveGestureEvent>::SharedPtr sub_;
  std::atomic<bool> confirmed_for_current_track_ {false};
  int watched_track_id_ {kNoSelectedTrackId};
  std::chrono::steady_clock::time_point start_time_;
};

/// Ruft /approach_person auf (ihk_pepper_navigation). track_id kommt aus
/// dem Blackboard-Feld target_track_id, befuellt durch SelectStablePerson
/// (Entwicklungsauftrag 1, Abschnitt 6: umbenannt von
/// ApproachTargetPerson -- gleiche Logik, klarerer Name im neuen
/// Begruessen-und-Annaehern-Ablauf).
class ApproachSelectedPerson : public BT::StatefulActionNode
{
public:
  ApproachSelectedPerson(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<int>("track_id"),
      BT::InputPort<double>("target_distance_m", 1.0, "")
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using ApproachAction = ihk_pepper_interfaces::action::ApproachPerson;
  using GoalHandle = rclcpp_action::ClientGoalHandle<ApproachAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<ApproachAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
};

/// Ruft /run_dialogue auf (Entwicklungsauftrag 3, AP11) und wartet auf
/// das Ergebnis -- startet den Dialog NACHDEM CONVERSATION_READY
/// erreicht wurde (siehe DialogueSubtree in trees/pepper_main.xml).
/// onHalted() bricht ein laufendes Gespraech wirklich ab (Safety
/// praeemptiert ueber die Root-ReactiveFallback jederzeit), GENAU wie
/// bei ApproachSelectedPerson -- der Action-Server selbst gibt dabei
/// NIE eine Bewegungsfreigabe frei (siehe run_dialogue_action_server.py).
class RunDialogueViaBT : public BT::StatefulActionNode
{
public:
  RunDialogueViaBT(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    // int, NICHT string -- track_id auf dem Blackboard (z.B.
    // "target_track_id") ist als int abgelegt (siehe SelectStablePerson).
    // Ein direkter getInput<std::string> auf einen int-typisierten
    // Blackboard-Eintrag ist in BT.CPP 4.x nicht garantiert verlustfrei --
    // die Umwandlung zu RunDialogue.action's string-Feld session_id
    // passiert deshalb explizit in onStart(), nicht ueber den Port-Typ.
    return {BT::InputPort<int>("session_id")};
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using DialogueAction = ihk_pepper_interfaces::action::RunDialogue;
  using GoalHandle = rclcpp_action::ClientGoalHandle<DialogueAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<DialogueAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
};

/// Ruft /set_interaction_state auf (neuer Service, behandelt von
/// supervisor_node.py) -- der Supervisor bleibt einzige Quelle der
/// Wahrheit fuer den Zustand, dieser Knoten kann nur ANFRAGEN, siehe
/// ihk_pepper_interaction/interaction_state.py::request_external_state().
class SetInteractionState : public BT::StatefulActionNode
{
public:
  SetInteractionState(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<std::string>("state_name")};
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using SetInteractionStateSrv = ihk_pepper_interfaces::srv::SetInteractionState;
  rclcpp::Node::SharedPtr node_;
  rclcpp::Client<SetInteractionStateSrv>::SharedPtr client_;
  // rclcpp::Client<T>::FutureAndRequestId hat KEINEN Default-Konstruktor
  // (async-Anfragen-ID ist Teil des Konstruktors) -- deshalb nur das
  // eigentliche std::future als Member halten, per pruefbarem have_future_
  // signalisiert statt eines optional<FutureAndRequestId>.
  std::future<SetInteractionStateSrv::Response::SharedPtr> future_;
  bool have_future_ {false};
};

/// Leert den Blackboard-Slot selected_track_id (setzt kNoSelectedTrackId).
/// Trivial-Knoten, immer SUCCESS -- genutzt im Fehler-/Timeout-/Safety-
/// Praemptionspfad, damit die naechste Zielauswahl wieder frisch beginnt.
class ClearSelectedPerson : public BT::SyncActionNode
{
public:
  ClearSelectedPerson(const std::string & name, const BT::NodeConfig & config)
  : BT::SyncActionNode(name, config) {}
  static BT::PortsList providedPorts()
  {
    return {BT::BidirectionalPort<int>("selected_track_id")};
  }
  BT::NodeStatus tick() override
  {
    setOutput("selected_track_id", kNoSelectedTrackId);
    return BT::NodeStatus::SUCCESS;
  }
};

/// Ruft /cancel_interaction UND den generischen Action-Cancel-Service
/// fuer /play_presentation auf -- exakt derselbe Pfad wie der
/// Tablet-Stop-Button (siehe apps/web/tablet/ros_bridge.py
/// request_stop()). Kehrt sofort mit SUCCESS zurueck (fire-and-forget,
/// wie beim Tablet-Button).
class SafeStopAll : public BT::SyncActionNode
{
public:
  SafeStopAll(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override;

private:
  rclcpp::Node::SharedPtr node_;
  rclcpp::Client<ihk_pepper_interfaces::srv::CancelInteraction>::SharedPtr
    cancel_interaction_client_;
  rclcpp::Client<action_msgs::srv::CancelGoal>::SharedPtr cancel_presentation_client_;
};

/// No-op, immer SUCCESS -- letzter Ausweg im IdleAttractSubtree, damit
/// der Baum immer terminiert (Pepper bleibt einfach ruhig stehen).
class AlwaysSuccessIdle : public BT::SyncActionNode
{
public:
  AlwaysSuccessIdle(const std::string & name, const BT::NodeConfig & config)
  : BT::SyncActionNode(name, config) {}
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override {return BT::NodeStatus::SUCCESS;}
};

}  // namespace ihk_pepper_bt
