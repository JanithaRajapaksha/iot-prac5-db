#!/usr/bin/env bash
# ==============================================================================
# ET4242 Internet of Things - Practical 05: Python and MySQL Lab Automation Setup
# Target Environment: Ubuntu / Debian Linux (Laptop or Raspberry Pi)
# Usage: ./setup.sh [--venv]
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Parse CLI options
CREATE_VENV=false
for arg in "$@"; do
    case "$arg" in
        --venv|-v)
            CREATE_VENV=true
            ;;
        --help|-h)
            echo "Usage: ./setup.sh [--venv]"
            echo ""
            echo "Options:"
            echo "  --venv, -v    Create and configure a local Python virtual environment (.venv)."
            echo "                (Default: skip venv creation and use current Python environment)"
            echo "  --help, -h    Show this help message."
            exit 0
            ;;
        *)
            echo "Unknown option: $arg (Use --help for usage)"
            exit 1
            ;;
    esac
done

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

# 4. Initialize Database Schema & Sync Passwords from db.ini
echo "[4/6] Initializing schema and syncing passwords from db.ini..."
if [ ! -f "$SCRIPT_DIR/db.ini" ]; then
    echo ">> db.ini not found. Creating from db.ini.example..."
    cp "$SCRIPT_DIR/db.ini.example" "$SCRIPT_DIR/db.ini"
fi
chmod 600 "$SCRIPT_DIR/db.ini"

# Read passwords from db.ini (Single Source of Truth)
WRITER_PASS=$(python3 -c "import configparser; c=configparser.ConfigParser(); c.read('$SCRIPT_DIR/db.ini'); print(c['writer']['password'])")
READER_PASS=$(python3 -c "import configparser; c=configparser.ConfigParser(); c.read('$SCRIPT_DIR/db.ini'); print(c['reader']['password'])")

# Run schema DDL
sudo mariadb < "$SCRIPT_DIR/init_db.sql"

# Configure MariaDB users with the passwords from db.ini
sudo mariadb -e "
CREATE OR REPLACE USER 'iot_writer'@'localhost' IDENTIFIED BY '$WRITER_PASS';
CREATE OR REPLACE USER 'iot_reader'@'localhost' IDENTIFIED BY '$READER_PASS';

GRANT SELECT ON iot_lab.devices TO 'iot_writer'@'localhost';
GRANT SELECT, INSERT, UPDATE ON iot_lab.sensor_readings TO 'iot_writer'@'localhost';
GRANT SELECT ON iot_lab.* TO 'iot_reader'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE, ALTER, INDEX ON iot_lab.bench_readings TO 'iot_writer'@'localhost';

FLUSH PRIVILEGES;
"
echo ">> Synchronized MariaDB user passwords with db.ini."

# 5. Python Environment & Dependency Installation
if [ "$CREATE_VENV" = true ]; then
    echo "[5/6] Creating Python virtual environment (.venv) as requested (--venv)..."
    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
    fi
    source .venv/bin/activate
    PYTHON_CMD="python"
    PIP_CMD="pip"
else
    echo "[5/6] Skipping .venv creation (default)."
    if [ -n "$VIRTUAL_ENV" ]; then
        echo ">> Detected already-active environment: $VIRTUAL_ENV"
        PYTHON_CMD="python"
        PIP_CMD="pip"
    else
        echo ">> Using current Python environment (pass '--venv' if you want a local .venv created)."
        PYTHON_CMD="python3"
        PIP_CMD="python3 -m pip"
    fi
fi

echo ">> Installing/verifying dependencies from requirements.txt..."
$PIP_CMD install -r "$SCRIPT_DIR/requirements.txt" --quiet

# 6. Ensure db.ini permissions (chmod 600)
echo "[6/6] Securing credentials file db.ini..."
chmod 600 "$SCRIPT_DIR/db.ini"

# Verify connectivity
echo ""
echo ">> Testing database connections..."
$PYTHON_CMD -c "
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
