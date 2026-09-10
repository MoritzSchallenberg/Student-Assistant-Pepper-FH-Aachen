// Erstmals erfolgreich gebaut gegen behaviortree_cpp 4.9.0, siehe
// bt_nodes.hpp und docs/DEVELOPMENT_ORDER_01_REPORT.md.
#include "ihk_pepper_behavior_tree/bt_nodes.hpp"

namespace ihk_pepper_bt
{

// ---- IsSafetyTriggered ---------------------------------------------------

IsSafetyTriggered::IsSafetyTriggered(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: TopicWatchingCondition(name, config)
{
  sub_ = node->create_subscription<ihk_pepper_interfaces::msg::SafetyState>(
    "/safety_state", 10,
    [this](const ihk_pepper_interfaces::msg::SafetyState::SharedPtr msg) {
      triggered_ = msg->emergency_stop || msg->bumper_active;
    });
}

BT::NodeStatus IsSafetyTriggered::tick()
{
  return triggered_ ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

// ---- IsBatteryLow ---------------------------------------------------------

IsBatteryLow::IsBatteryLow(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: TopicWatchingCondition(name, config)
{
  sub_ = node->create_subscription<ihk_pepper_interfaces::msg::SystemHealth>(
    "/pepper_bridge/system_health", 10,
    [this](const ihk_pepper_interfaces::msg::SystemHealth::SharedPtr msg) {
      battery_percent_ = msg->battery_percent;
      have_reading_ = true;
    });
}

BT::NodeStatus IsBatteryLow::tick()
{
  double threshold = getInput<double>("threshold").value_or(15.0);
  // Ohne jemals empfangene Messung (battery_percent koennte auch -1.0
  // sein, wenn Pepper unerreichbar ist, siehe bridge_node.py) bewusst
  // FAILURE -- kein Alarm ohne echte Daten (gleiches Prinzip wie
  // SafetyGate: fehlende Daten sind nie automatisch "alles ok").
  if (!have_reading_ || battery_percent_ < 0.0) {
    return BT::NodeStatus::FAILURE;
  }
  return battery_percent_ < threshold ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

// ---- InteractionStateCondition --------------------------------------------

InteractionStateCondition::InteractionStateCondition(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node, uint8_t expected_state)
: TopicWatchingCondition(name, config), expected_state_(expected_state)
{
  sub_ = node->create_subscription<std_msgs::msg::UInt8>(
    "/interaction_state", 10,
    [this](const std_msgs::msg::UInt8::SharedPtr msg) {
      current_state_ = msg->data;
      have_reading_ = true;
    });
}

BT::NodeStatus InteractionStateCondition::tick()
{
  if (!have_reading_) {
    return BT::NodeStatus::FAILURE;
  }
  return current_state_ == expected_state_ ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

// ---- WaitForFreshWakeword (Entwicklungsauftrag 04-B, AP6, Abschnitt 8/14) ----

namespace
{
// Entwicklungsauftrag 04-B, AP6.1, Abschnitt 6: begrenzt -- verhindert
// unbegrenztes Wachstum ueber eine lange Laufzeit, gross genug, dass
// keine realistische Ereignisfolge je vor Ablauf zurueckgesetzt wird.
constexpr size_t kMaxConsumedWakewordEventIds = 64;
}  // namespace

WaitForFreshWakeword::WaitForFreshWakeword(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::SyncActionNode(name, config)
{
  if (!node->has_parameter("wakeword_base_frame")) {
    node->declare_parameter<std::string>("wakeword_base_frame", "base_link");
  }
  base_frame_ = node->get_parameter("wakeword_base_frame").as_string();

  sub_ = node->create_subscription<ihk_pepper_interfaces::msg::WakewordEvent>(
    "/audio/wakeword_event", 10,
    [this](const ihk_pepper_interfaces::msg::WakewordEvent::SharedPtr msg) {
      last_event_id_ = msg->event_id;
      last_frame_id_ = msg->header.frame_id;
      azimuth_rad_ = msg->azimuth_rad;
      direction_confidence_ = msg->direction_confidence;
      direction_valid_ = msg->direction_valid;
      last_stamp_sec_ = msg->header.stamp.sec;
      last_stamp_nanosec_ = msg->header.stamp.nanosec;
      last_received_ = std::chrono::steady_clock::now();
      have_reading_ = true;
    });
}

void WaitForFreshWakeword::markEventConsumed(const std::string & event_id)
{
  if (consumed_ids_.count(event_id) > 0) {
    return;
  }
  consumed_ids_.insert(event_id);
  consumed_order_.push_back(event_id);
  if (consumed_order_.size() > kMaxConsumedWakewordEventIds) {
    consumed_ids_.erase(consumed_order_.front());
    consumed_order_.pop_front();
  }
}

bool WaitForFreshWakeword::isEventConsumed(const std::string & event_id) const
{
  return consumed_ids_.count(event_id) > 0;
}

BT::NodeStatus WaitForFreshWakeword::tick()
{
  if (!have_reading_ || !direction_valid_ || last_event_id_.empty()) {
    return BT::NodeStatus::FAILURE;
  }
  // Entwicklungsauftrag 04-B, AP6.1, Abschnitt 6: nur die kanonische,
  // bereits nach base_frame transformierte Schallrichtung akzeptieren
  // (siehe sound_direction_transform_node.py, AP6.1 Commit 3) -- ein
  // Ereignis in einem anderen/unbekannten Frame ist fail-closed
  // ungueltig, NIE stillschweigend uebernommen.
  if (last_frame_id_ != base_frame_) {
    return BT::NodeStatus::FAILURE;
  }
  // Exactly-once: ein bereits erfolgreich verarbeitetes Ereignis kann
  // NIE ein zweites Mal SUCCESS ausloesen -- ein spaeterer BT-Tick
  // (z.B. nach einem gescheiterten Ausrichtungs-/Zuordnungsversuch)
  // braucht ein NEUES Wakeword-Ereignis ("Pepper" erneut sagen).
  if (isEventConsumed(last_event_id_)) {
    return BT::NodeStatus::FAILURE;
  }
  double max_age_s = getInput<double>("max_age_s").value_or(2.0);
  double age_s = std::chrono::duration<double>(
    std::chrono::steady_clock::now() - last_received_).count();
  if (age_s > max_age_s) {
    return BT::NodeStatus::FAILURE;
  }
  setOutput("wakeword_event_id", last_event_id_);
  setOutput("azimuth_rad", static_cast<double>(azimuth_rad_));
  setOutput("direction_confidence", static_cast<double>(direction_confidence_));
  setOutput("original_stamp_sec", static_cast<int>(last_stamp_sec_));
  setOutput("original_stamp_nanosec", static_cast<int>(last_stamp_nanosec_));
  // Entwicklungsauftrag 04-B, AP6.1, Abschnitt 3.2/6: bestaetigter Fund
  // behoben -- measured_at_sec ist jetzt der ECHTE Original-Messzeitpunkt
  // (msg->header.stamp), NICHT mehr system_clock::now() (der bisherige
  // BT-Tick-Empfangszeitpunkt haette eine mittlerweile veraltete Messung
  // faelschlich als "gerade eben" ausgegeben).
  double measured_at_sec = static_cast<double>(last_stamp_sec_) +
    static_cast<double>(last_stamp_nanosec_) * 1e-9;
  setOutput("measured_at_sec", measured_at_sec);

  markEventConsumed(last_event_id_);
  return BT::NodeStatus::SUCCESS;
}

// ---- IsHeadOrientationAllowed (Entwicklungsauftrag 04-B, AP6, Abschnitt 12) ----

IsHeadOrientationAllowed::IsHeadOrientationAllowed(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: TopicWatchingCondition(name, config)
{
  mapping_sub_ = node->create_subscription<std_msgs::msg::Bool>(
    "/mapping_active", 10,
    [this](const std_msgs::msg::Bool::SharedPtr msg) {mapping_active_ = msg->data;});
  nav2_sub_ = node->create_subscription<std_msgs::msg::Bool>(
    "/nav2_moving", 10,
    [this](const std_msgs::msg::Bool::SharedPtr msg) {nav2_moving_ = msg->data;});
}

BT::NodeStatus IsHeadOrientationAllowed::tick()
{
  if (mapping_active_ || nav2_moving_) {
    return BT::NodeStatus::FAILURE;
  }
  return BT::NodeStatus::SUCCESS;
}

// ---- IsUnsolicitedAttractAllowed (Entwicklungsauftrag 04-B, AP6, Abschnitt 14) ----

IsUnsolicitedAttractAllowed::IsUnsolicitedAttractAllowed(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::ConditionNode(name, config)
{
  if (!node->has_parameter("allow_unsolicited_attract")) {
    node->declare_parameter<bool>("allow_unsolicited_attract", false);
  }
  allowed_ = node->get_parameter("allow_unsolicited_attract").as_bool();
}

BT::NodeStatus IsUnsolicitedAttractAllowed::tick()
{
  return allowed_ ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

// ---- IsSystemReady ----------------------------------------------------------

IsSystemReady::IsSystemReady(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: TopicWatchingCondition(name, config)
{
  sub_ = node->create_subscription<ihk_pepper_interfaces::msg::SafetyState>(
    "/safety_state", 10,
    [this](const ihk_pepper_interfaces::msg::SafetyState::SharedPtr msg) {
      emergency_stop_ = msg->emergency_stop;
      compute_power_valid_ = msg->compute_power_valid;
      last_received_ = std::chrono::steady_clock::now();
      have_reading_ = true;
    });
}

BT::NodeStatus IsSystemReady::tick()
{
  double max_age_s = getInput<double>("max_age_s").value_or(3.0);
  if (!have_reading_) {
    return BT::NodeStatus::FAILURE;
  }
  double age_s = std::chrono::duration<double>(std::chrono::steady_clock::now() -
      last_received_).count();
  if (age_s > max_age_s) {
    return BT::NodeStatus::FAILURE;
  }
  if (emergency_stop_ || !compute_power_valid_) {
    return BT::NodeStatus::FAILURE;
  }
  return BT::NodeStatus::SUCCESS;
}

// ---- IsApproachAllowed -------------------------------------------------------

IsApproachAllowed::IsApproachAllowed(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: TopicWatchingCondition(name, config)
{
  sub_ = node->create_subscription<ihk_pepper_interfaces::msg::SafetyState>(
    "/safety_state", 10,
    [this](const ihk_pepper_interfaces::msg::SafetyState::SharedPtr msg) {
      allow_person_approach_ = msg->allow_person_approach;
    });
}

BT::NodeStatus IsApproachAllowed::tick()
{
  return allow_person_approach_ ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

// ---- SelectStablePerson -------------------------------------------------------

SelectStablePerson::SelectStablePerson(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::SyncActionNode(name, config), node_(node)
{
  sub_ = node_->create_subscription<ihk_pepper_interfaces::msg::PersonTrackArray>(
    "/perception_node/person_tracks", 10,
    [this](const ihk_pepper_interfaces::msg::PersonTrackArray::SharedPtr msg) {
      latest_tracks_ = msg;
    });
}

BT::NodeStatus SelectStablePerson::tick()
{
  double min_interest = getInput<double>("min_interest_score").value_or(0.5);
  double max_age_s = getInput<double>("max_track_age_s").value_or(2.0);

  auto existing = getInput<int>("selected_track_id");
  int existing_id = existing.has_value() ? existing.value() : kNoSelectedTrackId;

  if (!latest_tracks_) {
    if (existing_id != kNoSelectedTrackId) {
      setOutput("selected_track_id", kNoSelectedTrackId);
    }
    return BT::NodeStatus::FAILURE;
  }

  auto is_fresh = [this, max_age_s](const ihk_pepper_interfaces::msg::PersonTrack & track) {
      rclcpp::Time last_seen(track.last_seen);
      double age_s = (node_->now() - last_seen).seconds();
      return age_s >= 0.0 && age_s <= max_age_s;
    };

  if (existing_id != kNoSelectedTrackId) {
    // Bereits eine Person gewaehlt -- nur validieren, ob sie noch
    // vorhanden, stabil, 3D-gueltig und aktuell ist.
    for (const auto & track : latest_tracks_->tracks) {
      if (static_cast<int>(track.track_id) == existing_id) {
        if (track.has_3d_position && track.stable && is_fresh(track)) {
          return BT::NodeStatus::SUCCESS;
        }
        break;
      }
    }
    // Nicht mehr gefunden oder nicht mehr stabil/3D-gueltig/aktuell ->
    // Blackboard bereinigen (Track-Verlust bricht die Auswahl ab).
    setOutput("selected_track_id", kNoSelectedTrackId);
    return BT::NodeStatus::FAILURE;
  }

  // Keine Person gewaehlt -- besten Kandidaten suchen.
  const ihk_pepper_interfaces::msg::PersonTrack * best = nullptr;
  for (const auto & track : latest_tracks_->tracks) {
    if (!track.stable || !track.has_3d_position) {continue;}
    if (track.interest_score < min_interest) {continue;}
    if (!is_fresh(track)) {continue;}
    if (!best || track.interest_score > best->interest_score) {
      best = &track;
    }
  }
  if (!best) {
    return BT::NodeStatus::FAILURE;
  }
  setOutput("selected_track_id", static_cast<int>(best->track_id));
  return BT::NodeStatus::SUCCESS;
}

// ---- HasGreetingCooldownExpired ----------------------------------------------

HasGreetingCooldownExpired::HasGreetingCooldownExpired(
  const std::string & name, const BT::NodeConfig & config)
: BT::ConditionNode(name, config) {}

BT::NodeStatus HasGreetingCooldownExpired::tick()
{
  auto track_id = getInput<int>("track_id");
  if (!track_id) {
    return BT::NodeStatus::FAILURE;
  }
  double cooldown_s = getInput<double>("cooldown_s").value_or(60.0);
  auto now = std::chrono::steady_clock::now();

  auto it = last_greeted_.find(track_id.value());
  if (it != last_greeted_.end()) {
    double elapsed_s = std::chrono::duration<double>(now - it->second).count();
    if (elapsed_s < cooldown_s) {
      return BT::NodeStatus::FAILURE;
    }
  }
  // Cooldown abgelaufen (oder nie gegruesst) -- Zeitpunkt hier direkt
  // festhalten, da im selben Tick als naechstes tatsaechlich gegruesst
  // wird (Sequence-Semantik), statt auf eine spaetere Bestaetigung zu
  // warten (haette einen zweiten Buchfuehrungsknoten gebraucht, siehe
  // docs/ARCHITECTURE_REALSense_BT.md).
  last_greeted_[track_id.value()] = now;
  return BT::NodeStatus::SUCCESS;
}

// ---- SpeakText --------------------------------------------------------------

SpeakText::SpeakText(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<SayAction>(node_, "/pepper_bridge/say");
}

BT::NodeStatus SpeakText::onStart()
{
  auto text = getInput<std::string>("text");
  if (!text || text.value().empty()) {
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "SpeakText: Say-Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  SayAction::Goal goal;
  goal.text = text.value();
  goal.allow_interrupt = true;
  goal.max_duration_s = 0.0;
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus SpeakText::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;   // Ziel abgelehnt
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void SpeakText::onHalted()
{
  if (goal_handle_) {
    auto cancel_future = client_->async_cancel_goal(goal_handle_);
    last_halt_cancel_confirmed_ = waitForBoundedCancelConfirmation(
      cancel_future, kHaltCancelConfirmTimeout, node_->get_logger(), "SpeakText");
  } else {
    last_halt_cancel_confirmed_ = false;
  }
}

// ---- PlayCatalogGesture -------------------------------------------------

PlayCatalogGesture::PlayCatalogGesture(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<GestureAction>(node_, "/pepper_bridge/play_gesture");
}

BT::NodeStatus PlayCatalogGesture::onStart()
{
  auto gesture_name = getInput<std::string>("gesture_name").value_or("wave_right");
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "PlayCatalogGesture: PlayGesture-Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  GestureAction::Goal goal;
  goal.gesture_name = gesture_name;
  goal.speed_scale = static_cast<float>(getInput<double>("speed_scale").value_or(1.0));
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus PlayCatalogGesture::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void PlayCatalogGesture::onHalted()
{
  if (goal_handle_) {
    auto cancel_future = client_->async_cancel_goal(goal_handle_);
    last_halt_cancel_confirmed_ = waitForBoundedCancelConfirmation(
      cancel_future, kHaltCancelConfirmTimeout, node_->get_logger(), "PlayCatalogGesture");
  } else {
    last_halt_cancel_confirmed_ = false;
  }
}

// ---- PlayDailyPresentation ------------------------------------------------

PlayDailyPresentation::PlayDailyPresentation(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<PresentationAction>(node_, "/play_presentation");
}

BT::NodeStatus PlayDailyPresentation::onStart()
{
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "PlayDailyPresentation: Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  PresentationAction::Goal goal;
  goal.topic_id = getInput<std::string>("topic_id").value_or("");
  goal.allow_qa = getInput<bool>("allow_qa").value_or(true);
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus PlayDailyPresentation::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void PlayDailyPresentation::onHalted()
{
  if (goal_handle_) {
    auto cancel_future = client_->async_cancel_goal(goal_handle_);
    last_halt_cancel_confirmed_ = waitForBoundedCancelConfirmation(
      cancel_future, kHaltCancelConfirmTimeout, node_->get_logger(), "PlayDailyPresentation");
  } else {
    last_halt_cancel_confirmed_ = false;
  }
}

// ---- WaitForGestureFromTrack ----------------------------------------------

WaitForGestureFromTrack::WaitForGestureFromTrack(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  sub_ = node_->create_subscription<ihk_pepper_interfaces::msg::WaveGestureEvent>(
    "/wave_gesture_events", 10,
    [this](const ihk_pepper_interfaces::msg::WaveGestureEvent::SharedPtr msg) {
      if (msg->stable && watched_track_id_ != kNoSelectedTrackId &&
      static_cast<int>(msg->track_id) == watched_track_id_)
      {
        confirmed_for_current_track_.store(true);
      }
    });
}

BT::NodeStatus WaitForGestureFromTrack::onStart()
{
  auto track_id = getInput<int>("track_id");
  if (!track_id) {
    return BT::NodeStatus::FAILURE;
  }
  watched_track_id_ = track_id.value();
  confirmed_for_current_track_.store(false);
  start_time_ = std::chrono::steady_clock::now();
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus WaitForGestureFromTrack::onRunning()
{
  if (confirmed_for_current_track_.load()) {
    return BT::NodeStatus::SUCCESS;
  }
  double timeout_s = getInput<double>("timeout_s").value_or(8.0);
  double elapsed_s = std::chrono::duration<double>(std::chrono::steady_clock::now() -
      start_time_).count();
  if (elapsed_s > timeout_s) {
    return BT::NodeStatus::FAILURE;
  }
  return BT::NodeStatus::RUNNING;
}

void WaitForGestureFromTrack::onHalted()
{
  watched_track_id_ = kNoSelectedTrackId;
  confirmed_for_current_track_.store(false);
}

// ---- ApproachSelectedPerson -------------------------------------------------

ApproachSelectedPerson::ApproachSelectedPerson(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<ApproachAction>(node_, "/approach_person");
}

BT::NodeStatus ApproachSelectedPerson::onStart()
{
  auto track_id = getInput<int>("track_id");
  if (!track_id) {
    // Blackboard-Feld "selected_track_id"/"target_track_id" leer -- kann
    // passieren, wenn die Person zwischen SelectStablePerson und diesem
    // Knoten verloren ging (derselbe Tick liest denselben Blackboard-
    // Stand, aber ein Wechsel zwischen Ticks ist moeglich).
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "ApproachSelectedPerson: Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  ApproachAction::Goal goal;
  goal.track_id = static_cast<uint32_t>(track_id.value());
  goal.target_distance_m = static_cast<float>(getInput<double>("target_distance_m").value_or(1.0));
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus ApproachSelectedPerson::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void ApproachSelectedPerson::onHalted()
{
  if (goal_handle_) {
    auto cancel_future = client_->async_cancel_goal(goal_handle_);
    last_halt_cancel_confirmed_ = waitForBoundedCancelConfirmation(
      cancel_future, kHaltCancelConfirmTimeout, node_->get_logger(), "ApproachSelectedPerson");
  } else {
    last_halt_cancel_confirmed_ = false;
  }
}

// ---- OrientHeadToSound (Entwicklungsauftrag 04-B, AP6, Abschnitt 7/14) ----

OrientHeadToSound::OrientHeadToSound(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<OrientAction>(node_, "/orient_to_sound");
}

BT::NodeStatus OrientHeadToSound::onStart()
{
  auto azimuth_rad = getInput<double>("azimuth_rad");
  auto measured_at_sec = getInput<double>("measured_at_sec");
  if (!azimuth_rad || !measured_at_sec) {
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "OrientHeadToSound: OrientToSound-Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  OrientAction::Goal goal;
  goal.wakeword_event_id = getInput<std::string>("wakeword_event_id").value_or("");
  goal.azimuth_rad_base_link = static_cast<float>(azimuth_rad.value());
  auto whole_sec = static_cast<int32_t>(measured_at_sec.value());
  goal.measured_at.sec = whole_sec;
  goal.measured_at.nanosec = static_cast<uint32_t>(
    (measured_at_sec.value() - whole_sec) * 1e9);
  goal.max_measurement_age_s = static_cast<float>(
    getInput<double>("max_measurement_age_s").value_or(2.0));
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus OrientHeadToSound::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void OrientHeadToSound::onHalted()
{
  if (goal_handle_) {
    auto cancel_future = client_->async_cancel_goal(goal_handle_);
    last_halt_cancel_confirmed_ = waitForBoundedCancelConfirmation(
      cancel_future, kHaltCancelConfirmTimeout, node_->get_logger(), "OrientHeadToSound");
  } else {
    last_halt_cancel_confirmed_ = false;
  }
}

// ---- FindPersonNearSoundRay (Entwicklungsauftrag 04-B, AP6, Abschnitt 13) ----

FindPersonNearSoundRay::FindPersonNearSoundRay(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = node_->create_client<AssociateSrv>("/associate_person_with_sound");
}

BT::NodeStatus FindPersonNearSoundRay::onStart()
{
  auto azimuth_rad = getInput<double>("azimuth_rad");
  auto measured_at_sec = getInput<double>("measured_at_sec");
  if (!azimuth_rad || !measured_at_sec) {
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->service_is_ready()) {
    RCLCPP_WARN(node_->get_logger(), "FindPersonNearSoundRay: Service nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  auto request = std::make_shared<AssociateSrv::Request>();
  request->event_id = getInput<std::string>("wakeword_event_id").value_or("");
  request->sound_azimuth_rad = static_cast<float>(azimuth_rad.value());
  auto whole_sec = static_cast<int32_t>(measured_at_sec.value());
  request->measured_at.sec = whole_sec;
  request->measured_at.nanosec = static_cast<uint32_t>(
    (measured_at_sec.value() - whole_sec) * 1e9);
  request->max_measurement_age_s = static_cast<float>(
    getInput<double>("max_measurement_age_s").value_or(2.0));
  future_ = client_->async_send_request(request).future;
  have_future_ = true;
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus FindPersonNearSoundRay::onRunning()
{
  if (!have_future_) {
    return BT::NodeStatus::FAILURE;
  }
  if (future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto response = future_.get();
  have_future_ = false;
  if (!response->valid) {
    return BT::NodeStatus::FAILURE;
  }
  setOutput("target_track_id", response->selected_track_id);
  return BT::NodeStatus::SUCCESS;
}

void FindPersonNearSoundRay::onHalted()
{
  have_future_ = false;
}

// ---- RunDialogueViaBT (Entwicklungsauftrag 3, AP11) ----------------------

RunDialogueViaBT::RunDialogueViaBT(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<DialogueAction>(node_, "/run_dialogue");
}

BT::NodeStatus RunDialogueViaBT::onStart()
{
  auto session_id = getInput<int>("session_id");
  if (!session_id) {
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "RunDialogueViaBT: Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  DialogueAction::Goal goal;
  goal.session_id = std::to_string(session_id.value());
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus RunDialogueViaBT::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void RunDialogueViaBT::onHalted()
{
  // Safety/Root-ReactiveFallback kann diesen Knoten jederzeit
  // praeemptieren -- bricht die laufende RunDialogue-Action WIRKLICH ab
  // (siehe run_dialogue_action_server.py::_cancel_callback). Gibt dabei
  // NIE eine Bewegungsfreigabe frei -- der Action-Server selbst ruft nie
  // SetMotionPermission auf.
  if (goal_handle_) {
    auto cancel_future = client_->async_cancel_goal(goal_handle_);
    last_halt_cancel_confirmed_ = waitForBoundedCancelConfirmation(
      cancel_future, kHaltCancelConfirmTimeout, node_->get_logger(), "RunDialogueViaBT");
  } else {
    last_halt_cancel_confirmed_ = false;
  }
}

// ---- SetInteractionState ------------------------------------------------

SetInteractionState::SetInteractionState(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = node_->create_client<SetInteractionStateSrv>("/set_interaction_state");
}

BT::NodeStatus SetInteractionState::onStart()
{
  auto state_name = getInput<std::string>("state_name");
  if (!state_name || state_name.value().empty()) {
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->service_is_ready()) {
    RCLCPP_WARN(node_->get_logger(), "SetInteractionState: Service nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  auto request = std::make_shared<SetInteractionStateSrv::Request>();
  request->state_name = state_name.value();
  future_ = client_->async_send_request(request).future;
  have_future_ = true;
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus SetInteractionState::onRunning()
{
  if (!have_future_) {
    return BT::NodeStatus::FAILURE;
  }
  if (future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto response = future_.get();
  have_future_ = false;
  return response->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void SetInteractionState::onHalted()
{
  have_future_ = false;
}

// ---- CaptureOriginPose (Entwicklungsauftrag 04-B, AP7, Abschnitt 9/12) ----

CaptureOriginPose::CaptureOriginPose(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = node_->create_client<CaptureSrv>("/capture_origin");
}

BT::NodeStatus CaptureOriginPose::onStart()
{
  auto track_id = getInput<int>("track_id");
  if (!track_id) {
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->service_is_ready()) {
    RCLCPP_WARN(node_->get_logger(), "CaptureOriginPose: Service nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  // Dieselbe track_id->session_id-Umwandlung wie RunDialogueViaBT --
  // eigenstaendig gehalten, damit CaptureOriginPose ohne eine
  // vorherige RunDialogueViaBT-Ausfuehrung testbar/nutzbar bleibt.
  session_id_ = std::to_string(track_id.value());
  auto request = std::make_shared<CaptureSrv::Request>();
  request->session_id = session_id_;
  request->initial_track_id = static_cast<uint32_t>(track_id.value());
  // person_id/group_id bleiben leer -- siehe Klassendoku in bt_nodes.hpp.
  future_ = client_->async_send_request(request).future;
  have_future_ = true;
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus CaptureOriginPose::onRunning()
{
  if (!have_future_) {
    return BT::NodeStatus::FAILURE;
  }
  if (future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto response = future_.get();
  have_future_ = false;
  if (!response->success) {
    RCLCPP_WARN(
      node_->get_logger(), "CaptureOriginPose abgelehnt: %s", response->reason.c_str());
    return BT::NodeStatus::FAILURE;
  }
  setOutput("origin_id", response->origin_id);
  setOutput("origin_session_id", session_id_);
  return BT::NodeStatus::SUCCESS;
}

void CaptureOriginPose::onHalted()
{
  have_future_ = false;
}

// ---- ReturnToOriginViaBT (Entwicklungsauftrag 04-B, AP7, Abschnitt 9/12) ----

ReturnToOriginViaBT::ReturnToOriginViaBT(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<ReturnAction>(node_, "/return_to_origin");
}

BT::NodeStatus ReturnToOriginViaBT::onStart()
{
  auto session_id = getInput<std::string>("session_id");
  auto origin_id = getInput<std::string>("origin_id");
  if (!session_id || !origin_id || session_id.value().empty() || origin_id.value().empty()) {
    // Kein gueltiger Ursprung gesichert (z.B. CaptureOriginPose nie
    // erfolgreich durchlaufen) -- NIE eine Schaetzfahrt versuchen.
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "ReturnToOriginViaBT: Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  ReturnAction::Goal goal;
  goal.session_id = session_id.value();
  goal.origin_id = origin_id.value();
  goal.max_origin_age_s = static_cast<float>(getInput<double>("max_origin_age_s").value_or(0.0));
  goal.timeout_s = static_cast<float>(getInput<double>("timeout_s").value_or(0.0));
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus ReturnToOriginViaBT::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void ReturnToOriginViaBT::onHalted()
{
  if (goal_handle_) {
    auto cancel_future = client_->async_cancel_goal(goal_handle_);
    last_halt_cancel_confirmed_ = waitForBoundedCancelConfirmation(
      cancel_future, kHaltCancelConfirmTimeout, node_->get_logger(), "ReturnToOriginViaBT");
  } else {
    last_halt_cancel_confirmed_ = false;
  }
}

// ---- WaitForAuthorizedFollowCommand (Entwicklungsauftrag 04-B, AP7.1,
//      Abschnitt 11) --------------------------------------------------------

WaitForAuthorizedFollowCommand::WaitForAuthorizedFollowCommand(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::SyncActionNode(name, config)
{
  command_sub_ = node->create_subscription<ihk_pepper_interfaces::msg::InteractionCommand>(
    "/interaction/authorized_command", 10,
    [this](const ihk_pepper_interfaces::msg::InteractionCommand::SharedPtr msg) {
      last_event_id_ = msg->event_id;
      last_command_ = msg->command;
      last_authorization_status_ = msg->authorization_status;
      last_track_id_ = msg->track_id;
      last_person_id_ = msg->person_id;
      have_command_ = true;
    });
  grant_sub_ = node->create_subscription<ihk_pepper_interfaces::msg::AuthorizationGrant>(
    "/authorization/grants", 10,
    [this](const ihk_pepper_interfaces::msg::AuthorizationGrant::SharedPtr msg) {
      last_grant_id_ = msg->grant_id;
      last_grant_command_ = msg->command;
      last_grant_track_id_ = msg->track_id;
      have_grant_ = msg->valid;
    });
}

void WaitForAuthorizedFollowCommand::markEventConsumed(const std::string & event_id)
{
  if (consumed_ids_.count(event_id) > 0) {
    return;
  }
  consumed_ids_.insert(event_id);
  consumed_order_.push_back(event_id);
  if (consumed_order_.size() > kMaxConsumedWakewordEventIds) {
    consumed_ids_.erase(consumed_order_.front());
    consumed_order_.pop_front();
  }
}

bool WaitForAuthorizedFollowCommand::isEventConsumed(const std::string & event_id) const
{
  return consumed_ids_.count(event_id) > 0;
}

BT::NodeStatus WaitForAuthorizedFollowCommand::tick()
{
  if (!have_command_ || last_event_id_.empty()) {
    return BT::NodeStatus::FAILURE;
  }
  if (last_command_ != "follow_speaker" || last_authorization_status_ != "granted") {
    return BT::NodeStatus::FAILURE;
  }
  if (isEventConsumed(last_event_id_)) {
    return BT::NodeStatus::FAILURE;
  }
  // Der AuthorizationGrant muss zum SELBEN track_id+command gehoeren --
  // command_router_node.py veroeffentlicht beide praktisch zeitgleich
  // (siehe _publish_final_command_decision()/_issue_grant()), aber
  // NIEMALS blind auf einen frueheren/fremden Grant vertrauen.
  if (!have_grant_ || last_grant_command_ != "follow_speaker" ||
    last_grant_track_id_ != last_track_id_)
  {
    return BT::NodeStatus::FAILURE;
  }
  setOutput("target_track_id", static_cast<int>(last_track_id_));
  setOutput("person_id", last_person_id_);
  setOutput("authorization_grant_id", last_grant_id_);
  markEventConsumed(last_event_id_);
  return BT::NodeStatus::SUCCESS;
}

// ---- StartAuthorizedFollow (Entwicklungsauftrag 04-B, AP7.1, Abschnitt 11) --

StartAuthorizedFollow::StartAuthorizedFollow(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<FollowAction>(node_, "/follow_person");
}

BT::NodeStatus StartAuthorizedFollow::onStart()
{
  auto track_id = getInput<int>("track_id");
  auto grant_id = getInput<std::string>("authorization_grant_id");
  if (!track_id || !grant_id || grant_id.value().empty()) {
    // Auftrag Abschnitt 11: KEIN Fahrbefehl ohne einen gueltigen,
    // passenden AuthorizationGrant -- niemals ein leerer/erfundener
    // grant_id.
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "StartAuthorizedFollow: FollowPerson-Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  FollowAction::Goal goal;
  goal.track_id = static_cast<uint32_t>(track_id.value());
  goal.authorization_grant_id = grant_id.value();
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus StartAuthorizedFollow::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void StartAuthorizedFollow::onHalted()
{
  if (goal_handle_) {
    auto cancel_future = client_->async_cancel_goal(goal_handle_);
    last_halt_cancel_confirmed_ = waitForBoundedCancelConfirmation(
      cancel_future, kHaltCancelConfirmTimeout, node_->get_logger(), "StartAuthorizedFollow");
  } else {
    last_halt_cancel_confirmed_ = false;
  }
}

// ---- WaitForAuthorizedInterruptCommand (Entwicklungsauftrag 04-B,
//      AP7.1, Abschnitt 12: Codewort "Eisenbahn") ---------------------------

WaitForAuthorizedInterruptCommand::WaitForAuthorizedInterruptCommand(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::SyncActionNode(name, config)
{
  sub_ = node->create_subscription<ihk_pepper_interfaces::msg::InteractionCommand>(
    "/interaction/authorized_command", 10,
    [this](const ihk_pepper_interfaces::msg::InteractionCommand::SharedPtr msg) {
      last_event_id_ = msg->event_id;
      last_command_ = msg->command;
      last_authorization_status_ = msg->authorization_status;
      azimuth_rad_ = msg->direction_azimuth_rad_base;
      direction_valid_ = msg->direction_valid;
      last_stamp_sec_ = msg->header.stamp.sec;
      last_stamp_nanosec_ = msg->header.stamp.nanosec;
      last_received_ = std::chrono::steady_clock::now();
      have_reading_ = true;
    });
}

void WaitForAuthorizedInterruptCommand::markEventConsumed(const std::string & event_id)
{
  if (consumed_ids_.count(event_id) > 0) {
    return;
  }
  consumed_ids_.insert(event_id);
  consumed_order_.push_back(event_id);
  if (consumed_order_.size() > kMaxConsumedWakewordEventIds) {
    consumed_ids_.erase(consumed_order_.front());
    consumed_order_.pop_front();
  }
}

bool WaitForAuthorizedInterruptCommand::isEventConsumed(const std::string & event_id) const
{
  return consumed_ids_.count(event_id) > 0;
}

BT::NodeStatus WaitForAuthorizedInterruptCommand::tick()
{
  if (!have_reading_ || last_event_id_.empty()) {
    return BT::NodeStatus::FAILURE;
  }
  if (last_command_ != "interrupt_and_look" || last_authorization_status_ != "not_required") {
    return BT::NodeStatus::FAILURE;
  }
  if (!direction_valid_) {
    // Auftrag Abschnitt 12: veraltete/mehrdeutige/nicht transformierbare
    // Schallrichtung -- Kopf bleibt in sicherer Position, nur eine
    // neutrale Reaktion (kein FAILURE-Sonderfall hier noetig, der
    // Aufrufer bekommt ohnehin FAILURE und faellt auf niedrigere
    // Prioritaeten zurueck).
    return BT::NodeStatus::FAILURE;
  }
  if (isEventConsumed(last_event_id_)) {
    return BT::NodeStatus::FAILURE;
  }
  double max_age_s = getInput<double>("max_age_s").value_or(2.0);
  double age_s = std::chrono::duration<double>(
    std::chrono::steady_clock::now() - last_received_).count();
  if (age_s > max_age_s) {
    return BT::NodeStatus::FAILURE;
  }
  setOutput("event_id", last_event_id_);
  setOutput("azimuth_rad", static_cast<double>(azimuth_rad_));
  double measured_at_sec = static_cast<double>(last_stamp_sec_) +
    static_cast<double>(last_stamp_nanosec_) * 1e-9;
  setOutput("measured_at_sec", measured_at_sec);
  markEventConsumed(last_event_id_);
  return BT::NodeStatus::SUCCESS;
}

// ---- SafeStopAll ------------------------------------------------------------

SafeStopAll::SafeStopAll(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::SyncActionNode(name, config), node_(node)
{
  cancel_interaction_client_ =
    node_->create_client<ihk_pepper_interfaces::srv::CancelInteraction>("/cancel_interaction");
  cancel_presentation_client_ =
    node_->create_client<action_msgs::srv::CancelGoal>("/play_presentation/_action/cancel_goal");
}

BT::NodeStatus SafeStopAll::tick()
{
  if (cancel_interaction_client_->service_is_ready()) {
    auto req = std::make_shared<ihk_pepper_interfaces::srv::CancelInteraction::Request>();
    req->reason = "behavior_tree_safety_stop";
    cancel_interaction_client_->async_send_request(req);
  }
  if (cancel_presentation_client_->service_is_ready()) {
    auto req = std::make_shared<action_msgs::srv::CancelGoal::Request>();
    cancel_presentation_client_->async_send_request(req);
  }
  RCLCPP_WARN(node_->get_logger(), "SafeStopAll ausgeloest (Sicherheitsereignis erkannt)");
  return BT::NodeStatus::SUCCESS;
}

}  // namespace ihk_pepper_bt
