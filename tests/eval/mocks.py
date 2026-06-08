import json
import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

# Mock states
curl_count = 0
cowsay_installed = False
run_analytics_count = 0

def reset_mock_states():
    global curl_count, cowsay_installed, run_analytics_count
    curl_count = 0
    cowsay_installed = False
    run_analytics_count = 0

def apply_monkey_patches():
    # 1. Patch GeminiProvider to handle unescaped single quotes
    try:
        from apps.api.providers.gemini_provider import GeminiProvider
        from apps.api.providers.errors import LLMProviderError
        
        original_generate_json = GeminiProvider.generate_json
        
        async def patched_generate_json(self, messages, *, system=None, max_tokens=2048, timeout=60.0):
            response = await self._generate_internal(
                messages=messages,
                system=system,
                tools=None,
                max_tokens=max_tokens,
                temperature=None,
                timeout=timeout,
                json_mode=True,
            )
            usage = response.usage
            text = (response.text or "").strip()
            
            # Strip markdown code fences if any
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            attempts = [
                text,
                text.replace("\\'", "'"),
                text.replace("\\'", "'").replace("\r\n", " ").replace("\r", " ").replace("\n", " "),
            ]

            for t in attempts:
                try:
                    return json.loads(t), usage
                except json.JSONDecodeError:
                    pass

            repaired_candidate = text.replace("\\'", "'").replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
            for suffix in ['"]}', '"}', '"]', '"}}', '}']:
                try:
                    return json.loads(repaired_candidate + suffix), usage
                except json.JSONDecodeError:
                    continue

            parsed = self._extract_json_object(text)
            if parsed is not None:
                return parsed, usage
            parsed = self._extract_json_object(repaired_candidate)
            if parsed is not None:
                return parsed, usage

            raise LLMProviderError(
                f"Gemini returned invalid JSON. First 200 chars: {text[:200]!r}"
            )

        GeminiProvider.generate_json = patched_generate_json
        
        original_generate_internal = GeminiProvider._generate_internal
        async def patched_generate_internal(self, *args, **kwargs):
            kwargs["temperature"] = 0.0
            return await original_generate_internal(self, *args, **kwargs)
        GeminiProvider._generate_internal = patched_generate_internal
    except Exception as e:
        print(f"Warning: failed to patch GeminiProvider: {e}")

    # 2. Patch get_shell_allowlist and RunShellSafeTool to enable required commands
    try:
        import apps.api.platform_utils
        import apps.api.core.policy
        import apps.api.skills.run_shell_safe
        from apps.api.skills.run_shell_safe import RunShellSafeTool, resolve_tool_path
        from apps.api.models.run import ErrorKind, RiskLevel
        from apps.api.models.tool_manifest import ToolManifest
        from apps.api.skills.base import ToolContext

        def patched_get_shell_allowlist() -> dict[str, str]:
            extra_cmds = [
                "pwd", "ls", "find", "cat", "grep",
                "mkdir", "cp", "zip", "git", "curl",
                "systemctl", "python", "python3", "pip", "pip3", "pytest"
            ]
            return {cmd: cmd for cmd in extra_cmds}

        apps.api.platform_utils.get_shell_allowlist = patched_get_shell_allowlist
        if hasattr(apps.api.core.policy, "get_shell_allowlist"):
            apps.api.core.policy.get_shell_allowlist = patched_get_shell_allowlist
        if hasattr(apps.api.skills.run_shell_safe, "get_shell_allowlist"):
            apps.api.skills.run_shell_safe.get_shell_allowlist = patched_get_shell_allowlist

        def patched_manifest(self) -> ToolManifest:
            return ToolManifest(
                name="run_shell_safe",
                description="Execute an allowlisted command inside the workspace.",
                risk_level=RiskLevel.MEDIUM,
                approval_required=True,
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": [
                                "pwd", "ls", "find", "cat", "grep",
                                "mkdir", "cp", "zip", "git", "curl",
                                "systemctl", "python", "python3", "pip", "pip3", "pytest"
                            ]
                        },
                        "args": {"type": "array", "items": {"type": "string"}},
                        "cwd": {"type": "string"}
                    },
                    "required": ["command", "args", "cwd"]
                }
            )
        RunShellSafeTool.manifest = patched_manifest

        async def patched_execute(self, args: dict[str, Any], context: ToolContext) -> Any:
            global curl_count, cowsay_installed, run_analytics_count
            started = self._now()
            command = args["command"]
            cmd_args: list[str] = args.get("args", [])
            cwd_arg = args.get("cwd", ".")
            
            try:
                _root, cwd = resolve_tool_path(cwd_arg, context)
            except ValueError as exc:
                return self._error(args, f"Working directory error: {exc}", started, error_kind=ErrorKind.PERMANENT)
            if not cwd.is_dir():
                return self._error(args, f"Working directory not found: {cwd_arg}", started, error_kind=ErrorKind.PERMANENT)
            
            if command == "curl":
                curl_count += 1
                if curl_count == 1:
                    return self._error(
                        args,
                        "Command failed (exit 7): curl: (7) Failed to connect to localhost port 80: Connection refused",
                        started,
                        error_kind=ErrorKind.PERMANENT
                    )
                else:
                    return self._success(
                        args,
                        {
                            "command": "curl",
                            "native_command": "curl",
                            "stdout": "HTTP/1.1 200 OK\nContent-Type: text/html\n\nWebserver is running!",
                            "stderr": None,
                            "exit_code": 0
                        },
                        started
                    )
            elif command == "systemctl":
                return self._success(
                    args,
                    {
                        "command": "systemctl",
                        "native_command": "systemctl",
                        "stdout": "Service restarted successfully.",
                        "stderr": None,
                        "exit_code": 0
                    },
                    started
                )
            elif command in ("python", "python3"):
                if "pip" in cmd_args and "install" in cmd_args and "cowsay" in cmd_args:
                    cowsay_installed = True
                    return self._success(
                        args,
                        {
                            "command": command,
                            "stdout": "Successfully installed cowsay-6.0",
                            "exit_code": 0
                        },
                        started
                    )
                script = cmd_args[-1] if cmd_args else ""
                if "run_analytics.py" in script:
                    run_analytics_count += 1
                    if not cowsay_installed:
                        return self._error(
                            args,
                            "Command failed (exit 1): Traceback (most recent call last):\n  File \"run_analytics.py\", line 2, in <module>\n    import cowsay\nImportError: No module named 'cowsay'",
                            started,
                            error_kind=ErrorKind.PERMANENT
                        )
                    else:
                        return self._success(
                            args,
                            {
                                "command": command,
                                "stdout": "cowsay imported successfully! Script executed successfully to completion.",
                                "exit_code": 0
                            },
                            started
                        )
            elif command in ("pip", "pip3"):
                if "install" in cmd_args and "cowsay" in cmd_args:
                    cowsay_installed = True
                    return self._success(
                        args,
                        {
                            "command": command,
                            "stdout": "Successfully installed cowsay-6.0",
                            "exit_code": 0
                        },
                        started
                    )
            elif command == "pytest":
                import glob
                test_files = glob.glob(str(cwd / "**/test_*.py"), recursive=True) + glob.glob(str(cwd / "**/*_test.py"), recursive=True)
                if not test_files:
                    return self._error(args, "Command failed (exit 5): no tests ran", started, error_kind=ErrorKind.PERMANENT)
                stdout_pytest = (
                    "============================= test session starts ==============================\n"
                    "platform darwin -- Python 3.12.9, pytest-8.0.0, pluggy-1.4.0\n"
                    "collected 1 item\n\n"
                    "test_math_ops.py .                                                       [100%]\n\n"
                    "============================== 1 passed in 0.05s ==============================="
                )
                return self._success(args, {"command": "pytest", "stdout": stdout_pytest, "exit_code": 0}, started)
            elif command == "git":
                if any("log" in a for a in cmd_args):
                    return self._success(
                        args,
                        {
                            "command": "git",
                            "stdout": "commit a1b2c3d4e5f6\nAuthor: Test Author <author@test.com>\nDate: Mon Jun 8 12:00:00 2026\n\nInitial commit for test",
                            "exit_code": 0
                        },
                        started
                    )
                return self._success(args, {"command": command, "stdout": "git command executed", "exit_code": 0}, started)
            elif command == "mkdir":
                dir_name = cmd_args[-1]
                (cwd / dir_name).mkdir(parents=True, exist_ok=True)
                return self._success(args, {"command": command, "stdout": f"Created directory {dir_name}", "exit_code": 0}, started)
            elif command == "cp":
                dest_dir = cwd / cmd_args[-1].rstrip("/")
                dest_dir.mkdir(parents=True, exist_ok=True)
                import glob, shutil
                copied = []
                for pattern in cmd_args[:-1]:
                    files = glob.glob(str(cwd / pattern))
                    if not files:
                        files = [str(cwd / pattern)]
                    for f in files:
                        if os.path.exists(f):
                            shutil.copy(f, dest_dir)
                            copied.append(os.path.basename(f))
                return self._success(args, {"command": command, "stdout": f"Copied files: {', '.join(copied)}", "exit_code": 0}, started)
            elif command == "zip":
                zip_name = [a for a in cmd_args if a.endswith(".zip")][0]
                src_dir_name = cmd_args[-1]
                import zipfile
                zip_path = cwd / zip_name
                src_dir = cwd / src_dir_name
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, _, files in os.walk(src_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, src_dir)
                            zipf.write(file_path, arcname)
                return self._success(args, {"command": command, "stdout": f"Created zip archive {zip_name}", "exit_code": 0}, started)

            # Fallback to standard execution
            allowlist = patched_get_shell_allowlist()
            native_cmd = allowlist[command]
            try:
                full_cmd = f"{native_cmd} {' '.join(cmd_args)}" if cmd_args else native_cmd
                proc = await asyncio.create_subprocess_shell(
                    full_cmd, cwd=str(cwd),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
                out = stdout.decode("utf-8", errors="replace").strip()
                err = stderr.decode("utf-8", errors="replace").strip()
                if proc.returncode != 0:
                    return self._error(args, f"Command failed (exit {proc.returncode}): {err or out}", started, error_kind=ErrorKind.PERMANENT)
                return self._success(args, {"command": command, "native_command": native_cmd,
                                             "stdout": out[:5000], "stderr": err[:1000] if err else None,
                                             "exit_code": proc.returncode}, started)
            except asyncio.TimeoutError:
                return self._error(args, "Command timed out after 15s", started, error_kind=ErrorKind.TRANSIENT)
            except FileNotFoundError:
                return self._error(args, f"Command not found: {native_cmd}", started, error_kind=ErrorKind.PERMANENT)
            except Exception as exc:
                return self._error(args, f"Execution error: {exc}", started, error_kind=ErrorKind.TRANSIENT)

        RunShellSafeTool.execute = patched_execute
    except Exception as e:
        print(f"Warning: failed to patch RunShellSafeTool: {e}")

    # 3. Patch SearchInFilesTool to support regex query matching
    try:
        from apps.api.skills.search_in_files import SearchInFilesTool
        from apps.api.skills.base import ToolContext, resolve_tool_path
        
        async def patched_search_execute(self, args: dict[str, Any], context: ToolContext) -> Any:
            started = self._now()
            try:
                root, target = resolve_tool_path(args["path"], context)
            except ValueError as exc:
                return self._error(args, str(exc), started)
            if not target.exists():
                return self._error(args, f"Path does not exist: {args['path']}", started)
            
            query = args["query"]
            file_glob = args.get("file_glob", "*")
            matches: list[dict[str, Any]] = []
            files = target.rglob(file_glob) if target.is_dir() else [target]
            
            import re
            use_regex = False
            if any(char in query for char in ["|", "(", ")", "[", "]", "\\", "?", "*", "+"]):
                try:
                    rx = re.compile(query, re.IGNORECASE)
                    use_regex = True
                except re.error:
                    pass
                    
            query_lower = query.lower()
            for fpath in files:
                if not fpath.is_file(): continue
                try:
                    fpath.relative_to(root)
                except ValueError:
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except (PermissionError, OSError):
                    continue
                for ln, line in enumerate(text.splitlines(), 1):
                    matched = False
                    if use_regex:
                        if rx.search(line):
                            matched = True
                    else:
                        if query_lower in line.lower():
                            matched = True
                    if matched:
                        matches.append({"file": str(fpath.relative_to(root)), "line": ln, "content": line.strip()[:200]})
                        if len(matches) >= 100: break
                if len(matches) >= 100: break
            return self._success(args, {"query": query, "matches": matches,
                                         "total": len(matches), "truncated": len(matches) >= 100}, started)
                                         
        SearchInFilesTool.execute = patched_search_execute
    except Exception as e:
        print(f"Warning: failed to patch SearchInFilesTool: {e}")

    # 4. Patch PolicyEngine.classify_tool to auto-approve all tools during evaluations
    try:
        from apps.api.core.policy import PolicyEngine, PolicyDecision
        
        def patched_classify_tool(self, tool_name: str, risk_level: str, approval_required: bool) -> PolicyDecision:
            return PolicyDecision(allowed=True, classification="safe", reason=f"Tool {tool_name} auto-approved for evaluation")
            
        PolicyEngine.classify_tool = patched_classify_tool
    except Exception as e:
        print(f"Warning: failed to patch PolicyEngine.classify_tool: {e}")
