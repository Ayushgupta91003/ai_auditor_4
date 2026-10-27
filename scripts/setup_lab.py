"""Create private lab configuration once; never overwrite secrets or print them."""
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def create_env(root=ROOT):
    target = root / ".env"
    if target.exists():
        return False
    password = secrets.token_hex(20)
    text = (root / ".env.example").read_text(encoding="utf-8")
    text = text.replace("replace-with-a-local-password", password)
    text = text.replace("replace-with-a-random-local-service-token", secrets.token_urlsafe(32))
    # Region is not a credential; keep lab-provided region when present.
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if region:
        text = text.replace("AWS_REGION=us-east-1", "AWS_REGION=" + region)
    if hasattr(os, "getuid"):
        uid = os.getuid() or 10001
        gid = os.getgid() if os.getuid() else 10001
        text += "\nLAB_UID=" + str(uid) + "\nLAB_GID=" + str(gid) + "\n"
    with target.open("x", encoding="utf-8") as file:
        file.write(text)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    for name in ("incoming", "reports"):
        folder = root / "data" / name
        existed = folder.exists()
        folder.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "getuid") and os.getuid() == 0 and not existed:
            os.chown(folder, 10001, 10001)
    return True

def main():
    created = create_env()
    print("Created private .env with random local passwords." if created else "Existing .env preserved.")
    print("Set the lab AWS region/model IDs and optional Langfuse keys in .env.")
    print("AWS authentication: use the lab role, or the documented environment/profile override.")
    try:
        subprocess.run(["docker", "compose", "version"], check=True, cwd=ROOT)
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise SystemExit("Docker Compose is not available. Use a lab machine with Docker; see START_HERE_NUVEPRO.md.")
    print("Next: docker compose up --build -d --wait")

if __name__ == "__main__":
    main()
