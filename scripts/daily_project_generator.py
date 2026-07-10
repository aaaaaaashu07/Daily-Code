"""
Daily Project Generator (Google Gemini version)
--------------------------------------------------
Reads projects.csv, picks the next unfinished idea, asks Gemini to generate
a complete project, writes the files, zips it, and marks the idea as generated.

Run this once a day (cron / Windows Task Scheduler / GitHub Actions).
You review and commit yourself.
"""

import csv
import os
import json
import zipfile
import shutil
from pathlib import Path
from google import genai
from google.genai import types

REPO_PATH = Path(os.environ.get("REPO_PATH", "."))
PROJECTS_CSV = REPO_PATH / "projects.csv"

OUTPUT_DIR = "output"
PROJECTS_SUBDIR = "projects"


MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash-lite"
)

api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("Missing GEMINI_API_KEY environment variable")

client = genai.Client(api_key=api_key)

def load_projects():
    with open(PROJECTS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_projects(rows):
    with open(PROJECTS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["idea", "status"])
        writer.writeheader()
        writer.writerows(rows)


def get_next_idea(rows):
    for row in rows:
        if row["status"].strip().lower() == "pending":
            return row
    return None


def generate_project(idea: str) -> dict:
    prompt = f"""Generate a complete, working, POLISHED software project for: "{idea}"

Pick the lightest stack that suits this specific idea — most of these should be
plain HTML/CSS/JS (no build step) or a single-file Python script, unless the idea
genuinely needs a backend/API (e.g. anything calling a live API like weather,
crypto, or GitHub data — for those, a small Flask or Node/Express backend is fine).
Do not force React/FastAPI/Postgres onto a simple utility — that's overkill and
more likely to fail to generate cleanly.

Respond ONLY with valid JSON. No markdown fences, no preamble, no explanation.

Format:
{{
  "project_name": "kebab-case-name",
  "files": {{
    "path/to/file.ext": "full file content as a string",
    "README.md": "..."
  }}
}}

Requirements:
- README.md must include: a one-line description, a features list, install/run
  instructions, and a "Screenshots" section placeholder (e.g. "![screenshot](screenshot.png)")
  the user can fill in after running it locally.
- UI must be clean and modern, not bare/unstyled HTML — think reasonable spacing,
  a clear color scheme, and legible typography.
- Include a dark mode toggle and responsive layout wherever the idea has a UI
  (skip this only for pure CLI/script tools). Layout must adapt cleanly to both
  portrait and landscape orientation and to mobile/tablet/desktop widths — use
  real CSS media queries (width and orientation), not just a single fixed layout.
- Include .gitignore and any dependency file (requirements.txt / package.json) only
  if the project actually has dependencies.
- Write real, working code - no TODOs or placeholder stubs.
- Keep scope tight: this should be buildable and testable in a single sitting,
  not an enterprise system.
"""
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=6000,
            temperature=0.7,
            response_mime_type="application/json",  # nudges Gemini to return raw JSON, no fences
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")

    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print("\nGemini returned invalid JSON:\n")
        print(text)
        raise


def write_project(project_data: dict) -> Path:
    name = project_data["project_name"]
    root = REPO_PATH / PROJECTS_SUBDIR / name
    if root.exists():
        shutil.rmtree(root)
    for rel_path, content in project_data["files"].items():
        file_path = root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return root


def zip_project(root_path: Path) -> Path:
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    zip_path = Path(OUTPUT_DIR) / f"{root_path.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in root_path.rglob("*"):
            zf.write(file, file.relative_to(root_path.parent))
    return zip_path


def main():
    rows = load_projects()
    idea_row = get_next_idea(rows)

    if not idea_row:
        print("All 100 projects done. Add more ideas to projects.csv.")
        return

    idea = idea_row["idea"]
    print(f"Generating: {idea}")

    try:
        project_data = generate_project(idea)
        root = write_project(project_data)
        if os.environ.get("CI") == "true":
            print(f"Generated -> {root} (CI run, skipping local zip backup)")
        else:
            zip_path = zip_project(root)
            print(f"Generated -> {zip_path}")
    except json.JSONDecodeError:
        print(f"Model didn't return valid JSON for '{idea}'. Try again tomorrow, or lower scope.")
        return
    except Exception as e:
        print(f"Failed on '{idea}': {e}")
        return

    idea_row["status"] = "generated"   # dashboard/PR review flips this to "committed" after you push
    save_projects(rows)
    print("Open the dashboard to review and push: streamlit run dashboard.py")


if __name__ == "__main__":
    main()