#!/usr/bin/env python3
"""Host-side AI runner for the Nepal Gold Purchase Advisor.

Runs on the host (not in Docker) so the Codex, Claude Code, and Kiro CLIs keep their
own installation and sign-in. It claims one job at a time from the API, runs the chosen
CLI without a shell in an empty temporary folder, and sends the raw output back. The
API validates the answer; this script never decides what is valid.

Standard library only. Configure with environment variables or --env-file:
  GA_RUNNER_TOKEN  shared secret (same value the API container has)
  GA_API_URL       default http://127.0.0.1:8010
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import openrouter

TIMEOUT_SECONDS = 120
POLL_SECONDS = 15
HEARTBEAT_SECONDS = 60
MAX_OUTPUT = 200_000
EXECUTABLES = {"codex": "codex", "claude": "claude", "kiro": "kiro-cli"}
# Only these variables reach the CLI: enough for it to find its own sign-in.
PASSED_ENV = ("HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TERM", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
              "XDG_RUNTIME_DIR", "KIRO_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_HOME", "NVM_DIR")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def load_env_file(path: str) -> None:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Api:
    def __init__(self, base: str, token: str):
        self.base, self.token = base.rstrip("/"), token

    def post(self, path: str, body: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body or {}).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            return exc.code, {}


def child_env() -> dict:
    return {k: os.environ[k] for k in PASSED_ENV if k in os.environ}


def version(provider: str) -> dict:
    if provider == "openrouter":
        return {"ready": bool(os.environ.get("GA_OPENROUTER_API_KEY", "").strip()), "version": "OpenRouter API",
                **({} if os.environ.get("GA_OPENROUTER_API_KEY", "").strip() else {"error": "API key not configured"})}
    exe = shutil.which(EXECUTABLES[provider])
    if not exe:
        return {"ready": False, "error": f"{EXECUTABLES[provider]} is not installed"}
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20, env=child_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ready": False, "error": str(exc)}
    if out.returncode != 0:
        return {"ready": False, "error": (out.stderr or out.stdout).strip()[:300]}
    status = {"ready": True, "version": out.stdout.strip()[:120]}
    if provider == "kiro":
        who = subprocess.run([exe, "whoami"], capture_output=True, text=True, timeout=20, env=child_env())
        if who.returncode != 0:
            status = {"ready": False, "version": status["version"], "error": "Not signed in. Run: kiro-cli login"}
    return status


def command(provider: str, model: str | None, prompt: str, schema_path: str, out_path: str, workdir: str) -> list[str]:
    exe = shutil.which(EXECUTABLES[provider])
    if exe is None:
        raise FileNotFoundError(f"{EXECUTABLES[provider]} is not installed")
    if provider == "codex":
        cmd = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-rules", "-s", "read-only",
               "-c", "mcp_servers={}", "-C", workdir, "--output-schema", schema_path, "-o", out_path]
        if model:
            cmd += ["-m", model]
        return cmd + [prompt]
    if provider == "claude":
        with open(schema_path, encoding="utf-8") as fh:
            schema = fh.read()
        cmd = [exe, "-p", prompt, "--output-format", "json", "--json-schema", schema, "--restricted", "--tools", "",
               "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]
        if model:
            cmd += ["--model", model]
        return cmd
    cmd = [exe, "chat", "--no-interactive", "--trust-tools="]
    if model:
        cmd += ["--model", model]
    return cmd + [prompt]


def run_job(job: dict) -> dict:
    provider, model = job["provider"], job.get("model")
    info = version(provider)
    if not info.get("ready"):
        return {"error": f"{provider} is not ready: {info.get('error')}", "cli_version": info.get("version")}
    if provider == "openrouter":
        try:
            return {**openrouter.run(job["prompt"], job["schema"]), "cli_version": "OpenRouter API"}
        except openrouter.OpenRouterError as error:
            return {"error": str(error), "cli_version": "OpenRouter API"}
    with tempfile.TemporaryDirectory(prefix="gold-ai-") as workdir:
        schema_path = os.path.join(workdir, "schema.json")
        out_path = os.path.join(workdir, "answer.json")
        with open(schema_path, "w", encoding="utf-8") as fh:
            json.dump(job["schema"], fh)
        try:
            proc = subprocess.run(
                command(provider, model, job["prompt"], schema_path, out_path, workdir),
                cwd=workdir, env=child_env(), capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return {"error": f"{provider} took longer than {TIMEOUT_SECONDS} seconds", "cli_version": info["version"]}
        except OSError as exc:
            return {"error": str(exc), "cli_version": info["version"]}
        output = ""
        if os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as fh:
                output = fh.read()
        if not output.strip():
            output = ANSI.sub("", proc.stdout)
        if proc.returncode != 0 and not output.strip():
            detail = ANSI.sub("", proc.stderr or proc.stdout).strip()[-1500:]
            return {"error": f"{provider} exited {proc.returncode}: {detail}", "cli_version": info["version"]}
        return {"raw_output": output[:MAX_OUTPUT], "cli_version": info["version"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file")
    parser.add_argument("--once", action="store_true", help="handle at most one job, then exit")
    args = parser.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    token = os.environ.get("GA_RUNNER_TOKEN", "")
    if len(token) < 32:
        print("GA_RUNNER_TOKEN must be set (32+ characters)", file=sys.stderr)
        return 2
    api = Api(os.environ.get("GA_API_URL", "http://127.0.0.1:8010"), token)
    last_heartbeat = 0.0
    while True:
        try:
            if time.monotonic() - last_heartbeat >= HEARTBEAT_SECONDS:
                api.post("/api/v1/runner/heartbeat", {"providers": {p: version(p) for p in (*EXECUTABLES, "openrouter")}})
                last_heartbeat = time.monotonic()
            code, job = api.post("/api/v1/runner/claim")
            if code == 401:
                print("API rejected the runner token", file=sys.stderr)
                return 3
            if code == 200 and job.get("id"):
                print(f"job {job['id']}: running {job['provider']}", flush=True)
                result = run_job(job)
                code, reply = api.post(f"/api/v1/runner/jobs/{job['id']}", result)
                print(f"job {job['id']}: {reply.get('status', code)} {reply.get('error') or ''}".rstrip(), flush=True)
                if args.once:
                    return 0
                continue
            if args.once:
                return 0
        except (urllib.error.URLError, OSError) as exc:
            print(f"API not reachable: {exc}", file=sys.stderr, flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
