#!/usr/bin/env python
"""
Start both backend (FastAPI) and frontend (React Vite dev server) in parallel.

Run directly:
    python start_dev.py

Or from an exe wrapper:
    start-dev.exe
"""
import os
import sys
import subprocess
import time
import signal
import atexit
import webbrowser
from pathlib import Path

# Get project root
PROJECT_ROOT = Path(__file__).parent.absolute()
FRONTEND_DIR = PROJECT_ROOT / "frontend"

print("\n" + "=" * 50)
print("🚀 Liquidity Risk Tool — Starting dev servers")
print("=" * 50)
print(f"Project root: {PROJECT_ROOT}\n")

# Store process references for cleanup
processes = []

def cleanup(signum=None, frame=None):
    """Stop both backend and frontend on exit."""
    print("\n⏹️  Shutting down services...")
    for proc in processes:
        try:
            if proc.poll() is None:  # Still running
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception as e:
            print(f"Error stopping process: {e}")
    print("✅ Done.")
    sys.exit(0)

# Register cleanup handlers
atexit.register(cleanup)
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

# Check Python is available
try:
    subprocess.run([sys.executable, "--version"], capture_output=True, check=True)
except Exception as e:
    print(f"❌ Error: Python not available: {e}")
    sys.exit(1)

# Resolve npm — on Windows Node installs npm.cmd, not a plain exe
NPM = "npm.cmd" if sys.platform == "win32" else "npm"

# Check npm is available
try:
    subprocess.run([NPM, "--version"], capture_output=True, check=True)
except Exception:
    # Fallback: try running via cmd /c
    try:
        subprocess.run(["cmd", "/c", "npm", "--version"], capture_output=True, check=True)
        NPM = None  # signal to use shell=True below
    except Exception as e:
        print(f"❌ Error: npm not found. Ensure Node.js is installed and in PATH.")
        sys.exit(1)

# Start backend
print("▶️  Backend (FastAPI on port 8080)...")
try:
    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--reload",
        "--port",
        "8080"
    ]
    backend_proc = subprocess.Popen(
        backend_cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1
    )
    processes.append(backend_proc)
    print("✅ Backend process started (PID: {})".format(backend_proc.pid))
except Exception as e:
    print(f"❌ Failed to start backend: {e}")
    cleanup()
    sys.exit(1)

# Wait briefly for backend to stabilize
time.sleep(3)

# Start frontend
print("▶️  Frontend (Vite dev server on port 5173)...")
try:
    if NPM:
        frontend_cmd = [NPM, "run", "dev"]
        frontend_proc = subprocess.Popen(
            frontend_cmd,
            cwd=str(FRONTEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
        )
    else:
        frontend_proc = subprocess.Popen(
            "npm run dev",
            cwd=str(FRONTEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            shell=True,
        )
    processes.append(frontend_proc)
    print("✅ Frontend process started (PID: {})".format(frontend_proc.pid))
except Exception as e:
    print(f"❌ Failed to start frontend: {e}")
    cleanup()
    sys.exit(1)

print("\n" + "=" * 50)
print("✅ Both services started!")
print("=" * 50)
print("\nBackend:  http://localhost:8080/docs")
print("Frontend: http://localhost:5173\n")
print("Press Ctrl+C to stop both services.\n")

# Open frontend in default browser
print("Opening frontend in browser...")
webbrowser.open("http://localhost:5173")

# Stream output from both processes
def stream_output(proc, label):
    """Stream process output to console."""
    try:
        for line in iter(proc.stdout.readline, ''):
            if line:
                print(f"[{label}] {line.rstrip()}")
    except Exception:
        pass

# Keep main thread alive and monitor processes
try:
    while True:
        # Check if either process has died
        if backend_proc.poll() is not None:
            print("❌ Backend process exited (code: {})".format(backend_proc.returncode))
            cleanup()
        if frontend_proc.poll() is not None:
            print("❌ Frontend process exited (code: {})".format(frontend_proc.returncode))
            cleanup()
        time.sleep(1)
except KeyboardInterrupt:
    cleanup()
