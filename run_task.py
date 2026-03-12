"""Run a Zenflow task end-to-end by driving the API."""
import sys, os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import requests, time, json

BASE = "http://localhost:5000"
TASK_ID = sys.argv[1] if len(sys.argv) > 1 else input("Task ID: ").strip()

def get_steps():
    r = requests.get(f"{BASE}/api/tasks/{TASK_ID}")
    r.raise_for_status()
    return r.json()

def start_step(step_id):
    r = requests.post(f"{BASE}/api/tasks/{TASK_ID}/steps/{step_id}/start")
    r.raise_for_status()
    return r.json()

def stream_step(chat_id, step_name):
    """Stream the step to completion. Returns True if step_completed event received."""
    msg = f'Begin working on step: "{step_name}".'
    url = f"{BASE}/api/chats/{chat_id}/stream?taskId={TASK_ID}&message={requests.utils.quote(msg)}"
    completed = False
    error = False
    stalled = False
    with requests.get(url, stream=True, timeout=600) as resp:
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event: step_completed"):
                completed = True
            elif line.startswith("event: error"):
                error = True
            elif line.startswith("event: done"):
                # Check for stalled
                if "stalled" in line:
                    stalled = True
                break
    return completed, error, stalled

def mark_completed(step_id):
    """Call PATCH to trigger auto-complete check."""
    requests.patch(f"{BASE}/api/tasks/{TASK_ID}/steps/{step_id}",
                   json={"status": "completed"})

task = get_steps()
steps = task.get("steps", [])
total = len(steps)

print(f"Task: {task.get('title', TASK_ID)}")
print(f"Steps: {total}")
print("=" * 60)

for i, step in enumerate(steps):
    sid = step["id"]
    sname = step["name"]
    status = step["status"]

    if status == "completed":
        print(f"[{i+1}/{total}] {sname} — already completed, skipping")
        continue

    print(f"[{i+1}/{total}] {sname} — starting...", flush=True)
    info = start_step(sid)
    chat_id = info["chatId"]

    print(f"         chat={chat_id[:8]}... streaming...", flush=True)
    t0 = time.time()
    completed, error, stalled = stream_step(chat_id, sname)
    elapsed = time.time() - t0

    if completed:
        mark_completed(sid)
        print(f"         OK completed in {elapsed:.0f}s")
    elif stalled:
        print(f"         FAIL STALLED after {elapsed:.0f}s")
        sys.exit(1)
    elif error:
        print(f"         FAIL ERROR after {elapsed:.0f}s")
        sys.exit(1)
    else:
        print(f"         WARN  stream ended without step_completed ({elapsed:.0f}s)")
        # Check if step actually completed despite no event
        task = get_steps()
        s = next((x for x in task["steps"] if x["id"] == sid), None)
        if s and s["status"] == "completed":
            print(f"         OK (verified completed via API)")
        else:
            print(f"         FAIL step did not complete")
            sys.exit(1)

# Final status
task = get_steps()
print("=" * 60)
print(f"Final task status: {task['status']}")
all_done = all(s["status"] == "completed" for s in task["steps"])
print(f"All steps completed: {all_done}")
