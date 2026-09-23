#!/usr/bin/env bash
# Shared helpers for Ubuntu guest provisioning phases.
set -euo pipefail

glog() { printf '[guest %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

apt_q() { sudo DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Use-Pty=0 "$@"; }
