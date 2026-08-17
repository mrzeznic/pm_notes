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
            log_prompt = prompt if len(prompt) < 150 else prompt[:147] + "..."
            AILogger.log(f"Local AI Request Payload: {log_prompt}", "ai")
            status_code, response_body = await cls._http_post_json(url, payload, timeout=300.0)
            duration = time.time() - start_time

            if status_code == 200:
                data = json.loads(response_body)
                response_text = data.get("response", "").strip()
                AILogger.log(f"Ollama responded in {duration:.1f}s", "success")
                log_response = response_text if len(response_text) < 250 else response_text[:247] + "..."
                AILogger.log(f"Local AI Response: {log_response}", "ai")
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
                    log_prompt = prompt if len(prompt) < 150 else prompt[:147] + "..."
                    AILogger.log(f"Cloud AI Request Payload: {log_prompt}", "ai")
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
                    log_response = content.strip() if len(content.strip()) < 250 else content.strip()[:247] + "..."
                    AILogger.log(f"Cloud AI Response: {log_response}", "ai")
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
                    log_prompt = prompt if len(prompt) < 150 else prompt[:147] + "..."
                    AILogger.log(f"Cloud AI Request Payload: {log_prompt}", "ai")
                    status_code, body = await cls._http_post_json(chat_url, payload, headers=headers, timeout=300.0)
                    duration = time.time() - start_time
                    if status_code == 200:
                        data = json.loads(body)
                        content = data["choices"][0]["message"]["content"] or ""
                        AILogger.log(f"Copilot API responded in {duration:.1f}s", "success")
                        log_response = content.strip() if len(content.strip()) < 250 else content.strip()[:247] + "..."
                        AILogger.log(f"Cloud AI Response: {log_response}", "ai")
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
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300.0)
                duration = time.time() - start_time
                if process.returncode == 0:
                    AILogger.log(f"Cloud AI CLI responded in {duration:.1f}s", "success")
                    stdout_str = stdout.decode('utf-8', errors='ignore').strip()
                    stderr_str = stderr.decode('utf-8', errors='ignore').strip()
                    if not stdout_str and stderr_str:
                        AILogger.log(f"Cloud CLI Note: stdout empty, stderr captured: {stderr_str[:150]}", "warning")
                    
                    final_res = stdout_str if stdout_str else stderr_str
                    log_response = final_res if len(final_res) < 250 else final_res[:247] + "..."
                    AILogger.log(f"Cloud CLI Response: {log_response}", "ai")
                    
                    return clean_ansi(final_res)
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
        AILogger.log(f"DEBUG run_prompt: tool={tool_name}, override_mode={override_mode}, final_mode={mode}", "ai")
        if mode == "cloud":
            return await cls.run_copilot(prompt, config)
        return await cls.run_local(prompt, config)

    @classmethod
    async def decompose_task(cls, task_title: str, task_desc: str, project_name: str, config: Dict[str, Any], override_mode: Optional[str] = None) -> List[str]:
        """Prompts AI to break a high-level task into 3-5 concrete subtasks with priority tags."""
        prompt = config["PROMPT_TEMPLATES"]["Decompose"].format(
            project_name=project_name,
            task_title=task_title,
            task_desc=task_desc or 'None'
        )
        res = await cls.run_prompt(prompt, "Tech Plan", config, override_mode=override_mode)
        if "⚠️" in res:
            return []

        # We can parse the returned string with markdown-it-py to extract the generated tasks
        from markdown_it import MarkdownIt
        md = MarkdownIt()
        tokens = md.parse(res)
        lines = res.splitlines()
        
        cleaned = []
        for t in tokens:
            if t.type == "list_item_open" and t.map:
                start, end = t.map
                slice_lines = lines[start:end]
                if slice_lines and "- [" in slice_lines[0]:
                    cleaned.append("\n".join(slice_lines))
        
        # Fallback if AI didn't format as list items properly
        if not cleaned:
            for line in lines:
                if line.strip().startswith("- ["):
                    cleaned.append(line.strip())
                elif line.strip():
                    cleaned.append(f"- [ ] {line.strip()}")
                    
        return cleaned[:6]

    @classmethod
    async def generate_standup(cls, project_name: str, notes_content: str, config: Dict[str, Any], override_mode: Optional[str] = None) -> str:
        """Generates a structured daily standup update for Slack/Teams."""
        today_str = datetime.date.today().strftime('%b %d, %Y')
        prompt = config["PROMPT_TEMPLATES"]["Standup"].format(
            project_name=project_name,
            notes_content=notes_content,
            today_str=today_str
        )
        return await cls.run_prompt(prompt, "Executive", config, override_mode=override_mode)
    @staticmethod
    def filter_private_content(content: str) -> str:
        """Removes #private tasks and project-level context."""
        lines = content.splitlines()
        # Check project-level #private in the first 15 lines (ignore task lines)
        for i in range(min(15, len(lines))):
            line = lines[i].strip()
            if "#private" in line and not line.startswith("- ["):
                return ""
        
        # Filter out private tasks (using MarkdownParser)
        from services.markdown_parser import MarkdownParser
        tasks = MarkdownParser.parse_tasks(content)
        private_tasks = [t for t in tasks if "#private" in t.raw_text]
        for t in sorted(private_tasks, key=lambda x: x.line_start, reverse=True):
            del lines[t.line_start:t.line_end]
        return "\n".join(lines)
