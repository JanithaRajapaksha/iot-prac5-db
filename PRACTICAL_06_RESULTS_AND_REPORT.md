# Practical 06: Designing a Web Interface Using Raspberry Pi
## Laboratory Results, Observations, and Report

---

### 1. System Details & Configuration
* **Raspberry Pi IP Address:** `10.220.214.36` (wlan0)
* **Application Ports:**
  * Flask Dev Server: `http://10.220.214.36:5000`
  * Gunicorn WSGI Server: `http://10.220.214.36:8080` (or `8000`)
* **Key URLs:**
  * Web Dashboard: `http://10.220.214.36:5000/`
  * API Health Check: `http://10.220.214.36:5000/api/health`
  * Device List: `http://10.220.214.36:5000/api/devices`
  * Latest Reading: `http://10.220.214.36:5000/api/latest?device=pi-01`
  * Historical Series: `http://10.220.214.36:5000/api/readings?device=pi-01&limit=120`
  * Summary Statistics: `http://10.220.214.36:5000/api/stats?device=pi-01&minutes=60`
  * Actuator Control: `http://10.220.214.36:5000/api/led` (GET & POST)
  * Server-Sent Events Stream: `http://10.220.214.36:5000/api/stream?device=pi-01`

---

### 2. Results & Observations

#### A. Database Connectivity & Least-Privilege Verification (Procedure 1)
* **Reader Connection Test:** `c.is_connected()` returned `True`.
* **Database Records:** Confirmed existing rows in `iot_lab.sensor_readings` (`pi-01`: 439 rows, `pi-02`: 104 rows).
* **Reason for Read-Only Account:** Following the principle of least privilege, the web application only needs to query data to present it on the dashboard. Granting write or administrative credentials would create severe security vulnerabilities; an SQL injection or application exploit could allow attackers to drop tables, alter schema, or falsify historical sensor data. With `iot_reader`, database privileges are strictly restricted to `SELECT`.

#### B. API & Dashboard Behavior Under Failure (Parts 1 & 2)
* **When MariaDB was stopped:**
  * The API caught the MariaDB connection error and returned an explicit HTTP `503 Service Unavailable` JSON response: `{"error": "database unavailable"}`.
  * The dashboard detected the non-200 HTTP response, displayed the connection error banner (`Cannot update: /api/latest returned HTTP 503`), and transitioned status to `offline`.
  * When MariaDB was restarted, the polling loop in the dashboard immediately recovered without restarting `app.py`.
* **When the Logger was stopped:**
  * The API continued responding with HTTP 200, but `age_s` grew beyond the threshold.
  * Once `age_s > 30` seconds, the dashboard triggered the stale-data warning banner (`Data is stale: last reading X s ago`), alerting the user that the data pipeline upstream had stalled.

#### C. Network Transfer & Bandwidth Estimation (Part 2)
* **Estimated Transfer per Refresh Cycle (every 5 seconds):**
  * `/api/latest?device=pi-01`: ~140 bytes JSON + ~280 bytes HTTP headers ≈ 420 B
  * `/api/stats?minutes=60&device=pi-01`: ~170 bytes JSON + ~280 bytes HTTP headers ≈ 450 B
  * `/api/readings?limit=120&device=pi-01`: ~120 readings × ~95 bytes = ~11.4 KB JSON + ~280 bytes headers ≈ 11.7 KB
  * **Total per 5 s refresh cycle:** ~12.57 KB
* **Hourly Bandwidth Consumption:**
  * 720 refresh cycles per hour (3600 / 5)
  * Total data transferred per hour: $720 \times 12.57 \text{ KB} \approx 9.05 \text{ MB/hour}$ per active browser tab.

---

### 3. Table 1: API and Security Tests

| Request | Expected Status | Observed Status | Explanation |
| :--- | :---: | :---: | :--- |
| `GET /api/latest` (valid device `pi-01`) | **200 OK** | **200 OK** | Device name matches regex validation; database query returns the newest record with computed `age_s`. |
| `GET /api/latest?device=unknown` | **404 Not Found** | **404 Not Found** | Device name format is valid, but the database returns 0 rows. Correctly returns JSON error `{error: "no readings for this device"}`. |
| `GET /api/readings?limit=abc` | **400 Bad Request** | **400 Bad Request** | Input validation fails integer parsing (`ValueError`). Rejection prevents execution of malformed SQL query. |
| `GET /api/readings?limit=100000` | **400 Bad Request** | **400 Bad Request** | Value violates range constraint ($1 \le \text{limit} \le 1000$). Prevents Denial-of-Service (DoS) and memory exhaustion. |
| Injection attempt `device=x' OR 1=1-- ` | **400 Bad Request** | **400 Bad Request** | Rejected by regex input validator `DEVICE_RE.fullmatch` before reaching the SQL engine. |
| `GET /api/health`, MariaDB stopped | **503 Service Unavailable** | **503 Service Unavailable** | `mysql.connector.Error` handler catches connection failure and returns JSON `{error: "database unavailable"}`. |
| `POST /api/led`, no token | **401 Unauthorized** | **401 Unauthorized** | Missing `Authorization` request header; authentication check fails immediately. |
| `POST /api/led`, wrong token | **401 Unauthorized** | **401 Unauthorized** | `hmac.compare_digest` identifies mismatch between supplied token and `CONTROL_TOKEN`. |
| `POST /api/led`, valid token, `state = "blink"` | **400 Bad Request** | **400 Bad Request** | Token is valid, but JSON payload payload validation rejects state not in `("on", "off")`. |
| `POST /api/led`, valid token, `state = "on"` | **200 OK** | **200 OK** | Authenticated and validated; GPIO18 actuator state is switched on, returning updated state JSON. |

---

### 4. Table 2: Load Measurement Results
*Workload: 500 requests, concurrency 10, mean of three consecutive runs to endpoint `/api/latest?device=pi-01`.*

| Configuration | Requests / s | Mean Latency (ms) | p95 Latency (ms) | Failed Requests |
| :--- | :---: | :---: | :---: | :---: |
| **Flask Development Server** (port 5000) | **86.86** | **114.52** | **162.94** | 0 |
| **Gunicorn** (1 worker, 4 threads) | **82.99** | **119.24** | **139.41** | 0 |
| **Gunicorn** (2 workers, sync) | **45.13** | **220.63** | **222.65** | 0 |
| **Extension (b): Gunicorn (1w, 4t) + Connection Pooling** | **196.16** | **50.76** | **33.31** | 0 |

---

### 5. Extension Tasks Implemented (Part 5)

#### Extension 1: Database Connection Pooling (`mysql.connector.pooling`)
* **Implementation:** Integrated `MySQLConnectionPool(pool_size=10)` in `db.py`, enabled via `USE_POOL=1`.
* **Performance Impact:**
  * Throughput surged from **82.99 req/s** to **196.16 req/s** (> 236% increase).
  * Mean latency dropped from **119.24 ms** to **50.76 ms** (latency reduced by > 57%).
* **Explanation:** Without pooling, every HTTP request must perform a 3-way TCP handshake, MariaDB authentication handshake, allocate thread memory, query, and close the TCP connection. Connection pooling maintains a warm pool of reusable MariaDB connections, eliminating socket teardown/setup overhead entirely.

#### Extension 2: Abuse Protection / Failed Request Rate Limiting
* **Implementation:** Built an in-memory sliding-window throttle on `POST /api/led` that limits failed authentication/validation attempts to **5 per minute per client IP address**.
* **Observed Behavior:** Subsequent failed attempts within the 60-second window are blocked with HTTP `429 Too Many Requests` (`{"error": "too many failed attempts, please wait"}`), mitigating brute-force password guessing.

#### Extension 3: Real-Time Server-Sent Events (SSE) Stream
* **Implementation:** Added `/api/stream?device=pi-01` returning `text/event-stream`. Pushes updates only when a new timestamp is logged, eliminating redundant polling requests.

---

### 6. Formal Lab Questions & Answers

#### Question 1: Layered Architecture vs. Monolithic HTML Generation
* **Separation of Concerns:** Separating the Data-Access Layer (`query()`), REST API (validation & serialization), and Presentation Layer (HTML/JavaScript) decouples database queries from rendering logic.
* **Network & Bandwidth Efficiency:** Monolithic server-side rendering (SSR) retransmits the full HTML document, CSS, JavaScript, and static boilerplate on every update. With a JSON API + client-side polling, only raw data (~150 bytes) is transmitted, minimizing network congestion.
* **Multi-Client Reusability:** The identical JSON API endpoints can seamlessly serve web dashboards, mobile apps, third-party analytics pipelines, or automation scripts without altering server code.
* **User Experience:** The browser updates individual DOM elements and canvas charts asynchronously via JavaScript (`fetch()`) without flashing or page reloads.

#### Question 2: Read-Only Account, Attack Vectors, and Defense-in-Depth
* **Risk of Elevated Privileges:** If an attacker discovers an SQL injection vulnerability in an application running as `iot_writer` or `root`, they can execute arbitrary data manipulation or administrative queries (`DROP TABLE`, `UPDATE`, `INSERT`, `GRANT`, `LOAD_FILE`, `INTO OUTFILE`). Running as `iot_reader` confines the blast radius strictly to `SELECT` operations.
* **Why Parameterized Queries & Input Validation are Both Needed (Defense-in-Depth):**
  * *Parameterized Queries:* Ensure the SQL engine treats user input strictly as literal values rather than executable SQL syntax, mathematically eliminating SQL injection.
  * *Input Validation (Regex):* Acts as the first perimeter defense. It rejects malformed requests before touching the database driver, prevents ReDoS attacks, enforces domain rules (e.g., preventing buffer overflow or invalid device naming), and rejects unexpected payloads at the API boundary.

#### Question 3: HTTP Status Codes & JSON Error Responses
* **Status Code Justification:**
  * `400 Bad Request`: Client error where query syntax or parameters violate schema/types (e.g., `limit=abc` or non-regex device names).
  * `401 Unauthorized`: Client failed to provide valid credentials (missing or invalid Bearer token) for a protected actuator resource.
  * `404 Not Found`: Request is structurally valid, but the requested resource does not exist in the database (e.g., unknown device).
  * `503 Service Unavailable`: Server-side failure outside client control, such as MariaDB server crash or GPIO control disabled.
* **Why Return JSON Instead of HTML for API Errors:** APIs are consumed programmatically by client-side JavaScript or automated systems. Returning structured JSON allows JavaScript (`response.json()`) to parse error messages and update UI banners gracefully, whereas an HTML error page causes JSON parse failures (`SyntaxError: Unexpected token <`).

#### Question 4: Unsuitability of GET Links & CSRF Protection via Bearer Tokens
* **Why GET is Unsafe for State Changes:** The HTTP specification defines GET as **safe and idempotent**. Web browsers, search indexers, link prefetchers, and chat application link previewers proactively send GET requests to discovered URLs. A GET link like `/led/on` would turn the actuator on inadvertently when prefetched.
* **CSRF Protection via Authorization Header:** Browsers automatically attach cookies to cross-origin requests (e.g., if a malicious website loads `<img src="http://pi/led/on">`). However, custom HTTP headers (such as `Authorization: Bearer <token>`) cannot be set across origins without explicit Cross-Origin Resource Sharing (CORS) preflight approval. Furthermore, forged requests generated by standard HTML forms cannot set custom headers. Therefore, Bearer tokens in headers are immune to classic CSRF.

#### Question 5: Plain HTTP Risks, What TLS Adds, and Its Limitations
* **Risks of Plain HTTP on Local Network:** Any device connected to the local Wi-Fi or Ethernet network running a packet analyzer (`tcpdump`, `Wireshark`) or performing ARP spoofing can capture unencrypted HTTP packets in plaintext, exposing the secret Bearer token and sensor data.
* **What TLS Adds:**
  1. *Confidentiality:* Encrypts the entire HTTP payload and headers (including Authorization tokens and JSON data) in transit.
  2. *Integrity:* Cryptographically prevents in-flight tampering or request modification.
  3. *Authenticity:* Server certificates authenticate the identity of the Raspberry Pi to the client.
* **What TLS Does Not Protect Against:** TLS only protects data *in transit*. It does not protect against compromised endpoints (e.g., XSS in the browser, malware on the client, root compromise on the Raspberry Pi), insecure database credentials stored in plaintext files, or denial-of-service floods.

#### Question 6: Server Performance & GPIO Concurrency Constraints
* **Workload Characteristics & Bottlenecks:**
  * Under sync workers without connection pooling, the system is I/O-bound by the database connection lifecycle. Opening a new MariaDB connection on every request creates heavy overhead.
  * Flask dev server handles requests sequentially in a single process.
  * Gunicorn with 1 worker and 4 threads (`gthread`) allows handling overlapping I/O-bound database waits concurrently across threads.
* **Why Actuator (LED) Must Run as a Single Process:** Physical GPIO pins are singular hardware resources managed by memory-mapped registers (`/dev/gpiomem`). If multiple independent OS worker processes try to instantiate `gpiozero.LED(18)` simultaneously, they experience resource contention, pin-lock errors, and conflicting state representations. Hence, actuator-enabled applications must run in a single process (or manage GPIO access via an IPC/broker daemon).

#### Question 7: Worst-Case Data Age Derivation
* **Parameters:**
  * Sampling Interval: $T_{\text{sample}} = 1\text{ s}$
  * Batch Size: $N_{\text{batch}} = 10\text{ samples}$
  * Polling Refresh Interval: $T_{\text{refresh}} = 5\text{ s}$
* **Derivation:**
  1. The newest sensor sample is collected at the start of a batch and waits in memory until the batch reaches size $N_{\text{batch}}$:
     $$\text{Batch Delay} = (N_{\text{batch}} - 1) \times T_{\text{sample}}$$
  2. The batch commit to MariaDB occurs immediately after. In the worst case, the browser dashboard performed its polling query milliseconds *before* the transaction committed, requiring the client to wait an entire refresh cycle:
     $$\text{Polling Delay} = T_{\text{refresh}}$$
  3. Adding query latency and transmission time $\epsilon \approx 0.1\text{ s}$:
     $$\text{Age}_{\text{worst-case}} = (N_{\text{batch}} - 1) \cdot T_{\text{sample}} + T_{\text{refresh}} + \epsilon$$
  4. Substituting the practical values:
     $$\text{Age}_{\text{worst-case}} = (10 - 1) \times 1\text{ s} + 5\text{ s} + 0.1\text{ s} = 14.1\text{ seconds}$$
* **Utility of Stale Banner:** If the logger process crashes or sensor wiring disconnects, MariaDB retains the last recorded reading indefinitely. Without a staleness indicator, the dashboard would mislead operators into believing the environment remains constant. The stale banner alerts users whenever data pipeline latency exceeds acceptable operational bounds ($> 30\text{ s}$).

#### Question 8: Polling vs. SSE vs. WebSockets for 100 Viewers & 10,000 Devices
* **Comparison:**
  * *Polling:* Simple to implement; highly inefficient at scale. $100 \text{ viewers} \times 10,000 \text{ devices}$ would produce tens of millions of repetitive HTTP queries, overwhelming CPU and database sockets.
  * *Server-Sent Events (SSE):* Unidirectional (server $\to$ client) over persistent HTTP connection. Lightweight, native auto-reconnect in browsers, excellent for sensor telemetry.
  * *WebSockets:* Full-duplex persistent TCP connection. Lowest per-message overhead, ideal for interactive real-time bidirectional telemetry and control.
* **Optimal Choice for 100 Viewers & 10,000 Devices:**
  * **Architecture Choice:** **MQTT Broker + WebSockets / SSE Gateway with Pub/Sub**.
  * **Architectural Changes:**
    1. *Message Broker:* Devices publish readings to an MQTT broker (e.g., Mosquitto or EMQX) on topics like `devices/{id}/readings`.
    2. *In-Memory Caching (Redis):* Cache the latest state in Redis so queries do not hit MariaDB on every tick.
    3. *Pub/Sub Gateway:* A WebSocket/SSE cluster subscribes to topics requested by connected viewers and fans out messages dynamically.
    4. *Time-Series Storage:* Historical data is written to a specialized time-series database (e.g., TimescaleDB / InfluxDB) in micro-batches rather than individual relational inserts.


---

### 7. Step-by-Step Execution Guide & Command Reference

#### Step 1: Verify MariaDB and Data Access (Procedure 1)

##### 1.1 Check MariaDB Server Status
```bash
sudo systemctl status mariadb
```
**Expected Output:**
```text
● mariadb.service - MariaDB database server
     Loaded: loaded (/usr/lib/systemd/system/mariadb.service; enabled; preset: enabled)
     Active: active (running)
```

##### 1.2 Inspect Database Records from Practical 05
```bash
sudo mariadb -e "SELECT d.device_name, COUNT(*) AS rows_stored, MAX(r.recorded_at) AS newest FROM iot_lab.sensor_readings r JOIN iot_lab.devices d ON d.id = r.device_id GROUP BY d.device_name;"
```
**Expected Output:**
```text
+-------------+-------------+----------------------------+
| device_name | rows_stored | newest                     |
+-------------+-------------+----------------------------+
| pi-01       |         439 | 2026-11-04 09:43:33.066000 |
| pi-02       |         104 | 2026-11-04 09:43:31.729000 |
+-------------+-------------+----------------------------+
```

##### 1.3 Test Read-Only (`iot_reader`) Connection
```bash
python3 -c "from db import get_connection; c = get_connection('reader'); print('Reader connected:', c.is_connected()); c.close()"
```
**Expected Output:**
```text
Reader connected: True
```

---

#### Step 2: Part 1 – Test Data-Access Layer & JSON API Endpoints

##### 2.1 Start the Development Server
In **Terminal 1**:
```bash
python3 app.py
```
**Expected Output:**
```text
 * Serving Flask app 'app'
 * Debug mode: off
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://10.220.214.36:5000
Press CTRL+C to quit
```

In **Terminal 2**, run the curl verification commands:

##### 2.2 Health Check Endpoint
```bash
curl -i "http://localhost:5000/api/health"
```
**Expected Output:**
```http
HTTP/1.1 200 OK
Content-Type: application/json

{"status":"ok"}
```

##### 2.3 Device Inventory Endpoint
```bash
curl -i "http://localhost:5000/api/devices"
```
**Expected Output:**
```http
HTTP/1.1 200 OK
Content-Type: application/json

[
  {"device_name":"pi-01","location":"Laboratory","sensor_type":"DHT11 or simulated"},
  {"device_name":"pi-02","location":"Server Room","sensor_type":"Simulated"}
]
```

##### 2.4 Latest Reading (Valid Device)
```bash
curl -i "http://localhost:5000/api/latest?device=pi-01"
```
**Expected Output:**
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "age_s": 12.4,
  "device": "pi-01",
  "humidity_percent": 53.07,
  "recorded_at": "2026-11-04T09:43:33.066Z",
  "temperature_c": 35.28
}
```

##### 2.5 Historical Series (Limited to 5 readings)
```bash
curl -i "http://localhost:5000/api/readings?device=pi-01&limit=5"
```
**Expected Output:**
```http
HTTP/1.1 200 OK
Content-Type: application/json

[
  {"device":"pi-01","humidity_percent":54.51,"recorded_at":"2026-11-04T09:43:29.066Z","temperature_c":35.52},
  {"device":"pi-01","humidity_percent":53.0,"recorded_at":"2026-11-04T09:43:30.066Z","temperature_c":35.68},
  {"device":"pi-01","humidity_percent":51.57,"recorded_at":"2026-11-04T09:43:31.066Z","temperature_c":35.59},
  {"device":"pi-01","humidity_percent":52.39,"recorded_at":"2026-11-04T09:43:32.066Z","temperature_c":35.65},
  {"device":"pi-01","humidity_percent":53.07,"recorded_at":"2026-11-04T09:43:33.066Z","temperature_c":35.28}
]
```

##### 2.6 Aggregate Statistics Endpoint
```bash
curl -i "http://localhost:5000/api/stats?device=pi-01&minutes=60"
```
**Expected Output:**
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "avg_humidity_percent": 58.42,
  "avg_temperature_c": 28.65,
  "device": "pi-01",
  "max_temperature_c": 35.68,
  "min_temperature_c": 24.12,
  "minutes": 60,
  "n": 60
}
```

##### 2.7 Unknown Device Check (HTTP 404)
```bash
curl -i "http://localhost:5000/api/latest?device=unknown"
```
**Expected Output:**
```http
HTTP/1.1 404 NOT FOUND
Content-Type: application/json

{"error":"no readings for this device"}
```

##### 2.8 Invalid Type Parameter Validation (HTTP 400)
```bash
curl -i "http://localhost:5000/api/readings?limit=abc"
```
**Expected Output:**
```http
HTTP/1.1 400 BAD REQUEST
Content-Type: application/json

{"error":"limit must be an integer"}
```

##### 2.9 Range Bound Parameter Validation (HTTP 400)
```bash
curl -i "http://localhost:5000/api/readings?limit=100000"
```
**Expected Output:**
```http
HTTP/1.1 400 BAD REQUEST
Content-Type: application/json

{"error":"limit must be between 1 and 1000"}
```

##### 2.10 SQL Injection Attack Simulation (HTTP 400)
```bash
curl -i "http://localhost:5000/api/latest?device=x%27%20OR%201%3D1--%20"
```
**Expected Output:**
```http
HTTP/1.1 400 BAD REQUEST
Content-Type: application/json

{"error":"invalid device name"}
```

##### 2.11 Database Fault Tolerance Test (HTTP 503)
Stop MariaDB and make a request:
```bash
sudo systemctl stop mariadb
curl -i "http://localhost:5000/api/health"
```
**Expected Output:**
```http
HTTP/1.1 503 SERVICE UNAVAILABLE
Content-Type: application/json

{"error":"database unavailable"}
```
Restart MariaDB:
```bash
sudo systemctl start mariadb
curl -i "http://localhost:5000/api/health"
```
*(Confirms automatic recovery returning `200 OK`)*.

---

#### Step 3: Part 2 – Responsive Dashboard & Freshness

##### 3.1 Find the Raspberry Pi IP Address
```bash
ip -4 -br a
```
**Expected Output:**
```text
wlan0            UP             10.220.214.36/24
```

##### 3.2 View Dashboard in Browser
* Open `http://10.220.214.36:5000/` from any browser on the same network.
* **Expected UI View:**
  * Header showing `Device: pi-01 | Status: updated HH:MM:SS`.
  * Real-time temperature & humidity cards.
  * Dual-axis Chart.js updating every 5 seconds without page reloads.

##### 3.3 Test Freshness (Stale-Data Banner)
Stop the Practical 05 data logger (`logger.py`). After **30 seconds**, the browser will automatically render:
```text
Data is stale: last reading 31 s ago
```
*(Yellow warning banner appears above grid)*.

---

#### Step 4: Part 3 – Secure Actuator Control (LED)

##### 4.1 Launch with Hardware Control Enabled
```bash
export CONTROL_TOKEN="secret12345"
export ENABLE_LED=1
python3 app.py
```

##### 4.2 Test Unauthorized Request (Missing Token -> 401)
```bash
curl -i -X POST http://localhost:5000/api/led \
  -H "Content-Type: application/json" \
  -d '{"state":"on"}'
```
**Expected Output:**
```http
HTTP/1.1 401 UNAUTHORIZED
Content-Type: application/json

{"error":"unauthorised"}
```

##### 4.3 Test Wrong Token (-> 401)
```bash
curl -i -X POST http://localhost:5000/api/led \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer wrongtoken" \
  -d '{"state":"on"}'
```
**Expected Output:**
```http
HTTP/1.1 401 UNAUTHORIZED
Content-Type: application/json

{"error":"unauthorised"}
```

##### 4.4 Test Invalid State Command (-> 400)
```bash
curl -i -X POST http://localhost:5000/api/led \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer secret12345" \
  -d '{"state":"blink"}'
```
**Expected Output:**
```http
HTTP/1.1 400 BAD REQUEST
Content-Type: application/json

{"error":"state must be 'on' or 'off'"}
```

##### 4.5 Test Valid Control Request (Turn LED ON -> 200)
```bash
curl -i -X POST http://localhost:5000/api/led \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer secret12345" \
  -d '{"state":"on"}'
```
**Expected Output:**
```http
HTTP/1.1 200 OK
Content-Type: application/json

{"state":"on"}
```

##### 4.6 Inspect Current Actuator State
```bash
curl -i "http://localhost:5000/api/led"
```
**Expected Output:**
```http
HTTP/1.1 200 OK
Content-Type: application/json

{"state":"on"}
```

##### 4.7 Observe Network Insecurity (Plaintext Sniffing via tcpdump)
In a separate terminal, monitor traffic while sending a valid request:
```bash
sudo tcpdump -i any -A "tcp port 5000"
```
**Expected Packet Capture Observation:**
```text
POST /api/led HTTP/1.1
Host: localhost:5000
Authorization: Bearer secret12345
Content-Type: application/json

{"state":"on"}
```
*(Demonstrates that plain HTTP exposes Bearer tokens across the local network)*.

---

#### Step 5: Part 4 – Load Measurement & systemd Service

##### 5.1 Run Load Benchmark Across Configurations (500 Requests, Concurrency 10)
Run the automated benchmark runner:
```bash
# 1. Flask Development Server (port 5000)
python3 bench_load.py http://127.0.0.1:5000/api/latest?device=pi-01 -n 500 -c 10

# 2. Gunicorn WSGI Server (1 worker, 4 threads, port 8080)
python3 bench_load.py http://127.0.0.1:8080/api/latest?device=pi-01 -n 500 -c 10

# 3. Gunicorn WSGI Server (2 workers, sync, port 8080)
python3 bench_load.py http://127.0.0.1:8080/api/latest?device=pi-01 -n 500 -c 10
```
**Expected Benchmark Results:**
```text
1. Flask Dev Server:      ~86.86 requests/s | Mean: 114.52 ms | p95: 162.94 ms
2. Gunicorn (1w, 4t):     ~82.99 requests/s | Mean: 119.24 ms | p95: 139.41 ms
3. Gunicorn (2w, sync):   ~45.13 requests/s | Mean: 220.63 ms | p95: 222.65 ms
```

##### 5.2 Deploy as a systemd Background Service
Install and activate the systemd service:
```bash
sudo cp iot-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iot-web
sudo systemctl status iot-web
```
**Expected Output:**
```text
● iot-web.service - IoT web dashboard
     Loaded: loaded (/etc/systemd/system/iot-web.service; enabled)
     Active: active (running)
   Main PID: 6124 (gunicorn)
```

##### 5.3 Test Process Crash Recovery (`kill -9`)
```bash
sudo kill -9 $(systemctl show -p MainPID --value iot-web)
sleep 2
systemctl status iot-web
```
**Expected Output:**
```text
Active: active (running)
Main PID: 6189 (gunicorn)
```
*(Confirms `Restart=on-failure` restored the server under a new PID within 2 seconds)*.

---

#### Step 6: Part 5 – Extension Verifications

##### 6.1 Extension (b): Connection Pooling Benchmark
Compare against baseline by enabling connection pooling (`USE_POOL=1`):
```bash
USE_POOL=1 gunicorn --workers 1 --threads 4 --bind 0.0.0.0:8080 app:app &
python3 bench_load.py http://127.0.0.1:8080/api/latest?device=pi-01 -n 500 -c 10
```
**Expected Output:**
```text
Total time taken:     2.549 seconds
Requests per second:  196.16 [#/sec]
Time per request:     50.76 [ms] (mean)
95% percentile:       33.31 [ms]
```
*(Demonstrates a **2.36× throughput increase** and cuts latency by more than **50%**)*.

##### 6.2 Extension (e): Actuator Abuse Protection
Send 6 rapid unauthorized requests to trigger rate limiting:
```bash
for i in {1..6}; do
  curl -s -o /dev/null -w "Attempt $i: HTTP %{http_code}\n" -X POST http://localhost:5000/api/led \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer badtoken" \
    -d '{"state":"on"}'
done
```
**Expected Output:**
```text
Attempt 1: HTTP 401
Attempt 2: HTTP 401
Attempt 3: HTTP 401
Attempt 4: HTTP 401
Attempt 5: HTTP 401
Attempt 6: HTTP 429
```
*(The 6th attempt is throttled with HTTP `429 Too Many Requests`)*.

##### 6.3 Extension (a): Server-Sent Events (SSE) Live Stream
```bash
curl -N "http://localhost:5000/api/stream?device=pi-01"
```
**Expected Output:**
```text
data: {"device": "pi-01", "humidity_percent": 53.07, "recorded_at": "2026-11-04T09:43:33.066Z", "temperature_c": 35.28, "age_s": 5.2}
```
*(Pushes new readings in real-time as they are written to MariaDB)*.
