import os, sys, tempfile, shutil
td = tempfile.mkdtemp(prefix="rs_")
ts = os.path.join(td, "storage")
os.makedirs(ts)
sys.path.insert(0, "C:/Users/Shane/Desktop/zenflow-rebuild/backend")
import config
config.Config.STORAGE_DIR = ts
from services.reward_agent import _parse_lessons, _fallback_lessons, _format_signal_breakdown, _format_step_summaries, _format_execution_outcome, generate_lessons
from services.experience_memory import ExperienceMemory
import services.experience_memory as em
em.DB_PATH = os.path.join(ts, "experience_memory.json")
p=0
f=0
fl=[]
def T(n,c,d=""):
    global p,f
    if c:
        p+=1; print("  PASS:",n)
    else:
        f+=1; print("  FAIL:",n,"--",d); fl.append((n,d))
def rdb():
    if os.path.isfile(em.DB_PATH): os.remove(em.DB_PATH)
print("Test setup complete. Temp:", td)
print(); print("="*70)
print("1. _parse_lessons() EDGE CASES")
print("="*70)
r = _parse_lessons("")
T("parse: empty string", r == [])
r = _parse_lessons("No lessons here.")
T("parse: no LESSON lines", r == [])
r = _parse_lessons("LESSON: Do something important | TAGS: impl")
T("parse: missing TYPE", r == [])
r = _parse_lessons("LESSON: Do something important | TYPE: positive")
T("parse: missing TAGS", r == [])
r = _parse_lessons("LESSON: Always check imports before finishing | TYPE: positive | TAGS: implementation, imports | EXTRA: ignored
")
T("parse: extra pipes parses", len(r) >= 1)
if r: T("parse: extra pipes text", "Always check imports" in r[0]["lesson"])
r = _parse_lessons("LESSON: Short | TYPE: positive | TAGS: test
")
T("parse: <10 chars skipped", r == [])
r = _parse_lessons("LESSON: Exactly 10 | TYPE: positive | TAGS: test
")
T("parse: 10 chars skipped", r == [])
r = _parse_lessons("LESSON: Exactly 11c | TYPE: positive | TAGS: test
")
T("parse: 11 chars accepted", len(r) == 1)
mx = "Preamble.
LESSON: This lesson is valid and long enough | TYPE: positive | TAGS: implementation
LESSON: Too short | TYPE: positive | TAGS: test
LESSON: Another valid lesson that should be parsed correctly | TYPE: negative | TAGS: code_quality, python
LESSON: Missing type field | TAGS: whoops
"
r = _parse_lessons(mx)
T("parse: mixed 2 valid", len(r) == 2, f"got {len(r)}")
if len(r)>=2: T("parse: first positive", r[0]["type"]=="positive"); T("parse: second negative", r[1]["type"]=="negative")
r = _parse_lessons("lesson: Use type hints everywhere in Python code | type: positive | tags: python, code_quality
")
T("parse: lowercase", len(r) == 1)
r = _parse_lessons("Lesson: Use type hints everywhere in Python code | Type: Positive | Tags: python, code_quality
")
T("parse: mixed case", len(r) == 1)
r = _parse_lessons("LESSON: " + "A"*300 + " | TYPE: positive | TAGS: test
")
T("parse: long capped 200", len(r)==1 and len(r[0]["lesson"])<=200)
r = _parse_lessons("LESSON: Always verify imports exist in target module | TYPE: positive | TAGS: implementation, imports, python, code_quality
")
T("parse: 4 tags", len(r)==1 and len(r[0]["tags"])==4)
r = _parse_lessons("LESSON: Always verify imports exist in target module | TYPE: positive | TAGS: Implementation, PYTHON
")
T("parse: tags lowered", len(r)==1 and all(t==t.lower() for t in r[0]["tags"]))
r = _parse_lessons("LESSON: Always verify imports exist in target module | TYPE: POSITIVE | TAGS: test
")
T("parse: TYPE lowered", len(r)==1 and r[0]["type"]=="positive")
r = _parse_lessons("LESSON: Always verify imports exist in target module | TYPE: neutral | TAGS: test
")
T("parse: neutral rejected", r == [])
print(); print("="*70)
print("2. _fallback_lessons() EDGE CASES")
print("="*70)
r = _fallback_lessons({})
T("fb: empty >= 1", len(r) >= 1)
pf = {"composite":1.0,"grade":"A","step_scores":[{"step_id":"s1","grade":"A","composite":1.0,"signals":{"tool_adherence":1.0,"code_quality":1.0,"efficiency":1.0,"import_health":1.0},"file_count":5,"turn_count":5}],"execution_score":{"success":True,"attempts":1,"grade":"A","signals":{"review_pass_rate":1.0}}}
r = _fallback_lessons(pf)
T("fb: perfect >= 1", len(r) >= 1)
ty = [l["type"] for l in r]
T("fb: perfect has positive", "positive" in ty)
T("fb: perfect no negative", "negative" not in ty, f"types={ty}")
r = _fallback_lessons({"grade":"C"})
T("fb: missing keys", len(r) >= 1)
r = _fallback_lessons({"step_scores":[],"grade":"B","composite":0.75})
T("fb: empty steps", len(r) >= 1)
r = _fallback_lessons({"step_scores":[{"signals":{"tool_adherence":0.3}}],"grade":"D","composite":0.3})
T("fb: no exec", len(r) >= 1)
T("fb: low tool -> neg", any(l["type"]=="negative" and "tool_usage" in l.get("tags",[]) for l in r))
bd = {"composite":0.5,"grade":"C","step_scores":[{"step_id":"s1","signals":{"tool_adherence":0.5,"code_quality":0.5,"efficiency":0.3,"import_health":0.5}}]}
r = _fallback_lessons(bd)
ng = [l for l in r if l["type"]=="negative"]
T("fb: boundary no neg", len(ng)==0, f"got {len(ng)}")
bl = {"composite":0.4,"grade":"D","step_scores":[{"step_id":"s1","signals":{"tool_adherence":0.49,"code_quality":0.49,"efficiency":0.29,"import_health":0.49}}]}
r = _fallback_lessons(bl)
ng = [l for l in r if l["type"]=="negative"]
T("fb: below boundary >= 4 neg", len(ng) >= 4, f"got {len(ng)}")
r = _fallback_lessons({"composite":0.7,"grade":"B","step_scores":[{"step_id":"s1","signals":{"tool_adherence":0.9}}]})
T("fb: tool=0.9 pos", any("tool_usage" in l.get("tags",[]) and l["type"]=="positive" for l in r))
ab = {"composite":0.1,"grade":"F","step_scores":[{"step_id":"s1","signals":{"tool_adherence":0.1,"code_quality":0.1,"efficiency":0.1,"import_health":0.1}}],"execution_score":{"success":False,"attempts":4,"grade":"F","signals":{"review_pass_rate":0.2}}}
r = _fallback_lessons(ab)
T("fb: all-bad <= 5", len(r) <= 5, f"got {len(r)}")
T("fb: all-bad >= 4 neg", len([l for l in r if l["type"]=="negative"]) >= 4)
r = _fallback_lessons({"composite":0.3,"grade":"D","step_scores":[],"execution_score":{"success":False,"attempts":1,"grade":"F","signals":{}}})
T("fb: exec fail -> testing", any("testing" in l.get("tags",[]) for l in r))
r = _fallback_lessons({"composite":0.6,"grade":"C","step_scores":[],"execution_score":{"success":True,"attempts":3,"grade":"C","signals":{}}})
T("fb: >2 attempts", any("Aim for first-try" in l.get("lesson","") for l in r))
r = _fallback_lessons({"composite":0.90,"grade":"A","step_scores":[{"step_id":"s1","signals":{"tool_adherence":0.95,"code_quality":0.9}}]})
T("fb: grade A positive", any(l["type"]=="positive" for l in r))
r = _fallback_lessons({"composite":0.4,"grade":"D","step_scores":[],"execution_score":{"success":True,"attempts":1,"grade":"D","signals":{"review_pass_rate":0.3}}})
T("fb: low review", any("Read existing files" in l.get("lesson","") for l in r))
r = _fallback_lessons({"composite":0.75,"grade":"B","step_scores":[]})
T("fb: grade B >= 1", len(r) >= 1)
r = _fallback_lessons({"composite":0.2,"grade":"F","step_scores":[]})
T("fb: grade F neg", any(l["type"]=="negative" for l in r))
print(); print("="*70)
print("3. _format_signal_breakdown()")
print("="*70)
r=_format_signal_breakdown({})
T("sig: empty",r=="No signals available.")
r=_format_signal_breakdown({"step_scores":[]})
T("sig: empty steps",r=="No signals available.")
r=_format_signal_breakdown({"step_scores":[{"signals":{"tool_adherence":0.8,"code_quality":0.6}}]})
T("sig: step only","Step Signals" in r)
T("sig: tool shown","tool_adherence" in r)
r=_format_signal_breakdown({"execution_score":{"signals":{"review_pass_rate":0.9}}})
T("sig: exec only","Execution Signals" in r)
r=_format_signal_breakdown({"step_scores":[{"signals":{"tool_adherence":0.8}},{"signals":{"tool_adherence":0.6}}],"execution_score":{"signals":{"review_pass_rate":0.5}}})
T("sig: both","Step Signals" in r and "Execution Signals" in r)
r=_format_signal_breakdown({"step_scores":[{"signals":{"high_sig":0.9,"low_sig":0.2,"mid_sig":0.6}}]})
T("sig: + high","+ high_sig" in r)
T("sig: - low","- low_sig" in r)
T("sig: ~ mid","~ mid_sig" in r)
r=_format_signal_breakdown({"step_scores":[{"signals":{"tool_adherence":0.4}},{"signals":{"tool_adherence":0.6}}]})
T("sig: avg 0.5 ~","~ tool_adherence: 0.50" in r)
print(); print("="*70)
print("4. _format_step_summaries()")
print("="*70)
r=_format_step_summaries([])
T("steps: empty",r=="No steps scored.")
r=_format_step_summaries([{}])
T("steps: missing keys","?" in r)
r=_format_step_summaries([{"step_id":"i1","grade":"B","composite":0.78,"file_count":3,"turn_count":8},{"step_id":"i2","grade":"A","composite":0.95,"file_count":5,"turn_count":5}])
T("steps: normal","i1" in r and "i2" in r)
r=_format_step_summaries([{"step_id":"i3","composite":0.5}])
T("steps: partial","i3" in r)
print(); print("="*70)
print("5. _format_execution_outcome()")
print("="*70)
r=_format_execution_outcome({})
T("exec: no data",r=="No execution data.")
r=_format_execution_outcome({"execution_score":{"success":True,"attempts":1,"grade":"A"}})
T("exec: SUCCESS","SUCCESS" in r)
r=_format_execution_outcome({"execution_score":{"success":False,"attempts":3,"grade":"F"}})
T("exec: FAILED","FAILED" in r)
T("exec: attempt 3","attempt 3" in r)
r=_format_execution_outcome({"execution_score":{}})
T("exec: missing keys","Execution:" in r)
print(); print("="*70)
print("6. generate_lessons() INTEGRATION")
print("="*70)
rdb()
r=generate_lessons(llm=None,task_score={"composite":0.5,"grade":"C","step_scores":[],"execution_score":None},workspace_path="",fingerprint=None,task_id="t1")
T("gen: llm=None >= 1",len(r)>=1)
rdb()
r=generate_lessons(llm=None,task_score={"composite":0.95,"grade":"A","step_scores":[{"step_id":"s1","grade":"A","composite":0.95,"signals":{"tool_adherence":0.95,"code_quality":0.92},"file_count":4,"turn_count":4}],"execution_score":{"success":True,"attempts":1,"grade":"A","signals":{}}},workspace_path="C:/x",fingerprint={"tech_stack":["python"],"libraries":["flask"]},task_id="t2")
T("gen: A all pos",all(l["type"]=="positive" for l in r),f"types={[l[chr(116)+chr(121)+chr(112)+chr(101)] for l in r]}")
rdb()
r=generate_lessons(llm=None,task_score={"composite":0.15,"grade":"F","step_scores":[{"step_id":"s1","grade":"F","composite":0.15,"signals":{"tool_adherence":0.1,"code_quality":0.2,"efficiency":0.1,"import_health":0.2},"file_count":1,"turn_count":20}],"execution_score":{"success":False,"attempts":5,"grade":"F","signals":{"review_pass_rate":0.1}}},workspace_path="C:/x",fingerprint=None,task_id="t3")
T("gen: F has neg",any(l["type"]=="negative" for l in r))
T("gen: F >= 3",len(r)>=3,f"got {len(r)}")
rdb()
r=generate_lessons(llm=None,task_score={"composite":0.5,"grade":"C","step_scores":[]},workspace_path="",task_id="t4")
T("gen: empty ws",len(r)>=1)
rdb()
r=generate_lessons(llm=None,task_score={"composite":0.5,"grade":"C","step_scores":[]},fingerprint=None,task_id="t5")
T("gen: None fp",len(r)>=1)
print(); print("="*70)
print("7. ExperienceMemory RECORDING")
print("="*70)
rdb()
r=generate_lessons(llm=None,task_score={"composite":0.3,"grade":"D","step_scores":[{"step_id":"s1","signals":{"tool_adherence":0.2,"code_quality":0.3}}],"execution_score":{"success":False,"attempts":1,"grade":"F","signals":{}}},fingerprint={"tech_stack":["python"],"libraries":[],"file_exts":[".py"],"step_type":"implementation","complexity_bucket":"medium"},task_id="rec1")
db=ExperienceMemory.load()
ent=db.get("entries",[])
T("rec: DB has entries",len(ent)>=1,f"got {len(ent)}")
for ld in r:
    found=any(e.get("lesson")==ld["lesson"] for e in ent)
    T(f"rec: {ld[chr(108)+chr(101)+chr(115)+chr(115)+chr(111)+chr(110)][:35]}...",found)
if ent:
    e=ent[0]
    T("rec: has sig","sig" in e)
    T("rec: has source_task","source_task" in e)
    T("rec: has source_grade","source_grade" in e)
    T("rec: task=rec1",e.get("source_task")=="rec1")
    T("rec: grade=D",e.get("source_grade")=="D")
st=db.get("stats",{})
T("rec: tasks_scored>0",st.get("tasks_scored",0)>0)
r2=generate_lessons(llm=None,task_score={"composite":0.3,"grade":"D","step_scores":[{"step_id":"s2","signals":{"tool_adherence":0.2,"code_quality":0.3}}],"execution_score":{"success":False,"attempts":1,"grade":"F","signals":{}}},fingerprint={"tech_stack":["python"],"libraries":[],"file_exts":[".py"],"step_type":"implementation","complexity_bucket":"medium"},task_id="rec2")
db2=ExperienceMemory.load()
ent2=db2.get("entries",[])
sigs=[e.get("sig") for e in ent2]
T("rec: no dup sigs",len(sigs)==len(set(sigs)),f"{len(sigs)} vs {len(set(sigs))}")
fu=False
for e in ent2:
    if e.get("source")=="learned" and e.get("hits",0)>=2: fu=True; break
T("rec: hits incremented",fu)
print(); print("="*70)
print("8. GUARANTEE: >= 1 lesson always")
print("="*70)
cases=[
    ({},"empty task_score"),
    ({"composite":0,"grade":"F"},"grade F comp 0"),
    ({"composite":1.0,"grade":"A"},"grade A comp 1.0"),
    ({"composite":0.5,"grade":"C","step_scores":[]},"C empty steps"),
    ({"composite":0.5,"grade":"C","step_scores":[{"signals":{}}]},"empty signals"),
    ({"composite":0.5,"grade":"C","execution_score":{}},"empty exec"),
    ({"composite":0.5,"grade":"C","execution_score":{"success":True,"attempts":1,"signals":{}}},"success exec"),
]
for ts,desc in cases:
    rdb()
    try:
        r=generate_lessons(llm=None,task_score=ts,workspace_path="",fingerprint=None,task_id="g")
        T(f"guarantee: {desc} >= 1",len(r)>=1,f"got {len(r)}")
    except Exception as ex:
        T(f"guarantee: {desc} no crash",False,str(ex))
print(); print("="*70)
print(f"RESULTS: {p} passed, {f} failed, {p+f} total")
print("="*70)
if fl:
    print("
FAILURES:")
    for n,d in fl: print(f"  - {n}: {d}")
else:
    print("
All tests passed.")
shutil.rmtree(td,ignore_errors=True)
print(f"Cleaned up: {td}")
import sys; sys.exit(1 if f>0 else 0)
