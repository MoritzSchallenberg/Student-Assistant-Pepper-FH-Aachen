#!/usr/bin/env python3
"""
actuator_arbiter_node: duenner ROS2-Wrapper um die reine
ActuatorArbiter-Kernlogik (Entwicklungsauftrag 04-B, AP5B). Zentrale
Koordinationsstelle fuer alle Zugriffe auf Peppers physische Aktoren --
ersetzt NICHT Motion Guard (bleibt die endgueltige Basis-Sicherheits-
schicht, siehe docs/ACTUATOR_ARBITER.md) und ist KEINE
Authentifizierungsschicht gegen absichtlich boesartige ROS2-Nodes (ROS2
bietet in diesem Projekt keine Node-Authentifizierung, siehe
Moduldoku von actuator_arbiter.py).

Startet fail-closed: keine aktiven Leases, safety_ok=False, bis das
erste (frische) SafetyState-Signal eintrifft.
"""
import time

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from std_msgs.msg import Bool, String

from ihk_pepper_interfaces.msg import ActuatorLease, ActuatorResourceState, ActuatorState, SafetyState
from ihk_pepper_interfaces.srv import (
    AcquireActuatorLease,
    CancelActuation,
    ReleaseActuatorLease,
    RenewActuatorLease,
)

from . import safety_topics
from .actuator_arbiter import (
    ALL_RESOURCES,
    BASE,
    PRIORITY_SAFETY_ABORT,
    PRIORITY_RETURN_TO_SAFE,
    ActuatorArbiter,
)

# Serverseitig vertrauenswuerdige Owner-Praefixe, die eine
# sicherheitskritische Prioritaet (<= PRIORITY_SAFETY_ABORT) tatsaechlich
# beanspruchen duerfen (Auftrag Abschnitt 3/5: "Ein LLM oder ein frei
# befuellbares Action-Feld darf keine Notfallprioritaet beanspruchen").
# Jeder andere Aufrufer, der eine solche Prioritaet anfordert, wird auf
# PRIORITY_RETURN_TO_SAFE zurueckgestuft -- die Anfrage selbst wird NICHT
# abgelehnt, nur die beanspruchte Dringlichkeit korrigiert.
TRUSTED_EMERGENCY_OWNER_PREFIXES = ("motion_guard", "supervisor", "actuator_arbiter")

SAFETY_STATE_MAX_AGE_S = 2.0
STATE_PUBLISH_INTERVAL_S = 1.0


class ActuatorArbiterNode(Node):
    def __init__(self):
        super().__init__("actuator_arbiter")

        self.declare_parameter("default_ttl_s", 30.0)

        self._arbiter = ActuatorArbiter(now_fn=time.monotonic)
        self._safety_state = None
        self._safety_state_received_at = None
        self._last_abort_reason = ""
        self._last_abort_confirmed = False

        cb_group = ReentrantCallbackGroup()

        self.create_subscription(SafetyState, safety_topics.SAFETY_STATE_TOPIC, self._on_safety_state, 10)

        self.state_pub = self.create_publisher(ActuatorState, "~/state", 10)
        self.diagnostics_pub = self.create_publisher(String, "~/diagnostics", 10)
        self.base_lease_valid_pub = self.create_publisher(Bool, "~/base_lease_valid", 10)

        self.create_service(
            AcquireActuatorLease, "~/acquire", self._handle_acquire, callback_group=cb_group)
        self.create_service(
            RenewActuatorLease, "~/renew", self._handle_renew, callback_group=cb_group)
        self.create_service(
            ReleaseActuatorLease, "~/release", self._handle_release, callback_group=cb_group)
        self.create_service(
            CancelActuation, "~/cancel", self._handle_cancel, callback_group=cb_group)

        self.create_timer(STATE_PUBLISH_INTERVAL_S, self._publish_state)

        self.get_logger().info(
            "actuator_arbiter gestartet -- fail-closed, keine aktiven Leases, "
            "safety_ok=False bis zum ersten frischen SafetyState."
        )

    # ---- SafetyState ----

    def _on_safety_state(self, msg: SafetyState):
        self._safety_state = msg
        self._safety_state_received_at = time.monotonic()
        if msg.emergency_stop or msg.bumper_active:
            reason = "emergency_stop" if msg.emergency_stop else "bumper_active"
            revoked = self._arbiter.emergency_revoke_all(reason)
            if revoked:
                self._last_abort_reason = reason
                self._last_abort_confirmed = True  # Arbiter-seitig sofort widerrufen (kein Warten noetig)
                self.get_logger().warn(
                    f"Not-Stopp/Bumper -- {len(revoked)} Lease(s) sofort widerrufen: "
                    f"{[le.owner_id for le in revoked]}"
                )
            self._publish_state()

    def _safety_ok(self) -> bool:
        if self._safety_state is None or self._safety_state_received_at is None:
            return False
        if (time.monotonic() - self._safety_state_received_at) > SAFETY_STATE_MAX_AGE_S:
            return False
        return not self._safety_state.emergency_stop and not self._safety_state.bumper_active

    # ---- Services ----

    def _effective_priority(self, owner_id: str, requested_priority: int) -> int:
        if requested_priority <= PRIORITY_SAFETY_ABORT and not owner_id.startswith(
                TRUSTED_EMERGENCY_OWNER_PREFIXES):
            self.get_logger().warn(
                f"Owner '{owner_id}' forderte Sicherheitsprioritaet {requested_priority} an -- "
                f"nicht vertrauenswuerdig, auf {PRIORITY_RETURN_TO_SAFE} zurueckgestuft."
            )
            return PRIORITY_RETURN_TO_SAFE
        return requested_priority

    def _handle_acquire(self, request, response):
        priority = self._effective_priority(request.owner_id, request.priority)
        ttl_s = request.ttl_s if request.ttl_s > 0 else self._get_default_ttl()
        result = self._arbiter.acquire(
            owner_id=request.owner_id, resources=set(request.resources), purpose=request.purpose,
            priority=priority, safety_ok=self._safety_ok(), ttl_s=ttl_s, goal_id=request.goal_id,
        )
        response.granted = result.granted
        response.lease_id = result.lease.lease_id if result.lease else ""
        response.reason = result.reason
        response.conflicting_owners = result.conflicting_owners
        if result.granted:
            self.get_logger().info(
                f"Lease gewaehrt: owner={request.owner_id} resources={sorted(request.resources)} "
                f"purpose={request.purpose}"
            )
        self._publish_state()
        return response

    def _handle_renew(self, request, response):
        response.success = self._arbiter.renew(request.lease_id, ttl_s=request.ttl_s or self._get_default_ttl())
        response.reason = "" if response.success else "lease_id unbekannt oder bereits abgelaufen"
        return response

    def _handle_release(self, request, response):
        response.success = self._arbiter.release(request.lease_id)
        self._publish_state()
        return response

    def _handle_cancel(self, request, response):
        lease = self._arbiter.get_lease(request.lease_id) if request.lease_id else None
        if lease is None and request.goal_id:
            lease = next(
                (le for le in self._arbiter.active_leases() if le.goal_id == request.goal_id), None)
        if lease is None:
            response.found = False
            response.already_inactive = True
            response.message = "keine aktive Lease fuer lease_id/goal_id gefunden"
            return response
        self._arbiter.release(lease.lease_id)
        self._last_abort_reason = request.reason or "cancel_actuation"
        self._last_abort_confirmed = True
        response.found = True
        response.already_inactive = False
        response.message = f"Lease '{lease.lease_id}' widerrufen (owner={lease.owner_id})"
        self._publish_state()
        return response

    def _get_default_ttl(self) -> float:
        return float(self.get_parameter("default_ttl_s").value)

    # ---- Status/Diagnose ----

    def _publish_state(self):
        now = time.monotonic()
        leases = self._arbiter.active_leases()

        state = ActuatorState()
        state.header.stamp = self.get_clock().now().to_msg()
        state.safety_ok = self._safety_ok()
        state.last_abort_reason = self._last_abort_reason
        state.last_abort_confirmed = self._last_abort_confirmed
        state.active_leases = [
            ActuatorLease(
                lease_id=le.lease_id, owner_id=le.owner_id, purpose=le.purpose,
                resources=sorted(le.resources), priority=le.priority,
                remaining_s=max(0.0, le.expires_at - now), goal_id=le.goal_id,
                preempted=le.preempted, preempted_reason=le.preempted_reason,
            )
            for le in leases
        ]
        resource_states = []
        for resource in sorted(ALL_RESOURCES):
            owner_lease = next((le for le in leases if resource in le.resources), None)
            resource_states.append(ActuatorResourceState(
                resource=resource,
                locked=owner_lease is not None,
                owner_id=owner_lease.owner_id if owner_lease else "",
                lease_id=owner_lease.lease_id if owner_lease else "",
                remaining_s=max(0.0, owner_lease.expires_at - now) if owner_lease else 0.0,
            ))
        state.resources = resource_states
        self.state_pub.publish(state)

        summary = (
            f"safety_ok={state.safety_ok} leases={len(leases)} "
            f"locked={[r.resource for r in resource_states if r.locked]} "
            f"last_abort={self._last_abort_reason or '-'}"
        )
        self.diagnostics_pub.publish(String(data=summary))

        base_lease_valid = any(BASE in le.resources for le in leases)
        self.base_lease_valid_pub.publish(Bool(data=base_lease_valid))


def main(args=None):
    rclpy.init(args=args)
    node = ActuatorArbiterNode()
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
