#!/usr/bin/env bash
# ==============================================================================
# ET4242 Internet of Things - Practical 05: Python and MySQL Lab Automation Setup
# Author: Automated Lab Setup
# Target Environment: Ubuntu / Debian Linux (Laptop or Raspberry Pi)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================================="
echo "    ET4242 Practical 05: Automated Environment & Database Setup   "
echo "=================================================================="

# 1. Install System Dependencies (MariaDB & Python venv)
echo "[1/6] Checking system packages..."
if ! command -v mariadb &> /dev/null || ! command -v mysql &> /dev/null; then
    echo ">> Installing MariaDB server and client..."
    sudo apt update
    sudo apt install -y mariadb-server mariadb-client python3-venv python3-pip
else
    echo ">> MariaDB is already installed."
fi

# 2. Ensure MariaDB service is running
echo "[2/6] Starting MariaDB service..."
if ! systemctl is-active --quiet mariadb; then
    sudo systemctl start mariadb
fi
echo ">> MariaDB service is active."

# 3. Configure passwordless sudo for MariaDB service control (Required for Part 2 Fault Injection)
echo "[3/6] Ensuring sudoers rules for MariaDB service manipulation..."
SUDOERS_FILE="/etc/sudoers.d/mariadb-service"
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "$USER ALL=(ALL) NOPASSWD: /bin/systemctl stop mariadb, /bin/systemctl start mariadb, /bin/systemctl restart mariadb, /bin/systemctl status mariadb, /usr/bin/systemctl stop mariadb, /usr/bin/systemctl start mariadb, /usr/bin/systemctl restart mariadb, /usr/bin/systemctl status mariadb, /usr/bin/mariadb" | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "$SUDOERS_FILE"
fi
echo ">> Sudoers configured at $SUDOERS_FILE."

# 4. Initialize Database Schema, Constraints & Least-Privilege Users
echo "[4/6] Initializing MariaDB schema and user privileges..."
sudo mariadb < "$SCRIPT_DIR/init_db.sql"

# 5. Set Up Python Virtual Environment
echo "[5/6] Setting up Python virtual environment (.venv)..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r "$SCRIPT_DIR/requirements.txt" --quiet

# 6. Ensure db.ini permissions (chmod 600)
echo "[6/6] Securing credentials file db.ini..."
chmod 600 "$SCRIPT_DIR/db.ini"

# Verify connectivity
echo ""
echo ">> Testing database connections..."
python -c "
import db
conn_w = db.get_connection('writer')
conn_r = db.get_connection('reader')
assert conn_w.is_connected(), 'Writer connection failed'
assert conn_r.is_connected(), 'Reader connection failed'
conn_w.close()
conn_r.close()
print('>> [SUCCESS] Both iot_writer and iot_reader connected successfully!')
"

echo ""
echo "=================================================================="
echo " [SUCCESS] Practical 05 setup is complete and fully operational!  "
echo " You can now follow the Step-by-Step Execution Guide in           "
echo " PRACTICAL_05_PLAN_AND_APPROACH.md                                "
echo "=================================================================="
