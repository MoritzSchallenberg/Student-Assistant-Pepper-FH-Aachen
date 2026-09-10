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
#include <deque>
#include <map>
#include <string>
#include <unordered_set>

#include <behaviortree_cpp/behavior_tree.h>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>

#include <ihk_pepper_interfaces/action/say.hpp>
#include <ihk_pepper_interfaces/action/play_gesture.hpp>
#include <ihk_pepper_interfaces/action/play_presentation.hpp>
#include <ihk_pepper_interfaces/action/approach_person.hpp>
#include <ihk_pepper_interfaces/action/run_dialogue.hpp>
#include <ihk_pepper_interfaces/action/orient_to_sound.hpp>
#include <ihk_pepper_interfaces/action/return_to_origin.hpp>
#include <ihk_pepper_interfaces/action/follow_person.hpp>
#include <ihk_pepper_interfaces/msg/safety_state.hpp>
#include <ihk_pepper_interfaces/msg/system_health.hpp>
#include <ihk_pepper_interfaces/msg/person_track_array.hpp>
#include <ihk_pepper_interfaces/msg/wave_gesture_event.hpp>
#include <ihk_pepper_interfaces/msg/wakeword_event.hpp>
#include <ihk_pepper_interfaces/msg/interaction_command.hpp>
#include <ihk_pepper_interfaces/msg/authorization_grant.hpp>
#include <ihk_pepper_interfaces/srv/cancel_interaction.hpp>
#include <ihk_pepper_interfaces/srv/set_interaction_state.hpp>
#include <ihk_pepper_interfaces/srv/associate_person_with_sound.hpp>
#include <ihk_pepper_interfaces/srv/capture_origin.hpp>
#include <action_msgs/srv/cancel_goal.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/u_int8.hpp>

namespace ihk_pepper_bt
{

// Kein gueltiger Track hat eine negative ID -- Sentinel fuer "keine
// Zielperson ausgewaehlt" im Blackboard-Feld target_track_id.
constexpr int kNoSelectedTrackId = -1;

// Entwicklungsauftrag 04-B, AP5B, Abschnitt 13: onHalted() darf eine
// laufende Action nie nur "fire-and-forget" abbrechen (kein Feedback,
// keine Bestaetigung), aber auch NIE unbegrenzt auf eine Bestaetigung
// warten -- das wuerde den BT-Tick blockieren. 250ms ist bewusst kurz
// gehalten: dieser Future wird bereits fertig, sobald der Action-Server
// die Cancel-Anfrage per CancelGoal-Service ANGENOMMEN hat (nicht erst,
// wenn die physische Bewegung tatsaechlich steht) -- ein schneller,
// lokaler ROS2-Vorgang, kein Warten auf Hardware.
constexpr std::chrono::milliseconds kHaltCancelConfirmTimeout{250};

/// Wartet BEGRENZT auf die Bestaetigung eines zuvor gestellten
/// Cancel-Requests und gibt ehrliches Feedback zurueck (true = Server hat
/// die Cancel-Anfrage innerhalb der Frist angenommen, false = noch
/// ausstehend -- wird NIE stillschweigend als "erledigt" behandelt).
/// Bewusst nur ueber std::future/std::shared_future's wait_for()-
/// Schnittstelle formuliert (kein rclcpp_action-Typ im Signaturkopf) --
/// dasselbe "Logik von ROS trennen"-Muster wie ueberall sonst im Projekt
/// (z.B. ihk_pepper_navigation/approach_pose.py): so bleibt die Funktion
/// per einfachem std::promise/std::future in einem reinen Gtest ohne
/// ROS2-Action-Infrastruktur testbar, siehe test/test_bt_cancel_confirmation.cpp.
template<typename FutureT>
bool waitForBoundedCancelConfirmation(
  FutureT & cancel_future,
  std::chrono::milliseconds timeout,
  const rclcpp::Logger & logger,
  const std::string & node_label)
{
  if (cancel_future.wait_for(timeout) == std::future_status::ready) {
    RCLCPP_INFO(
      logger, "%s: Cancel-Anfrage vom Action-Server bestaetigt (innerhalb von %ldms)",
      node_label.c_str(), static_cast<long>(timeout.count()));
    return true;
  }
  RCLCPP_WARN(
    logger,
    "%s: Cancel-Bestaetigung nach %ldms noch nicht eingetroffen -- Abbruch bleibt "
    "angefordert, wird aber NICHT als bestaetigt behandelt (Best-Effort, siehe "
    "docs/ACTION_CANCELLATION.md)",
    node_label.c_str(), static_cast<long>(timeout.count()));
  return false;
}

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

/// SUCCESS nur, wenn ein FRISCHES WakewordEvent mit gueltiger Richtung
/// vorliegt (Entwicklungsauftrag 04-B, AP6, Abschnitt 8/14). Schreibt
/// event_id/azimuth_rad/measured_at_sec auf das Blackboard fuer
/// OrientHeadToSound/FindPersonNearSoundRay -- bewusst als
/// SyncActionNode (wie SelectStablePerson), nicht als reine Bedingung,
/// da Ausgabeports geschrieben werden.
///
/// KEINE eigene "schon verbraucht"-Buchfuehrung -- das erledigt bereits
/// der bestehende Interaktionszustand: nach einer ERFOLGREICHEN
/// Begruessung wechselt /interaction_state auf CONVERSATION_READY, womit
/// IsConversationInactive (davor in der Sequence) das naechste
/// WaitForFreshWakeword-Tick ohnehin blockiert. Ein wiederholtes Ticken
/// mit demselben, noch frischen Ereignis nach einem FEHLGESCHLAGENEN
/// Versuch (z.B. Person nicht gefunden) ist bewusst erlaubt -- bleibt
/// durch max_age_s selbst begrenzt und ist kein Sicherheitsrisiko
/// (hoechstens eine erneute, vorsichtige Kopfausrichtung).
/// Entwicklungsauftrag 04-B, AP6.1, Abschnitt 3.2/6: bestaetigter Fund --
/// measured_at_sec wurde bislang als system_clock::now() (Empfangs-
/// zeitpunkt DIESES BT-Ticks) ausgegeben, NIE der echte Original-
/// Messzeitpunkt (msg->header.stamp) -- exakt dieselbe Art Fehler, die
/// audio_node.py fuer die Python-Seite bereits in AP6.1 Commit 1 behoben
/// hat, hier aber fuer die C++-Seite noch offen war. Zusaetzlich (Abschnitt
/// 6): akzeptiert nur Nachrichten mit frame_id==base_frame (die kanonische
/// Transformation aus sound_direction_transform_node.py, siehe AP6.1
/// Commit 3) und erzwingt EXACTLY-ONCE-Verarbeitung -- ein event_id, das
/// einmal erfolgreich verarbeitet wurde, kann NIE ein zweites Mal
/// SUCCESS ausloesen (begrenzter Cache verbrauchter IDs, kein
/// unbegrenztes Wachstum). Nach einem fehlgeschlagenen Versuch
/// (Kopfausrichtung/Personenzuordnung schlaegt fehl) muss die Person
/// also erneut "Pepper" sagen -- ein spaeterer Tick kann dasselbe
/// Ereignis nicht wiederverwenden.
class WaitForFreshWakeword : public BT::SyncActionNode
{
public:
  WaitForFreshWakeword(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<double>("max_age_s", 2.0, ""),
      BT::OutputPort<std::string>("wakeword_event_id"),
      BT::OutputPort<double>("azimuth_rad"),
      BT::OutputPort<double>("direction_confidence"),
      BT::OutputPort<double>("measured_at_sec"),
      BT::OutputPort<int>("original_stamp_sec"),
      BT::OutputPort<int>("original_stamp_nanosec"),
    };
  }
  BT::NodeStatus tick() override;

private:
  // Begrenzt (kein unbegrenztes Wachstum ueber eine lange Laufzeit) --
  // ein FIFO-Ringpuffer + Set fuer O(1)-Nachschlag, aeltere IDs werden
  // verdraengt, sobald der Cache voll ist (siehe .cpp fuer die Grenze).
  void markEventConsumed(const std::string & event_id);
  bool isEventConsumed(const std::string & event_id) const;

  rclcpp::Subscription<ihk_pepper_interfaces::msg::WakewordEvent>::SharedPtr sub_;
  std::string base_frame_;
  std::string last_event_id_;
  std::string last_frame_id_;
  float azimuth_rad_ {0.0f};
  float direction_confidence_ {0.0f};
  bool direction_valid_ {false};
  int32_t last_stamp_sec_ {0};
  uint32_t last_stamp_nanosec_ {0};
  std::chrono::steady_clock::time_point last_received_;
  bool have_reading_ {false};
  std::unordered_set<std::string> consumed_ids_;
  std::deque<std::string> consumed_order_;
};

/// SUCCESS nur, wenn weder Mapping noch Nav2-Fahrt aktiv sind
/// (Entwicklungsauftrag 04-B, AP6, Abschnitt 12: "Waehrend aktivem
/// Mapping oder fahrendem Nav2 darf keine Wakeword-Kopfbewegung
/// erfolgen"). Verteidigung in der Tiefe -- orient_to_sound_node.py
/// prueft dieselben Bedingungen serverseitig nochmal vollstaendig.
class IsHeadOrientationAllowed : public TopicWatchingCondition
{
public:
  IsHeadOrientationAllowed(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override;

private:
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr mapping_sub_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr nav2_sub_;
  bool mapping_active_ {true};   // sicherer Default bis zur ersten Nachricht
  bool nav2_moving_ {true};
};

/// SUCCESS nur, wenn der ROS2-Parameter "allow_unsolicited_attract" auf
/// dem bt_executor-Node explizit auf true gesetzt wurde (Entwicklungsauftrag
/// 04-B, AP6, Abschnitt 14: sicherer Standardwert false -- das bisherige
/// ungefragte Winken im IdleAttractSubtree darf nicht mehr automatisch
/// laufen).
class IsUnsolicitedAttractAllowed : public BT::ConditionNode
{
public:
  IsUnsolicitedAttractAllowed(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override;

private:
  bool allowed_ {false};
};

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
  /// Entwicklungsauftrag 04-B, AP5B, Abschnitt 13: nachvollziehbares
  /// Cancel-Feedback -- true nur, wenn der letzte onHalted()-Aufruf eine
  /// laufende Action hatte UND deren Cancel-Anfrage innerhalb der
  /// Frist bestaetigt wurde.
  bool lastHaltCancelConfirmed() const {return last_halt_cancel_confirmed_;}

private:
  using SayAction = ihk_pepper_interfaces::action::Say;
  using GoalHandle = rclcpp_action::ClientGoalHandle<SayAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<SayAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
  bool last_halt_cancel_confirmed_ {false};
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
  bool lastHaltCancelConfirmed() const {return last_halt_cancel_confirmed_;}

private:
  using GestureAction = ihk_pepper_interfaces::action::PlayGesture;
  using GoalHandle = rclcpp_action::ClientGoalHandle<GestureAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<GestureAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
  bool last_halt_cancel_confirmed_ {false};
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
  bool lastHaltCancelConfirmed() const {return last_halt_cancel_confirmed_;}

private:
  using PresentationAction = ihk_pepper_interfaces::action::PlayPresentation;
  using GoalHandle = rclcpp_action::ClientGoalHandle<PresentationAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<PresentationAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
  bool last_halt_cancel_confirmed_ {false};
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
  bool lastHaltCancelConfirmed() const {return last_halt_cancel_confirmed_;}

private:
  using ApproachAction = ihk_pepper_interfaces::action::ApproachPerson;
  using GoalHandle = rclcpp_action::ClientGoalHandle<ApproachAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<ApproachAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
  bool last_halt_cancel_confirmed_ {false};
};

/// Ruft /orient_to_sound auf (Entwicklungsauftrag 04-B, AP6, Abschnitt
/// 7/14) -- richtet den Kopf begrenzt auf eine gemessene Schallrichtung
/// aus. azimuth_rad/measured_at_sec kommen von WaitForFreshWakeword.
/// onHalted() bricht ein laufendes Ausrichten wirklich ab, gleiches
/// Muster wie ApproachSelectedPerson.
class OrientHeadToSound : public BT::StatefulActionNode
{
public:
  OrientHeadToSound(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>("wakeword_event_id"),
      BT::InputPort<double>("azimuth_rad"),
      BT::InputPort<double>("measured_at_sec"),
      BT::InputPort<double>("max_measurement_age_s", 2.0, ""),
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;
  bool lastHaltCancelConfirmed() const {return last_halt_cancel_confirmed_;}

private:
  using OrientAction = ihk_pepper_interfaces::action::OrientToSound;
  using GoalHandle = rclcpp_action::ClientGoalHandle<OrientAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<OrientAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
  bool last_halt_cancel_confirmed_ {false};
};

/// Ruft /associate_person_with_sound auf (Entwicklungsauftrag 04-B, AP6,
/// Abschnitt 13) -- ordnet die gemessene Schallrichtung genau EINER
/// RealSense-Person zu, oder KEINER bei Mehrdeutigkeit. Schreibt
/// target_track_id (dasselbe Blackboard-Feld, das SelectStablePerson
/// sonst befuellt) NUR bei erfolgreicher, eindeutiger Zuordnung --
/// FAILURE bei Mehrdeutigkeit/keiner Person, kein target_track_id
/// gesetzt.
class FindPersonNearSoundRay : public BT::StatefulActionNode
{
public:
  FindPersonNearSoundRay(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      // Entwicklungsauftrag 04-B, AP6.1, Abschnitt 4/11: dieselbe
      // event_id wie WaitForFreshWakeword/OrientHeadToSound -- damit
      // /audio/visual_target (AudioVisualTarget.msg) jedes Ergebnis dem
      // ausloesenden Wakeword-Ereignis zuordnen kann.
      BT::InputPort<std::string>("wakeword_event_id"),
      BT::InputPort<double>("azimuth_rad"),
      BT::InputPort<double>("measured_at_sec"),
      BT::InputPort<double>("max_measurement_age_s", 2.0, ""),
      BT::OutputPort<int>("target_track_id"),
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using AssociateSrv = ihk_pepper_interfaces::srv::AssociatePersonWithSound;
  rclcpp::Node::SharedPtr node_;
  rclcpp::Client<AssociateSrv>::SharedPtr client_;
  std::future<AssociateSrv::Response::SharedPtr> future_;
  bool have_future_ {false};
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
  bool lastHaltCancelConfirmed() const {return last_halt_cancel_confirmed_;}

private:
  using DialogueAction = ihk_pepper_interfaces::action::RunDialogue;
  using GoalHandle = rclcpp_action::ClientGoalHandle<DialogueAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<DialogueAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
  bool last_halt_cancel_confirmed_ {false};
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

/// Ruft /capture_origin auf (Entwicklungsauftrag 04-B, AP7, Abschnitt
/// 9/12) -- sichert die aktuelle Roboterpose als Rueckkehrpunkt, BEVOR
/// sich Pepper einer Person naehert. Gleiches Aufbau-Muster wie
/// FindPersonNearSoundRay (einfacher Service-Aufruf, kein Action-
/// Client noetig). person_id/group_id bleiben in diesem Commit leer --
/// die Rollen-/Gruppen-Verdrahtung im Baum selbst ist NICHT Teil von
/// AP7 Commit 10 (ehrlich offen, siehe Abschlussmeldung).
class CaptureOriginPose : public BT::StatefulActionNode
{
public:
  CaptureOriginPose(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<int>("track_id"),
      BT::OutputPort<std::string>("origin_id"),
      BT::OutputPort<std::string>("origin_session_id"),
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using CaptureSrv = ihk_pepper_interfaces::srv::CaptureOrigin;
  rclcpp::Node::SharedPtr node_;
  rclcpp::Client<CaptureSrv>::SharedPtr client_;
  std::future<CaptureSrv::Response::SharedPtr> future_;
  bool have_future_ {false};
  std::string session_id_;
};

/// Ruft /return_to_origin auf (Entwicklungsauftrag 04-B, AP7, Abschnitt
/// 9/12) -- faehrt zur zuvor per CaptureOriginPose gesicherten Pose
/// zurueck. Gleiches Aufbau-/Abbruch-Muster wie ApproachSelectedPerson/
/// RunDialogueViaBT (Action-Client, onHalted() bricht wirklich ab, mit
/// derselben begrenzten Cancel-Bestaetigung).
class ReturnToOriginViaBT : public BT::StatefulActionNode
{
public:
  ReturnToOriginViaBT(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>("session_id"),
      BT::InputPort<std::string>("origin_id"),
      BT::InputPort<double>("max_origin_age_s", 0.0, "0 = Node-seitiger Standardwert"),
      BT::InputPort<double>("timeout_s", 0.0, "0 = Node-seitiger Standardwert"),
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;
  bool lastHaltCancelConfirmed() const {return last_halt_cancel_confirmed_;}

private:
  using ReturnAction = ihk_pepper_interfaces::action::ReturnToOrigin;
  using GoalHandle = rclcpp_action::ClientGoalHandle<ReturnAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<ReturnAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
  bool last_halt_cancel_confirmed_ {false};
};

/// Leert die Blackboard-Felder origin_id/origin_session_id. Trivial-
/// Knoten, immer SUCCESS -- gleiches Prinzip wie ClearSelectedPerson,
/// getrennt gehalten, da eine Sitzung auch OHNE eine ausgewaehlte Person
/// enden kann (z.B. ein bereits abgebrochener Ursprung).
class ClearSession : public BT::SyncActionNode
{
public:
  ClearSession(const std::string & name, const BT::NodeConfig & config)
  : BT::SyncActionNode(name, config) {}
  static BT::PortsList providedPorts()
  {
    return {
      BT::BidirectionalPort<std::string>("origin_id"),
      BT::BidirectionalPort<std::string>("origin_session_id"),
    };
  }
  BT::NodeStatus tick() override
  {
    setOutput("origin_id", std::string(""));
    setOutput("origin_session_id", std::string(""));
    return BT::NodeStatus::SUCCESS;
  }
};

/// Wartet auf einen AUTORISIERTEN "follow_speaker"-Befehl
/// (Entwicklungsauftrag 04-B, AP7.1, Abschnitt 11: "Pepper, komm mal
/// mit") -- abonniert /interaction/authorized_command (command_router_node.py)
/// UND /authorization/grants, liefert SUCCESS nur, wenn BEIDE
/// zusammenpassen: ein FRISCHES, noch nicht verbrauchtes
/// InteractionCommand mit command=="follow_speaker" UND
/// authorization_status=="granted", UND ein AuthorizationGrant fuer
/// GENAU denselben track_id+command. Exactly-once ueber event_id
/// (gleiches Muster wie WaitForFreshWakeword) -- ein bereits
/// verarbeiteter Befehl kann NIE ein zweites Mal SUCCESS ausloesen.
class WaitForAuthorizedFollowCommand : public BT::SyncActionNode
{
public:
  WaitForAuthorizedFollowCommand(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::OutputPort<int>("target_track_id"),
      BT::OutputPort<std::string>("person_id"),
      BT::OutputPort<std::string>("authorization_grant_id"),
    };
  }
  BT::NodeStatus tick() override;

private:
  void markEventConsumed(const std::string & event_id);
  bool isEventConsumed(const std::string & event_id) const;

  rclcpp::Subscription<ihk_pepper_interfaces::msg::InteractionCommand>::SharedPtr command_sub_;
  rclcpp::Subscription<ihk_pepper_interfaces::msg::AuthorizationGrant>::SharedPtr grant_sub_;
  std::string last_event_id_;
  std::string last_command_;
  std::string last_authorization_status_;
  int32_t last_track_id_ {-1};
  std::string last_person_id_;
  bool have_command_ {false};

  std::string last_grant_id_;
  std::string last_grant_command_;
  int32_t last_grant_track_id_ {-1};
  bool have_grant_ {false};

  std::unordered_set<std::string> consumed_ids_;
  std::deque<std::string> consumed_order_;
};

/// Ruft /follow_person auf (FollowPerson.action, person_approach_node.py) --
/// gleiches Aufbau-/Abbruch-Muster wie ApproachSelectedPerson/
/// RunDialogueViaBT (Action-Client, onHalted() bricht wirklich ab, mit
/// derselben begrenzten Cancel-Bestaetigung). Entwicklungsauftrag 04-B,
/// AP7.1, Abschnitt 11: KEIN Fahrbefehl ohne den hier weitergereichten
/// authorization_grant_id -- person_approach_node.py validiert diesen
/// selbst nochmal (siehe authorization_grant_cache.py), dieser Knoten
/// kann die Pruefung nicht umgehen.
class StartAuthorizedFollow : public BT::StatefulActionNode
{
public:
  StartAuthorizedFollow(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<int>("track_id"),
      BT::InputPort<std::string>("authorization_grant_id"),
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;
  bool lastHaltCancelConfirmed() const {return last_halt_cancel_confirmed_;}

private:
  using FollowAction = ihk_pepper_interfaces::action::FollowPerson;
  using GoalHandle = rclcpp_action::ClientGoalHandle<FollowAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<FollowAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
  bool last_halt_cancel_confirmed_ {false};
};

/// Wartet auf einen AUTORISIERTEN "interrupt_and_look"-Befehl (Codewort
/// "Eisenbahn", Entwicklungsauftrag 04-B, AP7.1, Abschnitt 12) --
/// abonniert /interaction/authorized_command, liefert SUCCESS nur bei
/// einem FRISCHEN, noch nicht verbrauchten Befehl mit
/// command=="interrupt_and_look" UND authorization_status=="not_required"
/// (dieser Befehl ist rollenfrei, siehe roles.py) UND gueltiger
/// Schallrichtung. Exactly-once ueber event_id. Liefert dieselben
/// azimuth_rad/measured_at_sec-Ports wie WaitForFreshWakeword, damit
/// OrientHeadToSound/FindPersonNearSoundRay unveraendert wiederverwendet
/// werden koennen -- KEIN eigener Fahrbefehl, dieser Knoten loest
/// niemals eine Basisbewegung aus (Auftrag: "Das Codewort darf keine
/// direkte Fahrt ausloesen").
class WaitForAuthorizedInterruptCommand : public BT::SyncActionNode
{
public:
  WaitForAuthorizedInterruptCommand(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<double>("max_age_s", 2.0, ""),
      BT::OutputPort<std::string>("event_id"),
      BT::OutputPort<double>("azimuth_rad"),
      BT::OutputPort<double>("measured_at_sec"),
    };
  }
  BT::NodeStatus tick() override;

private:
  void markEventConsumed(const std::string & event_id);
  bool isEventConsumed(const std::string & event_id) const;

  rclcpp::Subscription<ihk_pepper_interfaces::msg::InteractionCommand>::SharedPtr sub_;
  std::string last_event_id_;
  std::string last_command_;
  std::string last_authorization_status_;
  float azimuth_rad_ {0.0f};
  bool direction_valid_ {false};
  int32_t last_stamp_sec_ {0};
  uint32_t last_stamp_nanosec_ {0};
  std::chrono::steady_clock::time_point last_received_;
  bool have_reading_ {false};
  std::unordered_set<std::string> consumed_ids_;
  std::deque<std::string> consumed_order_;
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
