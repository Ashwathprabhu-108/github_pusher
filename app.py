import os
import shutil
import subprocess
import tempfile
import zipfile
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

HTML = open(os.path.join(os.path.dirname(__file__), "index.html"), encoding="utf-8").read()

@app.route("/")
def index():
    return HTML

@app.route("/push", methods=["POST"])
def push():
    repo_url   = request.form.get("repo_url", "").strip()
    branch     = request.form.get("branch", "main").strip() or "main"
    commit_msg = request.form.get("commit_msg", "Initial commit").strip() or "Initial commit"
    username   = request.form.get("username", "").strip()
    token      = request.form.get("token", "").strip()
    folder_zip = request.files.get("folder")

    if not repo_url:
        return jsonify(success=False, error="Repository URL is required.")
    if not folder_zip:
        return jsonify(success=False, error="No folder/zip file uploaded.")

    # Inject credentials into URL
    auth_url = repo_url
    if token and repo_url.startswith("https://"):
        user_part = f"{username}:{token}@" if username else f"{token}@"
        auth_url = repo_url.replace("https://", f"https://{user_part}")

    work_dir = tempfile.mkdtemp()
    try:
        zip_path = os.path.join(work_dir, "upload.zip")
        folder_zip.save(zip_path)

        extract_dir = os.path.join(work_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)

        # Skip single wrapper folder
        entries = os.listdir(extract_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            project_root = os.path.join(extract_dir, entries[0])
        else:
            project_root = extract_dir

        repo_dir = os.path.join(work_dir, "repo")
        os.makedirs(repo_dir, exist_ok=True)

        def git(args, cwd=None):
            return subprocess.run(
                ["git"] + args,
                cwd=cwd or repo_dir,
                capture_output=True, text=True
            )

        clone = git(["clone", auth_url, repo_dir])
        if clone.returncode != 0:
            os.makedirs(repo_dir, exist_ok=True)
            git(["init"], cwd=repo_dir)
            git(["remote", "add", "origin", auth_url], cwd=repo_dir)

        # Copy project files into cloned repo
        for item in os.listdir(project_root):
            if item == ".git":
                continue
            src = os.path.join(project_root, item)
            dst = os.path.join(repo_dir, item)
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        git(["config", "user.email", "gitpusher@tool.local"])
        git(["config", "user.name",  "Git Pusher Tool"])
        git(["add", "-A"])
        commit = git(["commit", "-m", commit_msg])

        if commit.returncode != 0 and "nothing to commit" in (commit.stdout + commit.stderr):
            return jsonify(success=False, error="Nothing to commit — repo already has this content.")

        push_result = git(["push", "-u", "origin", f"HEAD:{branch}", "--force"])
        if push_result.returncode != 0:
            return jsonify(success=False, error=f"Push failed:\n{push_result.stderr or push_result.stdout}")

        return jsonify(success=True, message=f"✓ Successfully pushed to '{branch}' branch!")

    except zipfile.BadZipFile:
        return jsonify(success=False, error="Uploaded file is not a valid ZIP archive.")
    except Exception as e:
        import traceback
        return jsonify(success=False, error=f"{str(e)}\n{traceback.format_exc()}")
    finally:
        try:
            for root, dirs, files in os.walk(work_dir, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(work_dir)
        except Exception:
            pass

if __name__ == "__main__":
    app.run(debug=True, port=5000)