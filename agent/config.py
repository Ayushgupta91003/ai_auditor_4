import yaml
from agent.settings import ROOT

def rules():
    return yaml.safe_load((ROOT / "configs/rules.yaml").read_text(encoding="utf-8"))

def prompt(name):
    personas=yaml.safe_load((ROOT / "configs/personas.yaml").read_text(encoding="utf-8"))
    role={"extraction":"extractor","translation":"translator","reporting":"reporter","answer":"rag","reflection":"rag"}.get(name,name)
    return personas.get(role,"")+"\n"+(ROOT/"agent/prompts"/(name+".txt")).read_text(encoding="utf-8")
