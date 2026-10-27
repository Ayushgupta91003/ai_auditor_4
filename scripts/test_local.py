"""Run the offline suite and save a non-secret machine-readable result."""
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"tests"))
suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"))
result=unittest.TextTestRunner(verbosity=1).run(suite)
out=ROOT/"test-results";out.mkdir(exist_ok=True)
summary={"tests_discovered":result.testsRun,"passed":result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
    "skipped":len(result.skipped),"failures":len(result.failures),"errors":len(result.errors),
    "live_groq_tested":False,"live_bedrock_tested":False,"skipped_checks":[{"test":str(t),"reason":reason} for t,reason in result.skipped]}
(out/"latest.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
raise SystemExit(0 if result.wasSuccessful() else 1)
