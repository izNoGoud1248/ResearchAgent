import json
import subprocess
import sys
import time

import httpx

from libs.settings import Settings


class ClusterChecks:
    """Proves the cluster behaves as designed: network isolation, a real run end to end, and KEDA scaling."""

    namespace = "researchdesk"
    baseUrl = "http://localhost:8090/api"
    probeScript = (
        "import socket, sys\n"
        "try:\n"
        "    socket.create_connection((sys.argv[1], int(sys.argv[2])), 3).close(); print('open')\n"
        "except OSError:\n"
        "    print('blocked')\n"
    )

    def __init__(self):
        settings = Settings()
        self.http = httpx.Client(base_url=self.baseUrl, timeout=30)
        self.keys = {"user": settings.userApiKey.get_secret_value(), "approver": settings.approverApiKey.get_secret_value()}

    def kubectl(self, *args: str) -> str:
        return subprocess.run(
            ["kubectl", "-n", self.namespace, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
        ).stdout

    def reach(self, fromWorkload: str, host: str, port: int) -> str:
        return self.kubectl("exec", f"deploy/{fromWorkload}", "--", "python", "-c", self.probeScript, host, str(port)).strip()

    def networkPolicies(self) -> None:
        expectations = [
            ("orchestrator", "gateway", 8100, "open"),
            ("orchestrator", "factchecker", 8110, "open"),
            ("orchestrator", "search", 8101, "blocked"),
            ("orchestrator", "notes", 8102, "blocked"),
            ("factchecker", "search", 8101, "blocked"),
            ("api", "search", 8101, "blocked"),
            ("api", "gateway", 8100, "blocked"),
            ("search", "postgres", 5432, "blocked"),
            ("gateway", "search", 8101, "open"),
            ("api", "redis", 6379, "open"),
        ]
        print("network policies (from -> to: expected / actual)")
        failures = 0
        for source, host, port, expected in expectations:
            actual = self.reach(source, host, port)
            failures += actual != expected
            print(f"  {source:12} -> {host}:{port:<5} {expected:7} / {actual:7} {'' if actual == expected else 'MISMATCH'}")
        print("all as designed" if not failures else f"{failures} mismatches")

    def ask(self, question: str, role: str = "user") -> str:
        response = self.http.post("/runs", json={"question": question, "sensitive": False}, headers={"X-Api-Key": self.keys[role]})
        response.raise_for_status()
        return response.json()["runId"]

    def run(self, runId: str) -> dict:
        return self.http.get(f"/runs/{runId}", headers={"X-Api-Key": self.keys["user"]}).json()

    def endToEnd(self, question: str) -> None:
        runId = self.ask(question)
        started = time.monotonic()
        while (run := self.run(runId))["status"] not in ("completed", "rejected", "failed"):
            time.sleep(3)
        print(f"end to end: {run['status']} in {time.monotonic() - started:.0f}s, ${run['cost'].get('usd', 0):.4f}, trace {run['traceId']}")
        time.sleep(8)
        trace = httpx.get(f"http://localhost:16686/api/traces/{run['traceId']}", timeout=30).json()["data"][0]
        services = sorted({process["serviceName"] for process in trace["processes"].values()})
        print(f"jaeger: {len(trace['spans'])} spans from {services}")

    def gracefulShutdown(self) -> None:
        """Deletes an idle worker pod the way a scale-down or rollout would, and reads how it exited."""
        pod = self.kubectl("get", "pods", "-l", "app=orchestrator", "-o", "jsonpath={.items[0].metadata.name}").strip()
        follower = subprocess.Popen(
            ["kubectl", "-n", self.namespace, "logs", "-f", pod, "-c", "orchestrator"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
        )
        time.sleep(2)
        started = time.monotonic()
        self.kubectl("delete", "pod", pod, "--wait=true")
        seconds = time.monotonic() - started
        follower.wait(timeout=30)
        lines = follower.stdout.read().splitlines()
        stoppedCleanly = any('"worker stopped cleanly"' in line for line in lines)
        print(f"graceful shutdown: pod {pod} gone in {seconds:.1f}s (grace period 120s); logged 'worker stopped cleanly': {stoppedCleanly}")
        self.kubectl("rollout", "status", "deploy/orchestrator", "--timeout=120s")

    def replicas(self) -> tuple[int, int]:
        deployment = json.loads(self.kubectl("get", "deploy/orchestrator", "-o", "json"))
        return deployment["spec"].get("replicas", 0), deployment["status"].get("readyReplicas", 0)

    def opsStatus(self) -> dict:
        return self.http.get("/ops/status", headers={"X-Api-Key": self.keys["user"]}).json()

    def scaling(self, question: str, jobs: int) -> None:
        runIds = [self.ask(question, "user" if index % 2 == 0 else "approver") for index in range(jobs)]
        print(f"\nsubmitted {len(runIds)} jobs; watching (seconds, waiting jobs, desired/ready workers, live heartbeats)")
        started = time.monotonic()
        peak = 0
        lastLine = ""
        while time.monotonic() - started < 600:
            status = self.opsStatus()
            waiting = sum(status["queue"][priority] for priority in ("high", "normal", "low"))
            desired, ready = self.replicas()
            peak = max(peak, ready)
            done = sum(self.run(runId)["status"] in ("completed", "failed") for runId in runIds)
            line = f"waiting={waiting:2} working={status['queue']['leased']} workers={desired}/{ready} live={status['workers']} done={done}/{jobs}"
            if line != lastLine:
                print(f"  {time.monotonic() - started:5.0f}s  {line}")
                lastLine = line
            if done == jobs and desired == 1:
                break
            time.sleep(5)
        print(f"peak ready workers: {peak}")


if __name__ == "__main__":
    checks = ClusterChecks()
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("network", "all"):
        checks.networkPolicies()
    if step in ("shutdown", "all"):
        checks.gracefulShutdown()
    if step in ("run", "all"):
        checks.endToEnd("What are common benchmarks for evaluating code generation by large language models?")
    if step in ("scale", "all"):
        checks.scaling("How does speculative decoding speed up large language model inference?", 12)
