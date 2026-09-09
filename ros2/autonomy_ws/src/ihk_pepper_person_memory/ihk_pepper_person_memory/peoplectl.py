#!/usr/bin/env python3
"""
peoplectl -- lokales Verwaltungswerkzeug fuer Personenrollen
(Entwicklungsauftrag 04-B, AP7, Abschnitt 6). EINZIGER Weg, eine Rolle
zu vergeben/entziehen -- identity_registry_db.py::set_role()/
revoke_role() werden NIE ueber ein ROS2-Service oder vom LLM aufgerufen
(siehe person_memory_node.py: keine SetRole-Service-Registrierung).

Nur fuer den lokalen administrativen Benutzer gedacht -- KEINE eigene
Authentifizierung ueber dieses Tool hinaus, die Zugriffskontrolle ist
die Dateisystemberechtigung der SQLite-Datei selbst (Shell-Zugriff auf
den NUC als der Benutzer, dem diese Datei gehoert). Kein Netzwerk-
Listener, kein ROS2-Node, KEIN Klartext-PIN irgendwo in diesem Modul.

Jeder schreibende Unterbefehl verlangt --reason (protokolliert im
Audit-Log, siehe identity_registry_db.py::_audit()). Rollen werden NIE
automatisch hochgestuft -- jede Aenderung ist ein expliziter,
protokollierter Aufruf dieses Werkzeugs.
"""
import argparse
import sys
import time

from .identity_registry_db import DEFAULT_RETENTION_DAYS, IdentityRegistryStore
from ihk_pepper_interaction.roles import VALID_ROLES


def _default_db_path() -> str:
    """Gleicher Default wie person_memory_node.py::DEFAULT_IDENTITY_DB --
    bewusst hier dupliziert statt importiert (person_memory_node.py
    importiert rclpy.node.Node auf Modulebene, peoplectl soll OHNE
    rclpy lauffaehig bleiben, gleiches Prinzip wie gesturectl.py)."""
    import os
    return os.path.expanduser("~/.ihk_pepper_memory/identity.db")


def _open_store(args) -> IdentityRegistryStore:
    return IdentityRegistryStore(args.db_path, retention_days=DEFAULT_RETENTION_DAYS)


def cmd_list(args):
    store = _open_store(args)
    try:
        records = store.list_all()
        if not records:
            print("Keine Identitaeten vorhanden.")
            return 0
        for r in records:
            effective = store.get_effective_role(r.person_id)
            expired_marker = " (ABGELAUFEN -> student)" if effective != r.role else ""
            print(
                f"{r.person_id:20s} name={r.display_name or '-':16s} "
                f"consent={r.consent_status:10s} role={r.role:10s}{expired_marker} "
                f"last_seen={r.last_seen_iso or '-'}"
            )
        return 0
    finally:
        store.close()


def cmd_show(args):
    store = _open_store(args)
    try:
        record = store.lookup(args.person_id)
        if record is None:
            print(f"Unbekannte person_id: {args.person_id}", file=sys.stderr)
            return 1
        effective = store.get_effective_role(args.person_id)
        print(f"person_id:            {record.person_id}")
        print(f"display_name:         {record.display_name or '-'}")
        print(f"consent_status:       {record.consent_status}")
        print(f"confidence:           {record.confidence}")
        print(f"last_seen:            {record.last_seen_iso or '-'}")
        print(f"retention_deadline:   {record.retention_deadline_iso or '-'}")
        print(f"role (gespeichert):   {record.role}")
        print(f"role (effektiv):      {effective}")
        print(f"role_assigned_at:     {record.role_assigned_at_iso or '-'}")
        print(f"role_assigned_by:     {record.role_assigned_by or '-'}")
        print(f"role_valid_until:     {record.role_valid_until_iso or '-'}")
        print("audit_log:")
        for action, reason, ts in store.audit_log_for(args.person_id):
            when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
            print(f"  {when}  {action:24s} reason={reason}")
        return 0
    finally:
        store.close()


def _set_role(args, role: str):
    store = _open_store(args)
    try:
        if store.lookup(args.person_id) is None:
            print(f"Unbekannte person_id: {args.person_id}", file=sys.stderr)
            return 1
        valid_until_ts = None
        if args.valid_for_days is not None:
            valid_until_ts = time.time() + args.valid_for_days * 86400.0
        record = store.set_role(
            args.person_id, role, assigned_by=args.assigned_by, reason=args.reason,
            valid_until_ts=valid_until_ts,
        )
        print(f"OK: {record.person_id} ist jetzt Rolle '{record.role}'.")
        return 0
    except (ValueError, KeyError) as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1
    finally:
        store.close()


def cmd_revoke_role(args):
    store = _open_store(args)
    try:
        if store.lookup(args.person_id) is None:
            print(f"Unbekannte person_id: {args.person_id}", file=sys.stderr)
            return 1
        record = store.revoke_role(args.person_id, assigned_by=args.assigned_by, reason=args.reason)
        print(f"OK: {record.person_id} ist jetzt Rolle '{record.role}'.")
        return 0
    finally:
        store.close()


def cmd_delete(args):
    if not args.yes:
        print(
            "Abgebrochen -- --yes fehlt (Loeschung ist unwiderruflich, "
            "siehe docs/PERSON_ROLES_AND_AUTHORIZATION.md).", file=sys.stderr,
        )
        return 1
    store = _open_store(args)
    try:
        deleted = store.delete(args.person_id, reason=args.reason)
        if not deleted:
            print(f"Unbekannte person_id: {args.person_id}", file=sys.stderr)
            return 1
        print(f"OK: {args.person_id} geloescht.")
        return 0
    finally:
        store.close()


def build_parser():
    parser = argparse.ArgumentParser(prog="peoplectl", description=__doc__)
    parser.add_argument("--db-path", default=_default_db_path())
    parser.add_argument(
        "--assigned-by", default="local_admin",
        help="wer diese Aenderung vorgenommen hat, landet im Audit-Log")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="alle bekannten Identitaeten auflisten")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="eine Identitaet + Audit-Log anzeigen")
    p.add_argument("person_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("set-role", help="Rolle einer Person setzen")
    p.add_argument("person_id")
    p.add_argument("role", choices=VALID_ROLES)
    p.add_argument("--reason", required=True)
    p.add_argument("--valid-for-days", type=float, default=None,
                    help="optional: Rolle laeuft nach so vielen Tagen automatisch ab")
    p.set_defaults(func=lambda a: _set_role(a, a.role))

    p = sub.add_parser("revoke-role", help="Rolle einer Person auf 'student' zuruecksetzen")
    p.add_argument("person_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_revoke_role)

    p = sub.add_parser("delete", help="Identitaet vollstaendig loeschen (unwiderruflich)")
    p.add_argument("person_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--yes", action="store_true", help="Loeschung bestaetigen")
    p.set_defaults(func=cmd_delete)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
