#!/usr/bin/env python3
"""SSH Local-Port-Forward 9559 -> Pepper:127.0.0.1:9559, per paramiko.

ACHTUNG -- dokumentierter Sackgassen-Versuch (siehe STATUS.md, Abschnitt
"Architektur-Entscheidung"): Peppers sshd hat AllowTcpForwarding aus,
der Tunnel scheitert mit "Administratively prohibited". Nicht
weiterverfolgt, SSH+qicli (pepper/qicli.py) ist der gewaehlte Weg.
Datei bleibt nur als Dokumentation der Sackgasse erhalten.
"""
import os
import sys
import socket
import select
import threading
import paramiko

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config.config as _cfg

HOST = _cfg.QI_HOST
USER = _cfg.QI_USER
PASSWORD = _cfg.QI_PW
LOCAL_PORT = 9559
REMOTE_HOST = "127.0.0.1"
REMOTE_PORT = 9559


def handler(chan, sock):
    while True:
        r, _, _ = select.select([sock, chan], [], [])
        if sock in r:
            data = sock.recv(4096)
            if not data:
                break
            chan.send(data)
        if chan in r:
            data = chan.recv(4096)
            if not data:
                break
            sock.send(data)
    chan.close()
    sock.close()


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=HOST, username=USER, password=PASSWORD, timeout=10)
    except paramiko.ssh_exception.BadAuthenticationType as e:
        if "keyboard-interactive" not in e.allowed_types:
            raise
        transport = client.get_transport()
        transport.auth_interactive(USER, lambda t, i, p: [PASSWORD for _ in p])
    transport = client.get_transport()
    print(f"SSH verbunden. Forwarde lokal :{LOCAL_PORT} -> {REMOTE_HOST}:{REMOTE_PORT} auf Pepper", flush=True)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", LOCAL_PORT))
    server.listen(5)

    try:
        while True:
            sock, addr = server.accept()
            chan = transport.open_channel("direct-tcpip", (REMOTE_HOST, REMOTE_PORT), addr)
            t = threading.Thread(target=handler, args=(chan, sock), daemon=True)
            t.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        client.close()


if __name__ == "__main__":
    main()
