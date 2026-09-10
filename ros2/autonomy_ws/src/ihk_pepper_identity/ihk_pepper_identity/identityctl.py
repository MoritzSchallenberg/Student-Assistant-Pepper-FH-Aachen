#!/usr/bin/env python3
"""
identityctl -- lokales Verwaltungswerkzeug fuer biometrische Vorlagen
(Entwicklungsauftrag 04-B, AP7.1, Abschnitt 7). Ergaenzt peoplectl
(ihk_pepper_person_memory, Rollen-/Consent-Verwaltung) um den
biometrischen Speicher (ihk_pepper_identity/biometric_template_store.py).

status/list/revoke/delete/validate-store arbeiten DIREKT auf den
Speicherdateien (kein ROS2 noetig, gleiches Prinzip wie peoplectl) --
enroll ist die EINZIGE Ausnahme: eine Einschreibung braucht AKTUELLE
Kameradaten (Auftrag Abschnitt 7: "aktuelle Kameradaten vorliegen,
Liveness ausreichend, mehrere geeignete Beobachtungen gesammelt"),
das kann nur der laufende face_identity_node.py leisten -- enroll ruft
dessen /enroll_person-Service auf (ROS2 muss dafuer laufen).

revoke widerruft NUR die Einwilligung (identity_registry_db.py::
set_consent(), das Template bleibt gespeichert, verschluesselt, aber
sofort unbenutzbar -- face_identity_node.py prueft Consent vor JEDER
Verwendung erneut). delete entfernt das Template TATSAECHLICH
(unwiderruflich, verlangt --yes) -- beide sind bewusst getrennte
Befehle (Auftrag Abschnitt 7: "Loeschung und Widerruf unmittelbar
wirksam machen").

Nur fuer den lokalen administrativen Benutzer gedacht -- kein Netzwerk-
Listener ausser dem expliziten enroll-ROS2-Aufruf, kein Klartext-PIN."""
import argparse
import sys

from ihk_pepper_person_memory.identity_registry_db import ConsentStatus, IdentityRegistryStore

from .biometric_template_store import DEFAULT_BIOMETRIC_DB_PATH, BiometricTemplateStore


def _default_identity_db_path() -> str:
    """Gleicher Default wie peoplectl.py::_default_db_path() -- bewusst
    hier dupliziert statt importiert (gleiches Prinzip: dieses Modul
    soll unabhaengig von peoplectl.py aenderbar bleiben)."""
    import os
    return os.path.expanduser("~/.ihk_pepper_memory/identity.db")


def _open_registry(args) -> IdentityRegistryStore:
    return IdentityRegistryStore(args.identity_db_path)


def _open_biometric_store(args) -> BiometricTemplateStore:
    return BiometricTemplateStore(args.biometric_db_path)


def cmd_status(args):
    registry_ok = True
    registry_error = ""
    try:
        registry = _open_registry(args)
        registry_count = len(registry.list_all())
        registry.close()
    except Exception as e:
        registry_ok = False
        registry_error = str(e)
        registry_count = 0

    store_ok = True
    store_error = ""
    try:
        store = _open_biometric_store(args)
        template_count = len(store.all_person_ids())
        store.close()
    except Exception as e:
        store_ok = False
        store_error = str(e)
        template_count = 0

    print(f"identity_db_path:    {args.identity_db_path}")
    print(f"identity_registry:   {'erreichbar' if registry_ok else 'NICHT erreichbar: ' + registry_error}")
    print(f"registrierte_personen: {registry_count}")
    print(f"biometric_db_path:   {args.biometric_db_path}")
    print(f"biometric_store:     {'erreichbar' if store_ok else 'NICHT erreichbar: ' + store_error}")
    print(f"gespeicherte_templates: {template_count}")
    return 0 if (registry_ok and store_ok) else 1


def cmd_list(args):
    registry = _open_registry(args)
    store = _open_biometric_store(args)
    try:
        person_ids = store.all_person_ids()
        if not person_ids:
            print("Keine biometrischen Vorlagen vorhanden.")
            return 0
        for person_id in person_ids:
            record = registry.lookup(person_id)
            consent = record.consent_status if record is not None else "unbekannt_in_registry"
            print(f"{person_id:20s} consent={consent}")
        return 0
    finally:
        registry.close()
        store.close()


def cmd_revoke(args):
    registry = _open_registry(args)
    try:
        if registry.lookup(args.person_id) is None:
            print(f"Unbekannte person_id: {args.person_id}", file=sys.stderr)
            return 1
        registry.set_consent(args.person_id, ConsentStatus.WITHDRAWN.value, reason=args.reason)
        print(
            f"OK: Einwilligung fuer {args.person_id} widerrufen -- das gespeicherte "
            f"Template bleibt bestehen, wird aber ab sofort NICHT mehr zum Abgleich "
            f"geladen (siehe face_identity_node.py::_template_candidates())."
        )
        return 0
    finally:
        registry.close()


def cmd_delete(args):
    if not args.yes:
        print(
            "Abgebrochen -- --yes fehlt (Loeschung des Templates ist unwiderruflich).",
            file=sys.stderr,
        )
        return 1
    store = _open_biometric_store(args)
    try:
        deleted = store.delete_template(args.person_id)
        if not deleted:
            print(f"Kein Template fuer person_id: {args.person_id}", file=sys.stderr)
            return 1
        print(f"OK: Template fuer {args.person_id} geloescht.")
        return 0
    finally:
        store.close()


def cmd_validate_store(args):
    """Auftrag Abschnitt 7: 'ein nicht entschluesselbarer Store muss
    fail-closed behandelt werden' -- versucht, JEDES gespeicherte
    Template zu entschluesseln, meldet aber niemals dessen Inhalt."""
    try:
        store = _open_biometric_store(args)
    except Exception as e:
        print(f"FEHLER: biometrischer Speicher nicht oeffenbar: {e}", file=sys.stderr)
        return 1
    try:
        person_ids = store.all_person_ids()
        if not person_ids:
            print("Keine Vorlagen zum Pruefen vorhanden.")
            return 0
        ok_count = 0
        bad_ids = []
        for person_id in person_ids:
            if store.get_template(person_id) is not None:
                ok_count += 1
            else:
                bad_ids.append(person_id)
        print(f"{ok_count}/{len(person_ids)} Vorlagen entschluesselbar/gueltig.")
        if bad_ids:
            print(
                f"NICHT entschluesselbar oder abgelaufen: {', '.join(bad_ids)}",
                file=sys.stderr,
            )
            return 1
        return 0
    finally:
        store.close()


def cmd_enroll(args):
    """Ruft /enroll_person auf face_identity_node.py auf -- braucht
    ein laufendes ROS2-System (Auftrag Abschnitt 7: 'aktuelle
    Kameradaten vorliegen'), das ist der einzige Unterbefehl dieses
    Werkzeugs, der das tut."""
    import rclpy
    from rclpy.node import Node

    from ihk_pepper_interfaces.srv import EnrollPerson

    rclpy.init(args=None)
    try:
        node = Node("identityctl")
        client = node.create_client(EnrollPerson, "/enroll_person")
        if not client.wait_for_service(timeout_sec=3.0):
            print(
                "FEHLER: face_identity_node ist nicht erreichbar (/enroll_person). "
                "Laeuft der Node?", file=sys.stderr,
            )
            return 1
        request = EnrollPerson.Request()
        request.person_id = args.person_id
        request.timeout_s = float(args.timeout_s)
        request.reason = args.reason
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=args.timeout_s + 5.0)
        if not future.done():
            print("FEHLER: Einschreibungsanfrage nicht beantwortet (Zeitueberschreitung).",
                  file=sys.stderr)
            return 1
        response = future.result()
        if response.success:
            print(f"OK: {args.person_id} eingeschrieben ({response.frames_collected} Beobachtungen).")
            return 0
        print(f"Abgelehnt: {response.reason} ({response.frames_collected} Beobachtungen).",
              file=sys.stderr)
        return 1
    finally:
        rclpy.shutdown()


def build_parser():
    parser = argparse.ArgumentParser(prog="identityctl", description=__doc__)
    parser.add_argument("--identity-db-path", default=_default_identity_db_path())
    parser.add_argument("--biometric-db-path", default=DEFAULT_BIOMETRIC_DB_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="Erreichbarkeit/Anzahl von Registry und biometrischem Speicher")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("list", help="alle gespeicherten biometrischen Vorlagen auflisten")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("enroll", help="Einschreibungssitzung starten (braucht laufenden face_identity_node)")
    p.add_argument("--person-id", required=True)
    p.add_argument("--timeout-s", type=float, default=20.0)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_enroll)

    p = sub.add_parser("revoke", help="Einwilligung widerrufen (Template bleibt gespeichert)")
    p.add_argument("--person-id", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("delete", help="Template unwiderruflich loeschen")
    p.add_argument("--person-id", required=True)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("validate-store", help="alle Vorlagen auf Entschluesselbarkeit pruefen")
    p.set_defaults(func=cmd_validate_store)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
