import asyncio
import datetime
import json
import os
import re
import shlex
import sys
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List

from core.logger import AILogger
from core.security import clean_ansi

# Optional imports for performance
try:
    import httpx
except ImportError:
    httpx = None

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

class AIEngine:
    """Enterprise Hybrid AI Engine: Ollama Local HTTP + GitHub Copilot / Models API + CLI Fallback."""

    @staticmethod
    async def _http_post_json(url: str, payload: dict, headers: Optional[dict] = None, timeout: float = 300.0) -> tuple[int, str]:
        """Async helper that uses httpx if available, otherwise urllib in a thread pool."""
        headers = headers or {}
        headers.setdefault("Content-Type", "application/json")

        if httpx is not None:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    res = await client.post(url, json=payload, headers=headers)
                    return res.status_code, res.text
            except Exception as e:
                err_msg = str(e) or f"{type(e).__name__} (Network / Connection Error)"
                return 500, err_msg

        # Standard library fallback using asyncio executor
        def _sync_request():
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return response.status, response.read().decode('utf-8', errors='ignore')
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode('utf-8', errors='ignore')
            except Exception as e:
                return 500, str(e) or type(e).__name__

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_request)

    @classmethod
    async def run_local(cls, prompt: str, config: Dict[str, Any]) -> str:
        """Invokes local Ollama via native REST API."""
        model = config.get("LOCAL_MODEL", "qwen2.5:7b")
        base_url = config.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip('/')
        url = f"{base_url}/api/generate"

        AILogger.log(f"Invoking Ollama ({model}) via HTTP... [Prompt: {len(prompt)} chars]", "ai")
        start_time = time.time()

        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False
            }
            status_code, response_body = await cls._http_post_json(url, payload, timeout=300.0)
            duration = time.time() - start_time

            if status_code == 200:
                data = json.loads(response_body)
                response_text = data.get("response", "").strip()
                AILogger.log(f"Ollama responded in {duration:.1f}s", "success")
                return clean_ansi(response_text)
            else:
                AILogger.log(f"Ollama HTTP {status_code}: {response_body[:80]}", "error")
                return f"⚠️ Local Model Error ({status_code}): {response_body[:100]}"

        except Exception as e:
            err_msg = str(e) or type(e).__name__
            AILogger.log(f"Ollama Engine Exception: {err_msg}", "error")
            return f"⚠️ Local AI Error: {err_msg}"

    @classmethod
    async def run_copilot(cls, prompt: str, config: Dict[str, Any]) -> str:
        """Invokes GitHub Copilot / Models API via OpenAI-compatible endpoint with CLI fallback."""
        token = config.get("GITHUB_TOKEN", "").strip() or os.environ.get("GITHUB_TOKEN", "").strip()
        model = config.get("CLOUD_MODEL", "gpt-4o")
        endpoint = config.get("GITHUB_MODELS_BASE_URL", "https://models.inference.ai.azure.com")

        # 1. Primary: Use GitHub Models API if token is provided
        if token:
            AILogger.log(f"Invoking GitHub Copilot API ({model})... [Prompt: {len(prompt)} chars]", "ai")
            start_time = time.time()
            try:
                if AsyncOpenAI is not None:
                    client = AsyncOpenAI(base_url=endpoint, api_key=token)
                    response = await client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "You are an expert Technical Project Manager."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.2,
                        timeout=300.0
                    )
                    duration = time.time() - start_time
                    content = response.choices[0].message.content or ""
                    AILogger.log(f"Copilot API responded in {duration:.1f}s", "success")
                    return clean_ansi(content.strip())
                else:
                    chat_url = f"{endpoint.rstrip('/')}/chat/completions"
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "You are an expert Technical Project Manager."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2
                    }
                    headers = {
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    }
                    status_code, body = await cls._http_post_json(chat_url, payload, headers=headers, timeout=300.0)
                    duration = time.time() - start_time
                    if status_code == 200:
                        data = json.loads(body)
                        content = data["choices"][0]["message"]["content"]
                        AILogger.log(f"Copilot API responded in {duration:.1f}s", "success")
                        return clean_ansi(content.strip())
                    else:
                        AILogger.log(f"Copilot API HTTP {status_code}: {body[:80]}", "warning")
            except Exception as e:
                err_msg = str(e) or type(e).__name__
                AILogger.log(f"Copilot API error: {err_msg}. Attempting CLI fallback...", "warning")

        # 2. Fallback: Use 'gh copilot' CLI
        AILogger.log(f"Invoking Cloud AI via gh CLI... [Prompt: {len(prompt)} chars]", "ai")
        try:
            start_time = time.time()
            raw_cmd = config.get("GLOBAL_MODEL_CMD", "gh copilot chat -p")
            cmd_parts = shlex.split(raw_cmd)
            process = await asyncio.create_subprocess_exec(
                *cmd_parts, prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300.0)
                duration = time.time() - start_time
                if process.returncode == 0:
                    AILogger.log(f"Cloud AI CLI responded in {duration:.1f}s", "success")
                    return clean_ansi(stdout.decode('utf-8', errors='ignore').strip())
                else:
                    err_str = stderr.decode('utf-8', errors='ignore').strip()
                    AILogger.log(f"Cloud AI CLI failed ({process.returncode}): {err_str[:100]}", "error")
                    return "⚠️ Cloud Model Error (Check Logs or set GITHUB_TOKEN)"
            except asyncio.TimeoutError:
                process.kill()
                AILogger.log("Cloud AI CLI request timed out (300s)", "error")
                return "⚠️ AI Timeout: Cloud request expired"

        except Exception as e:
            err_msg = str(e) or type(e).__name__
            AILogger.log(f"Cloud AI Engine Exception: {err_msg}", "error")
            return "⚠️ Cloud AI Unavailable (Set GITHUB_TOKEN in Settings)"

    @classmethod
    async def run_prompt(cls, prompt: str, tool_name: str, config: Dict[str, Any], override_mode: Optional[str] = None) -> str:
        """Routes prompt to appropriate engine based on tool configuration or override."""
        mode = override_mode or config.get("MODEL_PREFS", {}).get(tool_name, "local")
        if mode == "cloud":
            return await cls.run_copilot(prompt, config)
        return await cls.run_local(prompt, config)

    @classmethod
    async def decompose_task(cls, task_title: str, task_desc: str, project_name: str, config: Dict[str, Any]) -> List[str]:
        """Prompts AI to break a high-level task into 3-5 concrete subtasks with priority tags."""
        prompt = (
            f"Act as a Technical Project Manager. Decompose this complex task for project '{project_name}' into 3 to 5 clear, actionable subtasks.\n\n"
            f"Parent Task: {task_title}\n"
            f"Context / Description: {task_desc or 'None'}\n\n"
            f"FORMAT RULES:\n"
            f"1. Return ONLY the subtask items, one per line.\n"
            f"2. Each line must be in format: Actionable title #p<1|2|3> (Brief context)\n"
            f"3. Do not include markdown bullet dashes '- [ ]' in the response.\n"
            f"4. Do not include conversational text, headers, or explanations."
        )
        res = await cls.run_prompt(prompt, "Tech Plan", config)
        if "⚠️" in res:
            return []

        lines = [line.strip() for line in res.splitlines() if line.strip()]
        cleaned = []
        for l in lines:
            # Strip checkboxes, numbered bullets (1., 10., (1), 1)), bullets, dashes
            l = re.sub(r'^\s*(?:-\s?\[[\sxX]\]|\(?\d+[\.\)]|[-*•])\s*', '', l)
            l = l.strip()
            if l:
                cleaned.append(l)
        return cleaned[:6]

    @classmethod
    async def generate_standup(cls, project_name: str, notes_content: str, config: Dict[str, Any]) -> str:
        """Generates a structured daily standup update for Slack/Teams."""
        today_str = datetime.date.today().strftime('%b %d, %Y')
        prompt = (
            f"Act as a Technical Project Manager. Review the project notes for '{project_name}' and produce a crisp, executive daily standup update formatted for Slack/Teams.\n\n"
            f"--- NOTES ---\n{notes_content}\n\n"
            f"OUTPUT FORMAT (STRICT):\n"
            f"### 🚀 Standup: {project_name} ({today_str})\n\n"
            f"**🟢 Completed / Recent Progress:**\n"
            f"- Bullet points of completed work based on [x] tasks\n\n"
            f"**🔵 Focus for Today (In Flight):**\n"
            f"- Key active tasks, priorities #p1/#p2, and target due dates\n\n"
            f"**🔴 Blockers & Vulnerabilities:**\n"
            f"- Explicit blockers (#blocked) or dependency risks (#dep)\n\n"
            f"Be concise, technical, and high-impact."
        )
        return await cls.run_prompt(prompt, "Chat", config)
