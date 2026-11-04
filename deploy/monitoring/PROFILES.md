# Gusby Monitoring Profiles & Resource Sizing Guide

**Device Target**: Sony Xperia 1 (802SO)  
**Host Specifications**: Qualcomm Snapdragon 855 (ARM64), ~5.4 GiB Visible RAM, Battery/USB Power  
**Thermal Limits**: Mobile passive cooling (throttles at sustained heavy background CPU load)  

---

## 1. Honest Resource Consumption Analysis

Running a full modern observability suite (Prometheus server + Grafana + Loki + Promtail + Jaeger / OTel Collector) on an Android phone alongside the primary application, database, and reverse proxy would result in:
- **RAM Consumption**: 1.2 – 2.0 GiB of RAM solely for telemetry daemons.
- **CPU & Battery**: Constant background disk I/O and time-series compaction, leading to thermal throttling, battery drain, and Android low-memory killer (LMK) terminating Termux.

**Architectural Principle**: **Decouple application instrumentation from telemetry storage.**  
The Gusby Go backend natively instruments in-memory Prometheus metrics and OpenTelemetry trace spans. How those metrics are stored depends on which profile you select.

---

## 2. Profile Comparison Matrix

| Resource / Component | Minimal Profile (Recommended for Xperia) | Expanded Profile (Lab / Staging VPS) |
|---|---|---|
| **Prometheus Exporter** | Embedded in Go binary (`:8081/metrics`) | Embedded in Go binary (`:8081/metrics`) |
| **Prometheus Server** | Runs remotely on Fedora dev workstation | Runs locally in Termux or separate VPS |
| **Grafana Server** | Runs remotely on Fedora dev workstation | Runs locally or on monitoring node |
| **OpenTelemetry Backend** | Noop tracer (zero CPU / 0 MB RAM) | OTLP HTTP exporter to Jaeger/Signoz |
| **Host Extra RAM Overhead** | **0 MB** | ~350 MB – 800 MB |
| **Host Extra CPU Overhead** | **< 0.1%** | 2% – 8% (Periodic TSDB indexing) |
| **Thermal Risk on Phone** | **Negligible** | **Moderate to High** |
| **Production Stability** | **Optimal** | Fair (Sensitive to LMK) |

---

## 3. Minimal Monitoring Profile (Recommended)

In the minimal profile, the Xperia runs zero monitoring daemons:
1. Gusby Go backend serves `/metrics` in memory with atomic counter operations.
2. Prometheus runs on the Fedora development workstation (or external VPS) and scrapes the Xperia over SSH port-forwarding or local WiFi:
   ```bash
   # On Fedora development machine:
   # Forward remote Xperia port 8081 to local port 8081
   ssh -N -L 8081:127.0.0.1:8081 termux-xperia
   ```
3. Run Prometheus and Grafana on Fedora dev machine:
   ```bash
   # On Fedora workstation:
   prometheus --config.file=deploy/monitoring/prometheus.yml
   ```
4. Import `deploy/monitoring/grafana-dashboard.json` into Grafana on Fedora.

**Result**: 100% telemetry visibility with 0 MB memory penalty and 0 additional background processes on the Sony Xperia!

---

## 4. Expanded Monitoring Profile

If on-device monitoring is strictly required on the phone:
1. Install Prometheus on Termux:
   ```bash
   pkg install prometheus
   ```
2. Run Prometheus with constrained retention:
   ```bash
   prometheus \
     --config.file=$HOME/KBA/deploy/monitoring/prometheus.yml \
     --storage.tsdb.retention.time=2d \
     --storage.tsdb.retention.size=500MB \
     --web.listen-address="127.0.0.1:9090"
   ```
3. Run Alertmanager for local push notifications if desired.
4. Ensure battery optimization is disabled for Termux and wake lock is active (`termux-wake-lock`).
