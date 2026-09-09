"""
Gehaertete SSH-Verbindungsaufnahme, eigenstaendige Kopie des in
apps/web/pepper/qicli.py (Entwicklungsauftrag 4, AP2) etablierten
Musters (gleiches "deliberate duplicate over cross-package
dependency"-Idiom wie safety_topics.py -- ihk_pepper_audio kann kein
Paket ausserhalb des ROS2-Workspace importieren).

Verwendet von SshPcmTransport (respeaker_transport.py, Entwicklungsauftrag
04-B, AP6) UND von audio_source.py::PepperPulseAudioSource (dort vorher
AutoAddPolicy -- ein bestaetigter, im selben Zug behobener Fund, siehe
docs/RESPEAKER_TRANSPORT.md).

KEIN AutoAddPolicy, KEIN Standardpasswort-Fallback, KEIN
StrictHostKeyChecking=no -- ein unbekannter oder veraenderter Host-Key
wird NIE automatisch akzeptiert (RejectPolicy als Standard fuer alles,
was nicht in System- oder projekteigener known_hosts steht).
"""
import os

import paramiko


class UnknownHostKeyError(Exception):
    """Der Host-Key ist weder im System- noch im projekteigenen
    known_hosts hinterlegt -- erste Verbindung zu diesem Host, oder eine
    falsch konfigurierte known_hosts-Datei. KEIN automatisches
    Vertrauen."""


class HostKeyChangedError(Exception):
    """Der praesentierte Host-Key weicht vom hinterlegten Key ab --
    klassisches MITM-Warnsignal, niemals automatisch akzeptieren."""


def known_hosts_paths(project_known_hosts_env_var: str, project_default_path: str):
    """System- und projekteigene known_hosts-Datei, in dieser Reihenfolge
    geladen. Der Pfad der projekteigenen Datei ist ueber die uebergebene
    Umgebungsvariable konfigurierbar (jeder Aufrufer kann eine eigene
    Variable/einen eigenen Default waehlen, z.B. getrennt fuer Pepper
    selbst und den ReSpeaker)."""
    project_path = os.environ.get(project_known_hosts_env_var, project_default_path)
    return os.path.expanduser("~/.ssh/known_hosts"), project_path


def connect_hardened(
    client: paramiko.SSHClient,
    hostname: str,
    username: str,
    password: str,
    port: int = 22,
    timeout: float = 10.0,
    project_known_hosts_env_var: str = "PEPPER_KNOWN_HOSTS_PATH",
    project_default_known_hosts_path: str = "",
) -> None:
    """Verbindet ein bereits konstruiertes paramiko.SSHClient()-Objekt
    gehaertet -- wirft UnknownHostKeyError/HostKeyChangedError statt
    stillschweigend zu vertrauen. Faellt bei per-Passwort abgelehnter
    Authentifizierung auf keyboard-interactive zurueck (viele
    eingebettete sshd-Implementierungen, u.a. Peppers NAOqi-Box,
    advertisieren nur 'publickey'/'keyboard-interactive')."""
    system_known_hosts, project_known_hosts = known_hosts_paths(
        project_known_hosts_env_var, project_default_known_hosts_path)
    if os.path.exists(system_known_hosts):
        client.load_system_host_keys(system_known_hosts)
    if os.path.exists(project_known_hosts):
        client.load_host_keys(project_known_hosts)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(hostname=hostname, username=username, password=password,
                        port=port, timeout=timeout)
    except paramiko.ssh_exception.BadAuthenticationType as e:
        if "keyboard-interactive" not in e.allowed_types:
            raise
        transport = client.get_transport()

        def _handler(title, instructions, prompt_list):
            return [password for _ in prompt_list]

        transport.auth_interactive(username, _handler)
    except paramiko.BadHostKeyException as e:
        raise HostKeyChangedError(
            f"Host-Key von {hostname} hat sich geaendert (erwartet: {e.expected_key}, "
            f"tatsaechlich: {e.key})! Verbindung ABGEBROCHEN -- Key erst manuell "
            f"verifizieren, dann den ALTEN Eintrag bewusst aus {system_known_hosts} "
            f"bzw. {project_known_hosts} entfernen, niemals automatisch ueberschreiben."
        ) from e
    except paramiko.SSHException as e:
        if "not found in known_hosts" in str(e) or ("Server" in str(e) and "not in" in str(e)):
            raise UnknownHostKeyError(
                f"Host-Key von {hostname} ist weder in {system_known_hosts} noch in "
                f"{project_known_hosts} hinterlegt -- Fingerprint bewusst pruefen, "
                f"erst dann eintragen (z.B. ssh-keyscan -p {port} {hostname})."
            ) from e
        raise
