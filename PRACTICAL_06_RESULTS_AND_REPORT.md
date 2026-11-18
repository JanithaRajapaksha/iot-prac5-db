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
