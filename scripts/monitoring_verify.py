#!/usr/bin/env python3
"""Verify monitoring via private port-forwards; never emit credentials or target URLs."""
import argparse
import base64
import contextlib
from datetime import datetime, timedelta, timezone
import json
import re
import selectors
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from doppler_runtime import Cluster
from redis_pki import get


@contextlib.contextmanager
def forward(cluster, service, port):
    process = subprocess.Popen(cluster.prefix + ["-n", "monitoring", "port-forward", "svc/" + service,
                               "--address=127.0.0.1", ":" + str(port)], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, env=cluster.environment)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=20), "Port-forward not ready"
            match = re.search(r"127\.0\.0\.1:(\d+)", process.stdout.readline())
            assert match, "Port-forward failed"
        yield "http://127.0.0.1:" + match.group(1)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


def request(base, path, data=None, auth=None, raw=False):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
    req = urllib.request.Request(base + path, headers=headers,
                                 data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(req, timeout=20) as response:
        body = response.read().decode()
        return body if raw else json.loads(body) if body else None


def query(base, expression):
    result = request(base, "/api/v1/query?" + urllib.parse.urlencode({"query": expression}))
    assert result["status"] == "success", "Prometheus query failed"
    return result["data"]["result"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-config", required=True)
    parser.add_argument("--send-test-alert", action="store_true")
    args = parser.parse_args()
    with open(args.run_config) as source:
        cluster = Cluster(json.load(source))
    with contextlib.ExitStack() as stack:
        prom = stack.enter_context(forward(cluster, "monitoring-kube-prometheus-prometheus", 9090))
        alert = stack.enter_context(forward(cluster, "monitoring-kube-prometheus-alertmanager", 9093))
        grafana = stack.enter_context(forward(cluster, "monitoring-grafana", 80))
        targets = request(prom, "/api/v1/targets")["data"]["activeTargets"]
        down = [t for t in targets if t["health"] != "up"]
        print(json.dumps({"targets_total": len(targets), "targets_down": len(down),
                          "down_jobs": sorted({t["labels"].get("job", "unknown") for t in down})}), flush=True)
        assert targets and not down, "Some scrape targets are down"
        for metric in ["node_memory_MemAvailable_bytes", "kube_pod_info", "container_memory_working_set_bytes", "cnpg_collector_up"]:
            assert query(prom, metric), "Required metric missing: " + metric
        alerts = request(alert, "/api/v2/alerts")
        assert any(a["labels"].get("alertname") == "Watchdog" for a in alerts), "Prometheus-to-Alertmanager delivery not verified"
        auth = get("infrastructure", "GRAFANA_ADMIN_USER") + ":" + get("infrastructure", "GRAFANA_ADMIN_PASSWORD")
        assert request(grafana, "/api/health")["database"] == "ok", "Grafana database unhealthy"
        try:
            request(grafana, "/api/search")
            raise AssertionError("Anonymous dashboard access accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 401, "Unexpected anonymous access response"
        dashboards = request(grafana, "/api/search?type=dash-db", auth=auth)
        assert dashboards, "Grafana dashboards missing"
        assert request(grafana, "/api/datasources/uid/prometheus/health", auth=auth)["status"] == "OK", "Grafana datasource failed"
        print(json.dumps({"grafana_login": True, "anonymous_denied": True, "dashboards": len(dashboards),
                          "datasource_healthy": True, "prometheus_alertmanager_delivery": True}), flush=True)
        if args.send_test_alert:
            def successful_notifications():
                metrics = request(alert, "/metrics", raw=True)
                total = sum(float(line.rsplit(" ", 1)[1]) for line in metrics.splitlines()
                            if line.startswith("alertmanager_notifications_total{") and 'integration="slack"' in line)
                failed = sum(float(line.rsplit(" ", 1)[1]) for line in metrics.splitlines()
                             if line.startswith("alertmanager_notifications_failed_total{") and 'integration="slack"' in line)
                return total - failed
            before = successful_notifications()
            now = datetime.now(timezone.utc)
            payload = [{"labels": {"alertname": "MonitoringIntegrationTest", "severity": "info", "namespace": "monitoring"},
                        "annotations": {"summary": "K3s Alertmanager → Slack 연결 테스트입니다. 실제 장애가 아닙니다."},
                        "startsAt": now.isoformat(), "endsAt": (now + timedelta(minutes=2)).isoformat()}]
            request(alert, "/api/v2/alerts", data=payload)
            try:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if successful_notifications() > before:
                        print(json.dumps({"slack_notification_success": True}), flush=True)
                        break
                    time.sleep(3)
                else:
                    raise AssertionError("Slack notification was not confirmed")
            finally:
                payload[0]["endsAt"] = datetime.now(timezone.utc).isoformat()
                request(alert, "/api/v2/alerts", data=payload)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # HTTP/connection errors may include confidential endpoints; do not print raw exceptions.
        print("Monitoring verification failed: " + type(error).__name__ + "; sensitive details suppressed", flush=True)
        raise SystemExit(1)
