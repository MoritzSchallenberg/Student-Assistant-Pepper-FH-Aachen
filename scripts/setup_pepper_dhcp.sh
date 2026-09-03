#!/bin/bash
# Richtet auf eno1 (Kabel zu Pepper) einen festen DHCP-Reservierungs-Server ein,
# damit Pepper bei jedem Neustart/Neuverbinden immer dieselbe IP bekommt.
set -e

PEPPER_MAC="00:13:95:1f:49:1b"
PEPPER_IP="192.168.100.50"
PC_IP="192.168.100.1"

echo "== 1/4: dnsmasq-Zusatzregel fuer feste Pepper-IP anlegen =="
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
sudo tee /etc/NetworkManager/dnsmasq-shared.d/pepper.conf > /dev/null <<EOF
dhcp-host=${PEPPER_MAC},${PEPPER_IP},pepper,infinite
EOF

echo "== 2/4: Alte eno1-Verbindungsprofile (falls vorhanden) entfernen =="
sudo nmcli connection delete eno1-pepper 2>/dev/null || true

echo "== 3/4: Neues 'Shared'-Verbindungsprofil fuer eno1 anlegen =="
sudo nmcli connection add type ethernet ifname eno1 con-name eno1-pepper \
    ipv4.method shared ipv4.addresses ${PC_IP}/24

echo "== 4/4: Verbindung aktivieren =="
sudo nmcli connection up eno1-pepper

echo
echo "Fertig. PC-Seite: ${PC_IP}, Pepper wird beim naechsten DHCP-Request ${PEPPER_IP} bekommen."
echo "WICHTIG: Damit Pepper das mitbekommt, jetzt bitte kurz das Ethernet-Kabel an"
echo "Pepper (oder am PC) einmal abziehen und wieder einstecken -- oder Pepper neu starten."
