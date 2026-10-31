import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import yaml
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
k8sDirectory = root / "k8s"


class KindCluster:
    """Builds a local kind cluster running ResearchDesk. Safe to run again: every step is create-or-update."""

    clusterName = "researchdesk"
    namespace = "researchdesk"
    imageTag = "0.1.0"
    calicoManifest = "https://raw.githubusercontent.com/projectcalico/calico/v3.29.1/manifests/calico.yaml"
    kedaManifest = "https://github.com/kedacore/keda/releases/download/v2.16.1/keda-2.16.1.yaml"
    # Only these .env values go into the cluster's Secret; everything else is in the ConfigMap.
    secretNames = (
        "OPENAI_API_KEY", "REDIS_PASSWORD", "POSTGRES_PASSWORD", "AGENT_SIGNING_SEED", "AGENT_PUBLIC_KEY",
        "FACTCHECKER_SIGNING_SEED", "FACTCHECKER_PUBLIC_KEY", "SEARCH_HMAC_KEY", "NOTES_HMAC_KEY", "EVIL_HMAC_KEY",
        "USER_API_KEY", "APPROVER_API_KEY", "SESSION_SECRET",
    )

    def __init__(self):
        self.kind = shutil.which("kind") or self.wingetKind()

    @staticmethod
    def wingetKind() -> str:
        found = next(Path.home().glob("AppData/Local/Microsoft/WinGet/Packages/Kubernetes.kind*/kind.exe"), None)
        if found is None:
            raise FileNotFoundError("kind is not installed")
        return str(found)

    def run(self) -> None:
        self.createCluster()
        self.applyCalico()
        self.waitFor("kube-system", "daemonset/calico-node")
        self.step("KEDA (event-driven autoscaling)", ["kubectl", "apply", "--server-side", "-f", self.kedaManifest])
        for kedaPart in ("keda-operator", "keda-metrics-apiserver", "keda-admission"):
            self.waitFor("keda", f"deployment/{kedaPart}")
        self.loadImages()
        self.step("namespace and config", ["kubectl", "apply", "-f", str(k8sDirectory / "base.yaml")])
        self.applySecret()
        for manifest in ("dataStores.yaml", "app.yaml", "networkPolicies.yaml", "keda.yaml"):
            self.step(manifest, ["kubectl", "apply", "-f", str(k8sDirectory / manifest)])
        for workload in ("statefulset/redis", "statefulset/postgres", "deployment/search", "deployment/notes",
                         "deployment/gateway", "deployment/factchecker", "deployment/orchestrator", "deployment/api", "deployment/web"):
            self.waitFor(self.namespace, workload)
        print("\nResearchDesk is running on kind: http://localhost:8090")

    def createCluster(self) -> None:
        existing = subprocess.run(
            [self.kind, "get", "clusters"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
        ).stdout.split()
        if self.clusterName in existing:
            print(f"cluster {self.clusterName} already exists")
            return
        self.step("kind cluster", [self.kind, "create", "cluster", "--config", str(k8sDirectory / "kindCluster.yaml"), "--wait", "120s"])

    def applyCalico(self) -> None:
        # Calico's pod range must match the cluster's podSubnet; its manifest ships with 192.168.0.0/16 commented out.
        podSubnet = yaml.safe_load((k8sDirectory / "kindCluster.yaml").read_text())["networking"]["podSubnet"]
        manifest = httpx.get(self.calicoManifest, follow_redirects=True, timeout=60).text
        manifest, replaced = re.subn(
            r"# - name: CALICO_IPV4POOL_CIDR\n(\s*)#   value: \"[0-9./]+\"",
            rf'- name: CALICO_IPV4POOL_CIDR\n\1  value: "{podSubnet}"',
            manifest,
        )
        if replaced != 1:
            raise ValueError("could not set CALICO_IPV4POOL_CIDR in the Calico manifest")
        print("== Calico (enforces NetworkPolicy)")
        subprocess.run(["kubectl", "apply", "-f", "-"], input=manifest, text=True, encoding="utf-8", capture_output=True, check=True)

    def loadImages(self) -> None:
        # Images come from the Compose build; a fixed tag (not latest) keeps Kubernetes from trying to pull them.
        self.step("build images", ["docker", "compose", "--profile", "app", "build"], cwd=root)
        for image in ("researchdesk-app", "researchdesk-web"):
            self.step(f"tag {image}", ["docker", "tag", f"{image}:latest", f"{image}:{self.imageTag}"])
            self.step(f"load {image} into kind", [self.kind, "load", "docker-image", f"{image}:{self.imageTag}", "--name", self.clusterName])

    def applySecret(self) -> None:
        values = dotenv_values(root / ".env")
        missing = [name for name in self.secretNames if not values.get(name)]
        if missing:
            raise ValueError(f".env is missing {missing}; run uv run scripts/initEnv.py and add OPENAI_API_KEY")
        secret = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "researchdesk-secrets", "namespace": self.namespace},
            "type": "Opaque",
            "stringData": {name: values[name] for name in self.secretNames},
        }
        # Piped on stdin: the secret values never touch disk or the command line.
        subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(secret), text=True, check=True, capture_output=True)
        print("== secret researchdesk-secrets applied")

    def waitFor(self, namespace: str, workload: str) -> None:
        self.step(f"wait for {workload}", ["kubectl", "rollout", "status", workload, "-n", namespace, "--timeout=300s"])

    @staticmethod
    def step(label: str, command: list[str], cwd: Path | None = None) -> None:
        print(f"== {label}")
        # Tools print UTF-8; Windows' default code page cannot decode all of it.
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            print(result.stdout[-2000:], result.stderr[-2000:], file=sys.stderr)
            raise RuntimeError(f"step failed: {label}")


if __name__ == "__main__":
    KindCluster().run()
