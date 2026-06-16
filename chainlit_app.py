# chainlit_app.py
import chainlit as cl
import os
import re
import zipfile
import shutil
from datetime import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

from generator import generate_site_code, edit_existing_site
from deploy.vercel_factory import DefaultVercelDeployFactory


# ===============================
# CONFIG
# ===============================

TOKEN = os.getenv("VERCEL_TOKEN")
if not TOKEN:
    raise RuntimeError("VERCEL_TOKEN environment variable is not set")

OUTPUT_DIR = "output"


# ===============================
# LOGGING (UI VISIBLE)
# ===============================

async def log_step(text: str):
    await cl.Message(content=text).send()


# ===============================
# HELPERS
# ===============================

STOP_WORDS = {
    "create", "build", "make", "design", "generate",
    "website", "web", "page", "pages", "site",
    "for", "a", "an", "the", "with", "and", "to",
    "one", "simple", "modern", "responsive"
}


def smart_project_name(prompt: str) -> str:
    words = re.findall(r"[a-z0-9]+", prompt.lower())
    keywords = [w for w in words if w not in STOP_WORDS]
    core = keywords[:3] if keywords else ["webgen"]
    return f"{'-'.join(core)}-site"


def is_edit_request(prompt: str) -> bool:
    return prompt.lower().strip().startswith(
        ("edit", "update", "change", "modify", "replace")
    )


def save_files(files_dict: dict, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    for filepath, content in files_dict.items():
        full_path = os.path.join(output_dir, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        mode = "wb" if isinstance(content, bytes) else "w"
        with open(full_path, mode, encoding=None if "b" in mode else "utf-8") as f:
            f.write(content)


def zip_output(folder: str, zip_path: str):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder):
            for filename in files:
                filepath = os.path.join(root, filename)
                arcname = os.path.relpath(filepath, folder)
                zipf.write(filepath, arcname=arcname)


def zip_and_send(folder: str, zip_path: str, message_id: str):
    zip_output(folder, zip_path)
    return cl.File(
        name=os.path.basename(zip_path),
        path=zip_path
    ).send(for_id=message_id)


def get_clean_vercel_domain(deployment_url: str | None) -> str | None:
    if not deployment_url:
        return None

    hostname = urlparse(deployment_url).hostname
    if not hostname:
        return None

    prefix = hostname.split("-")[0]
    return f"https://{prefix}.vercel.app"


# ===============================
# CHAINLIT EVENTS
# ===============================

@cl.on_chat_start
async def on_chat_start():
    user = cl.user_session.get("user")
    username = user.identifier if user else "there"

    await cl.Message(
        content=(
            f"Hello {username} 👋\n\n"
            "### ✨ Welcome to Webgen ✨\n"
            "**Type your idea and I’ll build the site for you.**\n\n"
            "💡 Example prompts:\n"
            "- E-commerce store\n"
            "- Portfolio website\n"
            "- SaaS landing page\n"
            "- Admin dashboard\n\n"
            "✏️ To edit a site, start your message with **edit**, **update**, or **change**."
        ),
        author="System"
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    prompt = message.content.strip()
    await log_step(f"🧠 Prompt received: {prompt}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    is_edit = is_edit_request(prompt)

    # zip_name = f"site_edit_{timestamp}.zip" if is_edit else f"site_{timestamp}.zip"
    project_name = smart_project_name(prompt)
    zip_name = f"site_edit_{project_name}-{timestamp}.zip" if is_edit else f"site_{project_name}-{timestamp}.zip"
    zip_path = os.path.join(OUTPUT_DIR, zip_name)

    last_site_path = cl.user_session.get("last_site_path")

    try:
        # ===========================
        # EDIT EXISTING SITE
        # ===========================
        if is_edit and last_site_path and os.path.exists(last_site_path):
            await log_step("✏️ Editing existing site...")

            updated_files = edit_existing_site(prompt, last_site_path)
            if not updated_files:
                await log_step("⚠️ No changes detected.")
                return

            save_files(updated_files, last_site_path)
            await zip_and_send(last_site_path, zip_path, message.id)

            project_name = smart_project_name(prompt)
            await log_step(f"🚀 Deploying as: {project_name}.vercel.app")

            factory = DefaultVercelDeployFactory(
                site_dir=last_site_path,
                project_name=project_name,
                org_id=None,
                token=TOKEN
            )

            deployment_url = factory.create_deployer().run_deploy()
            domain = get_clean_vercel_domain(deployment_url)

            if domain:
                await log_step(f"🌍 Updated site live at: {domain}")
            return

        # ===========================
        # GENERATE NEW SITE
        # ===========================
        run_dir = os.path.join(OUTPUT_DIR, f"site_{timestamp}")
        shutil.rmtree(run_dir, ignore_errors=True)
        os.makedirs(run_dir, exist_ok=True)

        async def ui_log(msg: str):
            await cl.Message(content=msg).send()

        def progress_cb(msg: str):
            cl.run_sync(ui_log(msg))


        await log_step("🚀 Generating new site...")
        files = generate_site_code(prompt, progress_cb=progress_cb)
        save_files(files, run_dir)

        cl.user_session.set("last_site_path", run_dir)
        await zip_and_send(run_dir, zip_path, message.id)

        project_name = smart_project_name(prompt)
        await log_step(f"🚀 Deploying as: {project_name}.vercel.app")

        factory = DefaultVercelDeployFactory(
            site_dir=run_dir,
            project_name=project_name,
            org_id=None,
            token=TOKEN
        )

        deployment_url = factory.create_deployer().run_deploy()
        domain = get_clean_vercel_domain(deployment_url)
        

        if domain:
            await log_step(f"🌍 Live site available at: https://{project_name}.vercel.app")

    except Exception as e:
        await log_step(f"❌ Error: {e}")
