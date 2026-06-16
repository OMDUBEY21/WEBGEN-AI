# generator.py
import os
import re
import time
import json
import itertools
import requests
from typing import Dict, List

# ===============================
# CONFIG (SAFE)
# ===============================

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"

PEXELS_API_URL = "https://api.pexels.com/v1/search"

NAV_GRADIENT = "linear-gradient(90deg, #00448A, #0066CC)"
HEADER_GRADIENT = "linear-gradient(90deg, #007BFF, #00C6FF, #FF4B2B, #FF416C)"

MAX_FILE_CHARS = 10_000
REQUEST_TIMEOUT = 20


# ===============================
# ENV ACCESS (LAZY & SAFE)
# ===============================

def get_api_keys() -> list[str]:
    keys = [k for k in os.getenv("GROQ_API_KEYS", "").split(",") if k]
    if not keys:
        raise RuntimeError("GROQ_API_KEYS environment variable is empty")
    return keys


def get_pexels_key() -> str:
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        raise RuntimeError("PEXELS_API_KEY environment variable is missing")
    return key


# ===============================
# API CLIENT
# ===============================

_session = requests.Session()
_key_cycle = None


def _headers() -> Dict[str, str]:
    global _key_cycle
    if _key_cycle is None:
        _key_cycle = itertools.cycle(get_api_keys())

    return {
        "Authorization": f"Bearer {next(_key_cycle)}",
        "Content-Type": "application/json"
    }


def call_api(payload: dict, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            res = _session.post(
                API_URL,
                headers=_headers(),
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

            if res.status_code == 429:
                time.sleep(1)
                continue

            res.raise_for_status()
            return res.json()["choices"][0]["message"]["content"]

        except Exception as e:
            print(f"❌ API error (attempt {attempt + 1}): {e}")
            time.sleep(1)

    return None


# ===============================
# UTILITIES
# ===============================

def parse_code_blocks(content: str) -> Dict[str, str]:
    pattern = r"---FILE:(.+?)---\n(.*?)(?=(---FILE:|$))"
    matches = re.findall(pattern, content, re.DOTALL)
    return {name.strip(): code.strip() for name, code, _ in matches}


def extract_keywords(prompt: str) -> str:
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": "Extract 3–5 image search keywords."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }

    content = call_api(payload)
    if not content:
        return prompt

    return re.sub(r"[^A-Za-z, ]", "", content)


def fetch_related_image(prompt: str) -> str | None:
    keywords = extract_keywords(prompt).split()[:6]
    query = " ".join(keywords) or "modern website"

    try:
        res = _session.get(
            PEXELS_API_URL,
            headers={"Authorization": get_pexels_key()},
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            timeout=10
        )
        res.raise_for_status()
        photos = res.json().get("photos", [])
        return photos[0]["src"]["large"] if photos else None

    except Exception as e:
        print("⚠️ Pexels error:", e)
        return None


# ===============================
# SITE GENERATION
# ===============================

def plan_site_structure(user_prompt):
    print("📌 Planning site structure...")
    planning_prompt = f"""
        You are an expert web planner AI.

        Given the concept: "{user_prompt}", respond with a JSON list of files (HTML only) you would create,
        each with a short description of its purpose.

        Example output:
        [
        {{"file": "index.html", "description": "Landing page with overview and CTA"}},
        {{"file": "about.html", "description": "Background and mission"}},
        {{"file": "services.html", "description": "Service listings"}},
        {{"file": "contact.html", "description": "Contact form"}}
        ]
        Only return valid JSON. Do not include markdown or explanations.
        """

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a planning assistant."},
            {"role": "user", "content": planning_prompt.strip()}
        ],
        "temperature": 0.3
    }
    content = call_api(payload)
    if not content:
        return []

    try:
        import json
        plan = json.loads(content)
        print(f"✅ Site plan created: {[p['file'] for p in plan]}")
        return plan
    except Exception as e:
        print("❌ Failed to parse site plan:", e)
        print(content)
        return []

def generate_site_code(user_prompt: str, progress_cb=None) -> Dict[str, str]:
    if progress_cb:
        progress_cb("📌 Starting code generation...")

    site_plan = plan_site_structure(user_prompt)
    files = {}

    image_url = fetch_related_image(user_prompt)
    if image_url:
        print(f"🖼️ Using image: {image_url}")
    else:
        print("⚠️ No image found, skipping.")

    for page in site_plan:
        filename = page['file']
        if progress_cb:
            progress_cb(f"🛠 Generating HTML for: {filename}")
        detail_prompt = f"""
Create the full contents of {filename} for the website concept: "{user_prompt}".

If an image placeholder or hero section is used, embed this image:
{image_url or 'No image available'}

Design rules:
- Navbar gradient: {NAV_GRADIENT}
- Header text gradient: {HEADER_GRADIENT}
- Modern clean layout (Poppins/Roboto)
- Consistent navigation across: {[p['file'] for p in site_plan]}.

Wrap contents like:
---FILE:{filename}---
<html>...</html>
"""
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are a frontend developer AI."},
                {"role": "user", "content": detail_prompt.strip()}
            ],
            "temperature": 0.7
        }
        content = call_api(payload)
        if content:
            files.update(parse_code_blocks(content))
        time.sleep(1)

    # Shared CSS & JS
    for shared in ["styles.css", "script.js"]:
        if progress_cb:
            progress_cb(f"🎨 Generating shared asset: {shared}")

        prompt = f"""
Generate {shared} for "{user_prompt}" website.

Fixed:
- Navbar gradient: {NAV_GRADIENT}
- Header gradient text: {HEADER_GRADIENT}
- Font: Poppins or Roboto.

            Wrap the output like this:
            ---FILE:{shared}---
            <code>
            """

        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are a frontend developer AI."},
                {"role": "user", "content": prompt.strip()}
            ],
            "temperature": 0.6
        }
        content = call_api(payload)
        if content:
            files.update(parse_code_blocks(content))
        time.sleep(1)

    if progress_cb:
        progress_cb(f"✅ Code generation complete. Total files: {len(files)}")
    return files

# ===============================
# EDITING
# ===============================

def select_relevant_files(edit_prompt, site_path):
    """Selects relevant files for editing based on user request."""
    all_html_files = []
    for root, _, filenames in os.walk(site_path):
        for name in filenames:
            if name.endswith(".html"):
                base_name = os.path.splitext(name)[0].lower()
                all_html_files.append(base_name)

    # Fallback if no HTML files found
    if not all_html_files:
        all_html_files = ["index", "home", "main"]

    # Find HTML files whose name appears in the user's edit prompt
    selected = [kw for kw in all_html_files if kw in edit_prompt.lower()]
    files = set()  # use set to avoid duplicates

    for root, _, filenames in os.walk(site_path):
        for name in filenames:
            lower_name = name.lower()
            full_path = os.path.join(root, name)

            # Match selected keywords to filenames
            if lower_name.endswith((".html", ".css", ".js")):
                if any(kw in lower_name for kw in selected):
                    files.add(full_path)

    # Always include shared files for consistent updates
    for shared in ["styles.css", "script.js"]:
        for root, _, filenames in os.walk(site_path):
            if shared in filenames:
                files.add(os.path.join(root, shared))

    # Fallback to main files if no specific match
    if not selected and not files:
        for root, _, filenames in os.walk(site_path):
            for name in filenames:
                if name in ["index.html", "styles.css", "script.js"]:
                    files.add(os.path.join(root, name))

    return list(files)


def edit_existing_site(edit_prompt, site_path):
    print("🪄 Editing existing site...")

    # Select files intelligently
    files = {}
    relevant_files = select_relevant_files(edit_prompt, site_path)
    files = {}
    for full_path in relevant_files:
        with open(full_path, "r", encoding="utf-8") as f:
            files[os.path.basename(full_path)] = f.read()

    if not files:
        print("⚠️ No files found to edit.")
        return {}
    
    # Combine selected files into one string
    MAX_FILE_SIZE = 10000  # characters
    files_summary = "\n\n".join([f"---FILE:{name}---\n{content[:MAX_FILE_SIZE]}"for name, content in files.items()])
    
    # Instruction
    edit_instruction = f"""
You are a frontend engineer AI.

Here are the current website files:
{files_summary}

The user wants the following edit:
"{edit_prompt}"

Keep these constants:
- Navbar gradient: {NAV_GRADIENT}
- Header gradient: {HEADER_GRADIENT}
- Font: Poppins or Roboto

Return only updated files in format:
---FILE:filename---
<updated code>
"""

    # API request
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise frontend code editor."},
            {"role": "user", "content": edit_instruction.strip()}
        ],
        "temperature": 0.5
    }

    # Call API and handle large payload fallback
    content = call_api(payload)
    if not content:
        print("⚠️ Edit request failed due to payload size. Falling back to per-file edits.")
        return edit_files_individually(edit_prompt, files)

    updated_files = parse_code_blocks(content)
    print(f"✅ Updated files: {list(updated_files.keys())}")
    return updated_files


def edit_files_individually(edit_prompt, files):
    updated_files = {}
    for filename, content in files.items():
        print(f"✏️ Editing {filename} individually...")

        file_prompt = f"""
Modify this file according to user request:
"{edit_prompt}"

---FILE:{filename}---
{content}

Return only the updated file content.
"""
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are a code editor AI."},
                {"role": "user", "content": file_prompt.strip()}
            ],
            "temperature": 0.5
        }

        resp = call_api(payload)
        if resp:
            updated_files.update(parse_code_blocks(resp))
        time.sleep(0.5)
    return updated_files

def parse_code_blocks(content):
    pattern = r"---FILE:(.+?)---\n(.*?)(?=(---FILE:|$))"
    matches = re.findall(pattern, content, re.DOTALL)
    files = {}
    for filename, code, _ in matches:
        files[filename.strip()] = code.strip()
    return files

def safe_json_loads(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # try auto-fix common truncation
        text = text.strip()
        if text.startswith("[") and not text.endswith("]"):
            try:
                return json.loads(text + "]")
            except Exception:
                pass
        return None
