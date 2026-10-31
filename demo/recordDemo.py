import shutil
import subprocess
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import Page, sync_playwright

from libs.settings import Settings

webUrl = "http://localhost:5173"
outputDirectory = Path(__file__).resolve().parent / "output"


class Overlay:
    """Captions and title cards drawn on top of the real pages. Only this script's own text goes in them."""

    captionScript = """
    ({ step, text }) => {
      let box = document.getElementById("demoCaption");
      if (!box) {
        box = document.createElement("div");
        box.id = "demoCaption";
        Object.assign(box.style, {
          position: "fixed", left: "50%", bottom: "40px", transform: "translateX(-50%)", zIndex: "2147483647",
          display: "flex", alignItems: "center", gap: "16px", padding: "16px 28px", borderRadius: "16px",
          background: "rgba(7, 10, 20, 0.9)", border: "1px solid rgba(139, 108, 255, 0.65)",
          boxShadow: "0 0 36px rgba(139, 108, 255, 0.4)", color: "#fff", maxWidth: "82%", pointerEvents: "none",
          font: "600 28px 'Space Grotesk', Inter, system-ui, sans-serif", letterSpacing: "-0.01em",
        });
        const label = document.createElement("span");
        label.id = "demoStep";
        Object.assign(label.style, {
          font: "500 15px 'JetBrains Mono', Consolas, monospace", color: "#22d3ee", whiteSpace: "nowrap",
          border: "1px solid rgba(34, 211, 238, 0.5)", borderRadius: "999px", padding: "4px 12px",
        });
        const caption = document.createElement("span");
        caption.id = "demoText";
        box.append(label, caption);
        document.body.appendChild(box);
      }
      document.getElementById("demoStep").textContent = step;
      document.getElementById("demoText").textContent = text;
    }
    """

    cardScript = """
    ({ title, subtitle }) => {
      const card = document.createElement("div");
      card.id = "demoCard";
      Object.assign(card.style, {
        position: "fixed", inset: "0", zIndex: "2147483647", display: "grid", placeItems: "center",
        background: "radial-gradient(900px 500px at 20% 10%, rgba(124,92,255,0.35), transparent 60%),"
          + "radial-gradient(800px 500px at 90% 90%, rgba(34,211,238,0.25), transparent 60%), #060912",
      });
      const inner = document.createElement("div");
      Object.assign(inner.style, { textAlign: "center", maxWidth: "1300px", padding: "0 60px" });
      const heading = document.createElement("div");
      heading.textContent = title;
      Object.assign(heading.style, {
        font: "700 76px 'Space Grotesk', Inter, system-ui, sans-serif", letterSpacing: "-0.03em", lineHeight: "1.1",
        background: "linear-gradient(135deg, #8b6cff, #5b8cff 50%, #22d3ee)", webkitBackgroundClip: "text",
        backgroundClip: "text", color: "transparent",
      });
      const line = document.createElement("div");
      line.textContent = subtitle;
      Object.assign(line.style, { marginTop: "28px", font: "500 30px Inter, system-ui, sans-serif", color: "#c9d1e6", lineHeight: "1.45" });
      inner.append(heading, line);
      card.appendChild(inner);
      document.body.appendChild(card);
    }
    """

    def __init__(self, page: Page):
        self.page = page

    def caption(self, step: str, text: str) -> None:
        self.page.evaluate(self.captionScript, {"step": step, "text": text})

    def card(self, title: str, subtitle: str, seconds: float) -> None:
        self.page.evaluate(self.cardScript, {"title": title, "subtitle": subtitle})
        self.page.wait_for_timeout(seconds * 1000)
        self.page.evaluate("document.getElementById('demoCard')?.remove()")


class DemoRecorder:
    """Drives the running app through a full research run and records it, then encodes an MP4 for LinkedIn."""

    nodeCaptions = {
        "Planner": "The planner splits the question into focused sub-questions",
        "Researchers": "Researchers search arXiv in parallel, every call through the MCP gateway",
        "Fact-Checker": "An independent Fact-Checker agent verifies the claims over A2A",
        "Writer": "The writer drafts a cited research brief",
        "Critic": "The critic scores the draft and sends weak drafts back",
        "Sensitivity": "Sensitive topic: the run pauses for a human",
        "Save note": "Approved: the report is saved through the MCP notes tool",
    }

    # A question the LLM cache has not seen, so every agent visibly does its work on camera.
    question = "How are LLM agents evaluated on long-horizon, multi-step tool use?"
    reviewNote = "Add a short Limitations section with two open problems."

    def __init__(self, settings: Settings, speed: float = 1.5):
        self.apiKey = settings.approverApiKey.get_secret_value()
        self.speed = speed
        # Stretches of the raw recording (seconds) where a page is still loading; the encoder drops them.
        self.skips: list[tuple[float, float]] = []
        self.started = 0.0

    def run(self) -> Path:
        outputDirectory.mkdir(exist_ok=True)
        rawDirectory = outputDirectory / "raw"
        shutil.rmtree(rawDirectory, ignore_errors=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                color_scheme="dark",
                record_video_dir=str(rawDirectory),
                record_video_size={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            self.started = time.monotonic()
            page.set_default_timeout(60000)
            self.perform(page, Overlay(page))
            video = page.video
            context.close()
            browser.close()
            rawVideo = Path(video.path())
        return self.encode(rawVideo)

    def perform(self, page: Page, overlay: Overlay) -> None:
        self.openQuietly(page, webUrl, "Research with an")
        overlay.card("ResearchDesk", "A production-grade multi-agent research system: LangGraph, MCP, A2A, guardrails, OpenTelemetry", 4)

        overlay.caption("STEP 1", "Sign in with a role-based API key")
        page.wait_for_timeout(1200)
        page.locator("input[type=password]").press_sequentially(self.apiKey[:16], delay=25)
        page.locator("input[type=password]").fill(self.apiKey)
        page.get_by_role("button", name="Continue").click()
        page.wait_for_selector("textarea")
        overlay.caption("STEP 2", "Ask a research question")
        page.wait_for_timeout(1500)

        page.locator("textarea").press_sequentially(self.question, delay=35)
        page.wait_for_timeout(600)
        overlay.caption("STEP 2", "Mark it sensitive: a human must approve before anything is saved")
        page.locator(".toggle input").click()
        page.wait_for_timeout(1800)
        page.get_by_role("button", name="Start research").click()

        page.wait_for_selector(".agentGraph")
        overlay.caption("STEP 3", "Queued, picked up by a worker, and traced end to end")
        self.followAgents(page, overlay, until="Needs approval", step="STEP 3")

        overlay.caption("STEP 4", "Human in the loop: the draft waits for an approver")
        page.wait_for_timeout(2500)
        self.scrollTo(page, ".report")
        page.wait_for_timeout(3500)
        self.scrollTo(page, ".approvalBanner")
        page.wait_for_timeout(1000)
        overlay.caption("STEP 4", "Request changes: the note goes back to the writer")
        page.locator(".approvalBanner textarea").press_sequentially(self.reviewNote, delay=30)
        page.wait_for_timeout(800)
        page.get_by_role("button", name="Request changes").click()

        self.followAgents(page, overlay, until="Revised draft 1", step="STEP 5")
        overlay.caption("STEP 5", "Revised draft is back, with the requested Limitations section")
        self.scrollTo(page, ".report")
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollBy({ top: 700, behavior: 'smooth' })")
        page.wait_for_timeout(3000)
        self.scrollTo(page, ".approvalBanner")
        page.wait_for_timeout(1000)
        overlay.caption("STEP 6", "Approve: saved through the MCP notes tool")
        page.get_by_role("button", name="Approve and save").click()
        self.followAgents(page, overlay, until="Completed", step="STEP 6")
        page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
        overlay.caption("STEP 6", "Done: cost, tokens, critic scores and trace id on one page")
        page.wait_for_timeout(3500)

        jaegerUrl = page.get_by_role("link", name="Trace in Jaeger").get_attribute("href")
        kibanaUrl = page.get_by_role("link", name="Logs in Kibana").get_attribute("href")
        appUrl = page.url

        self.openQuietly(page, jaegerUrl, "Service & Operation")
        overlay.caption("STEP 7", "One OpenTelemetry trace across API, queue, agents, MCP, A2A and every LLM call")
        page.wait_for_timeout(4000)
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(3500)

        self.openQuietly(page, kibanaUrl, "Documents")
        page.wait_for_timeout(1500)
        overlay.caption("STEP 8", "Structured logs and the gateway audit trail in Kibana, same trace id")
        page.wait_for_timeout(5000)

        for route, heading, step, text in (
            ("#/history", "History", "STEP 9", "History: status, duration, tokens, cost and model per run"),
            ("#/ops", "Operations", "STEP 10", "Ops: queue backpressure, circuit breakers and cache hit rates"),
            ("#/security", "Security", "STEP 11", "Security: every tool call the gateway allowed, denied or redacted"),
        ):
            self.openQuietly(page, appUrl.split("#")[0] + route, heading)
            overlay.caption(step, text)
            page.wait_for_timeout(3500)

        overlay.card(
            "Built for production",
            "Guardrails · RBAC with signed agent tokens · PII redaction · rate limits · circuit breakers · "
            "human approval · Postgres checkpoints · OpenTelemetry, Jaeger, ELK, Langfuse",
            5,
        )

    def followAgents(self, page: Page, overlay: Overlay, until: str, step: str, timeoutSeconds: int = 300) -> None:
        """Keeps the caption in sync with whichever agent is active, until the given text appears on the page."""
        deadline = time.monotonic() + timeoutSeconds
        shown = ""
        while time.monotonic() < deadline:
            if page.get_by_text(until, exact=False).count() > 0:
                return
            if page.get_by_text("Failed", exact=True).count() > 0:
                raise RuntimeError("the run failed during recording")
            active = page.evaluate(
                "[...document.querySelectorAll('.agentNode.running .nodeLabel')].map(n => n.textContent).join(',')"
            )
            label = active.split(",")[0] if active else ""
            if label in self.nodeCaptions and label != shown:
                overlay.caption(step, self.nodeCaptions[label])
                shown = label
            page.wait_for_timeout(500)
        raise TimeoutError(f"'{until}' did not appear within {timeoutSeconds}s")

    def openQuietly(self, page: Page, url: str, readyText: str) -> None:
        """Navigates and waits for real content; the blank and half-drawn frames in between are cut from the video."""
        start = time.monotonic() - self.started
        page.goto(url)
        page.wait_for_function("text => document.body && document.body.innerText.includes(text)", arg=readyText, timeout=90000)
        page.wait_for_timeout(600)
        self.skips.append((max(0.0, start - 0.1), time.monotonic() - self.started + 0.1))

    @staticmethod
    def scrollTo(page: Page, selector: str) -> None:
        page.evaluate(f"document.querySelector('{selector}')?.scrollIntoView({{ behavior: 'smooth', block: 'start' }})")

    def encode(self, rawVideo: Path) -> Path:
        # H.264 in MP4, 1920x1080, 30 fps, yuv420p and faststart: what LinkedIn's feed player expects.
        # Loading stretches are dropped on the raw timeline first, then the rest is sped up and re-timed.
        finalVideo = outputDirectory / "researchdesk-demo-linkedin.mp4"
        dropped = "+".join(f"between(t,{start:.2f},{end:.2f})" for start, end in self.skips) or "0"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(rawVideo),
                "-vf", (
                    f"fps=30,select='not({dropped})',setpts=N/({30 * self.speed}*TB),fps=30,"
                    "scale=1920:1080:flags=lanczos,format=yuv420p"
                ),
                "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-profile:v", "high",
                "-movflags", "+faststart", "-an", str(finalVideo),
            ],
            check=True,
            capture_output=True,
        )
        return finalVideo


if __name__ == "__main__":
    print(DemoRecorder(Settings()).run())
