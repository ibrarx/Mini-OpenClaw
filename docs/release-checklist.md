# Release Readiness Checklist — T08

## Backend
- [x] Backend starts without errors
- [x] Health endpoint returns all fields (status, api_key, db, tools, workspace, memory count)
- [x] All 7 tools registered (list_files, read_file, write_file, search_in_files, run_shell_safe, remember_fact, search_memory)
- [x] POST /api/chat creates a run
- [x] GET /api/runs/{id} returns run status
- [x] POST /api/runs/{id}/approve works
- [x] GET /api/memory returns items
- [x] POST /api/memory/search returns results
- [x] GET /api/memory/export returns JSON
- [x] No import errors in any module

## Frontend
- [x] Frontend starts without errors
- [x] Chat panel renders with message input
- [x] Plan preview shows steps with tool names
- [x] Approval card appears for risky actions
- [x] Tool trace shows execution results
- [x] Memory browser loads and displays stored items
- [x] Run history shows past runs
- [x] Settings page shows backend status and tools

## Core Flows
- [x] Chat with direct answer works
- [x] Chat with safe tool works (list_files, read_file, search_in_files)
- [x] Chat with approval flow works (write_file, run_shell_safe)
- [x] Memory stores and retrieves facts
- [x] Rejection cancels run

## Security
- [x] Policy blocks paths outside workspace
- [x] Policy blocks path traversal (../)
- [x] Policy blocks tilde expansion (~)
- [x] Policy blocks empty paths
- [x] Policy blocks disallowed shell commands (rm, mv, wget, etc.)
- [x] Policy blocks shell metacharacters (; && || ` $() | < >)
- [x] Policy blocks Windows metacharacters (& ^ %) on all platforms
- [x] Binary files rejected by read_file
- [x] No hardcoded paths in source
- [x] No API keys in source

## Tests
- [x] test_policy.py passes (38 tests)
- [x] test_tools.py passes (31 tests)
- [x] test_planner.py passes (10 tests)
- [x] test_memory.py passes (13 tests)
- [x] test_integration.py passes (7 tests)
- [x] Total: 99+ tests passing

## Packaging
- [x] .env.example is complete
- [x] requirements.txt lists all dependencies
- [x] Makefile has install, dev, test, zip targets
- [x] start.bat and start.ps1 for Windows
- [x] Demo fixtures create useful workspace (seed_demo.py)
- [x] JSON memory export produces readable files (export_memory.py)
- [x] README instructions cover macOS/Linux and Windows
