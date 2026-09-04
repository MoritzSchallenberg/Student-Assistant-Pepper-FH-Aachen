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
    client_->async_cancel_goal(goal_handle_);
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
    client_->async_cancel_goal(goal_handle_);
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
    client_->async_cancel_goal(goal_handle_);
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
    client_->async_cancel_goal(goal_handle_);
  }
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
    client_->async_cancel_goal(goal_handle_);
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
