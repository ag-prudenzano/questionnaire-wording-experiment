from pathlib import Path
import os, re, stat, subprocess, tempfile

ROOT=Path(__file__).resolve().parent
TITLE,SLUG,DATE="Questionnaire Wording Experiment","questionnaire-wording-experiment","2026"
LEDE="A simulated randomised survey experiment measuring how benefit and effort framing affect response distributions, agreement, item nonresponse and completion behaviour."
WEBSITE="ag-prudenzano/ag-prudenzano.github.io"; REMOTE=f"https://github.com/{WEBSITE}.git"; BRANCH="main"
TEMPLATE="survey-response-quality-audit.html"; TOKEN="PORTFOLIO_PUBLISH_TOKEN"


def run(args,cwd,check=True,env=None): return subprocess.run(args,cwd=cwd,check=check,capture_output=True,text=True,env=env)


def clean(): return not run(["git","status","--porcelain","--","report.md","data","outputs","figures"],ROOT).stdout.strip()


def auth(temp):
    if not os.environ.get(TOKEN," ").strip(): raise RuntimeError(f"Automatic website publishing needs the repository secret {TOKEN} with write access to {WEBSITE}.")
    ask=temp/"git-askpass.sh"; ask.write_text('#!/bin/sh\ncase "$1" in\n *Username*) printf "%s\\n" "x-access-token" ;;\n *) printf "%s\\n" "$PORTFOLIO_PUBLISH_TOKEN" ;;\nesac\n',encoding="utf-8"); ask.chmod(ask.stat().st_mode|stat.S_IXUSR)
    env=os.environ.copy(); env.update({"GIT_ASKPASS":str(ask),"GIT_TERMINAL_PROMPT":"0","GIT_CONFIG_COUNT":"1","GIT_CONFIG_KEY_0":"credential.helper","GIT_CONFIG_VALUE_0":""}); env.pop("GITHUB_TOKEN",None); return env


def update_map(text):
    entry=f'  "{TITLE}": {{\n    href: "{SLUG}.html",\n    date: "{DATE}",\n  }},'
    pattern=re.compile(rf'  "{re.escape(TITLE)}": \{{\n    href: "[^"]+",\n    date: "[^"]+",\n  \}},')
    if pattern.search(text): return pattern.sub(entry,text,count=1)
    marker="const publishedPortfolioStudies = {\n"
    if marker not in text: raise RuntimeError("Could not find website publication map in script.js.")
    return text.replace(marker,marker+entry+"\n",1)


def publish_website():
    if not (ROOT/"report.md").exists(): print("Website publishing skipped: report.md does not exist."); return
    if not clean(): print("Website publishing skipped because generated files are uncommitted."); return
    commit=run(["git","rev-parse","--short","HEAD"],ROOT).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="portfolio-website-") as td:
        temp=Path(td); site=temp/"website"; env=auth(temp)
        clone=run(["git","clone","--depth","1","--branch",BRANCH,REMOTE,str(site)],temp,False,env)
        if clone.returncode: raise RuntimeError(f"Could not clone website repository: {(clone.stderr or clone.stdout).strip()}")
        name=run(["git","config","user.name"],ROOT,False).stdout.strip() or "AG Prudenzano"; email=run(["git","config","user.email"],ROOT,False).stdout.strip() or "309410350+ag-prudenzano@users.noreply.github.com"
        run(["git","config","user.name",name],site); run(["git","config","user.email",email],site)
        script=site/"script.js"; script.write_text(update_map(script.read_text(encoding="utf-8")),encoding="utf-8")
        template=(site/TEMPLATE).read_text(encoding="utf-8"); page=template.replace("Survey Response Quality Audit",TITLE).replace("survey-response-quality-audit",SLUG).replace("A simulated audit of 1,250 UK online survey responses using eight respondent-level quality checks to identify records for review or exclusion.",LEDE)
        (site/f"{SLUG}.html").write_text(page,encoding="utf-8")
        index=site/"index.html"; index.write_text(re.sub(r'script\.js\?v=[^"]+',f"script.js?v=published-{SLUG}-{commit}",index.read_text(encoding="utf-8"),count=1),encoding="utf-8")
        if not run(["git","status","--porcelain"],site).stdout.strip(): print("Website is already up to date."); return
        run(["git","add","--","script.js","index.html",f"{SLUG}.html"],site); run(["git","commit","-m",f"Publish {TITLE}"],site)
        push=run(["git","push","origin",BRANCH],site,False,env)
        if push.returncode: raise RuntimeError(f"Could not push website update: {(push.stderr or push.stdout).strip()}")
        print(f"Website updated and pushed to {WEBSITE}.")
