from pathlib import Path
import subprocess

try:
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
except ImportError as exc:
    raise SystemExit("Missing packages. Install with: pip install -r requirements.txt") from exc

ROOT = Path(__file__).resolve().parent
DATA, OUTPUTS, FIGURES = ROOT / "data", ROOT / "outputs", ROOT / "figures"
REPORT_FILE = ROOT / "report.md"
SEED, N = 20260811, 2400
ARMS = ["Neutral", "Benefit-framed", "Effort-framed"]
QUESTIONS = {
    "Neutral": "How likely are you to use the council's new online services?",
    "Benefit-framed": "How likely are you to use the council's new online services, which can save residents time?",
    "Effort-framed": "How likely are you to use the council's new online services, even if setup takes a few minutes?",
}
BG, TEXT, MUTED, GRID = "#0C0C0D", "#FFFFFF", "#A2A2A9", "#313135"
COLORS = ["#777780", "#E6E6E8", "#AFAFB5"]


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, check=check, capture_output=True, text=True)


def check_repository_up_to_date():
    if git("rev-parse", "--is-inside-work-tree", check=False).returncode:
        return False
    branch = git("branch", "--show-current").stdout.strip()
    if not branch or git("remote", "get-url", "origin", check=False).returncode:
        return False
    git("fetch", "origin")
    if git("rev-parse", "--verify", "--quiet", f"origin/{branch}", check=False).returncode:
        return False
    local, remote = map(int, git("rev-list", "--left-right", "--count", f"HEAD...origin/{branch}").stdout.split())
    if remote:
        raise SystemExit(f"Checkout is {remote} commit(s) behind origin/{branch}; pull before rerunning.")
    print(f"Repository is up to date with origin/{branch}.")
    return True


def save_generated_files(sync):
    if not sync:
        return
    paths = ["report.md", "data", "outputs", "figures"]
    git("add", "--", *paths)
    changed = git("diff", "--cached", "--quiet", "--", *paths, check=False).returncode
    if changed == 0:
        print("No generated changes to commit.")
        return
    if changed != 1:
        raise SystemExit("Could not inspect generated changes.")
    git("commit", "-m", "Update questionnaire wording experiment results", "--", *paths)
    branch = git("branch", "--show-current").stdout.strip()
    git("push", "origin", branch)
    print(f"Generated files committed and pushed to origin/{branch}.")


def simulate():
    rng = np.random.default_rng(SEED)
    assignment = np.repeat(ARMS, N // len(ARMS)); rng.shuffle(assignment)
    age = rng.choice(["18-34", "35-54", "55+"], N, p=[.31, .37, .32])
    gender = rng.choice(["Woman", "Man", "Non-binary / self-describe"], N, p=[.505, .475, .02])
    digital = np.clip(rng.normal(0, 1, N) + np.where(age == "55+", -.45, np.where(age == "18-34", .35, 0)), -2.5, 2.5)
    arm_shift = pd.Series(assignment).map({"Neutral": 0, "Benefit-framed": .34, "Effort-framed": -.27}).to_numpy()
    heterogeneity = np.where((assignment == "Effort-framed") & (age == "55+"), -.22, 0)
    latent = 3.15 + .46 * digital + arm_shift + heterogeneity + rng.normal(0, 1.05, N)
    response = np.clip(np.rint(latent), 1, 5).astype(float)
    miss_logit = -3.45 + np.where(assignment == "Effort-framed", .58, 0) + np.where(age == "55+", .25, 0)
    missing = rng.random(N) < 1 / (1 + np.exp(-miss_logit))
    response[missing] = np.nan
    duration = np.maximum(55, rng.lognormal(np.log(205), .34, N) + np.where(assignment == "Effort-framed", 19, np.where(assignment == "Benefit-framed", 5, 0)))
    complete_logit = 3.35 - .0032 * (duration - 200) + np.where(assignment == "Effort-framed", -.38, 0) + np.where(missing, -.55, 0)
    completed = rng.random(N) < 1 / (1 + np.exp(-complete_logit))
    frame = pd.DataFrame({
        "respondent_id": [f"R{i:04d}" for i in range(1, N + 1)], "wording_arm": assignment,
        "question_wording": pd.Series(assignment).map(QUESTIONS), "age_band": age, "gender": gender,
        "digital_confidence_z": np.round(digital, 3), "likelihood_1_5": response,
        "item_missing": missing.astype(int), "survey_completed": completed.astype(int),
        "completion_seconds": np.round(duration).astype(int),
    })
    return frame


def proportion_ci(x):
    n, p = len(x), float(np.mean(x)); se = np.sqrt(p * (1 - p) / n)
    return p, max(0, p - 1.96 * se), min(1, p + 1.96 * se)


def analyse(df):
    rows = []
    for arm in ARMS:
        x = df[df.wording_arm.eq(arm)]; valid = x.likelihood_1_5.dropna()
        agree, alo, ahi = proportion_ci(valid.ge(4))
        missing, mlo, mhi = proportion_ci(x.item_missing)
        complete, clo, chi = proportion_ci(x.survey_completed)
        rows.append([arm, len(x), len(valid), valid.mean(), valid.std(), agree, alo, ahi, missing, mlo, mhi, complete, clo, chi, x.completion_seconds.median()])
    summary = pd.DataFrame(rows, columns=["wording_arm", "assigned_n", "valid_n", "mean_likelihood", "sd_likelihood", "agreement_rate", "agreement_ci_low", "agreement_ci_high", "item_nonresponse_rate", "nonresponse_ci_low", "nonresponse_ci_high", "completion_rate", "completion_ci_low", "completion_ci_high", "median_completion_seconds"])
    neutral = df[df.wording_arm.eq("Neutral")]
    effects = []
    for arm in ARMS[1:]:
        treat = df[df.wording_arm.eq(arm)]
        a, b = treat.likelihood_1_5.dropna(), neutral.likelihood_1_5.dropna()
        diff = a.mean() - b.mean(); se = np.sqrt(a.var(ddof=1)/len(a) + b.var(ddof=1)/len(b))
        pooled = np.sqrt(((len(a)-1)*a.var(ddof=1)+(len(b)-1)*b.var(ddof=1))/(len(a)+len(b)-2))
        for outcome, ta, tb in [("Mean likelihood (points)", a, b), ("Agreement rate (pp)", a.ge(4).astype(float)*100, b.ge(4).astype(float)*100), ("Item nonresponse (pp)", treat.item_missing*100, neutral.item_missing*100), ("Completion rate (pp)", treat.survey_completed*100, neutral.survey_completed*100)]:
            d = ta.mean()-tb.mean(); s = np.sqrt(ta.var(ddof=1)/len(ta)+tb.var(ddof=1)/len(tb))
            effects.append([arm, outcome, d, d-1.96*s, d+1.96*s, diff/pooled if outcome.startswith("Mean") else np.nan])
    effects = pd.DataFrame(effects, columns=["contrast_vs_neutral", "outcome", "effect", "ci_low", "ci_high", "cohens_d"])
    dist = (df.dropna(subset=["likelihood_1_5"]).groupby(["wording_arm", "likelihood_1_5"]).size().rename("n").reset_index())
    dist["share"] = dist.n / dist.groupby("wording_arm").n.transform("sum")
    subgroup = df.dropna(subset=["likelihood_1_5"]).groupby(["age_band", "wording_arm"], observed=True).agg(n=("respondent_id", "size"), mean_likelihood=("likelihood_1_5", "mean"), agreement_rate=("likelihood_1_5", lambda s: s.ge(4).mean())).reset_index()
    return summary, effects, dist, subgroup


def style(ax, grid="y"):
    ax.figure.patch.set_facecolor(BG); ax.set_facecolor(BG); ax.tick_params(colors=MUTED, length=0, pad=7)
    for s in ax.spines.values(): s.set_visible(False)
    ax.grid(axis=grid, color=GRID, linewidth=.8); ax.set_axisbelow(True); ax.title.set_color(TEXT)
    ax.xaxis.label.set_color(MUTED); ax.yaxis.label.set_color(MUTED)


def create_figures(summary, effects, dist, subgroup):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5.8)); style(ax); x=np.arange(1,6); w=.24
    for i, arm in enumerate(ARMS):
        vals=dist[dist.wording_arm.eq(arm)].set_index("likelihood_1_5").share.reindex(x, fill_value=0)
        ax.bar(x+(i-1)*w, vals*100, w, label=arm, color=COLORS[i])
    ax.set(title="Response distributions shift with questionnaire wording", xlabel="Likelihood response (1–5)", ylabel="Share of valid responses (%)", xticks=x); ax.legend(frameon=False, labelcolor=TEXT)
    fig.tight_layout(); fig.savefig(FIGURES/"response_distributions.png", dpi=180, facecolor=BG); plt.close(fig)
    plot=effects[effects.outcome.isin(["Agreement rate (pp)", "Item nonresponse (pp)", "Completion rate (pp)"])].copy(); plot["label"]=plot.contrast_vs_neutral+" — "+plot.outcome
    fig, ax=plt.subplots(figsize=(10,6)); style(ax, "x"); y=np.arange(len(plot)); ax.axvline(0,color=TEXT,lw=1)
    ax.errorbar(plot.effect,y,xerr=[plot.effect-plot.ci_low,plot.ci_high-plot.effect],fmt="o",color=TEXT,ecolor="#888890",capsize=3)
    ax.set(yticks=y,yticklabels=plot.label, xlabel="Difference versus neutral (percentage points)", title="Wording effects with 95% confidence intervals"); fig.tight_layout(); fig.savefig(FIGURES/"effect_sizes_confidence_intervals.png",dpi=180,facecolor=BG); plt.close(fig)
    pivot=subgroup.pivot(index="age_band",columns="wording_arm",values="agreement_rate").reindex(columns=ARMS)*100
    fig,ax=plt.subplots(figsize=(9.5,5.6)); style(ax); x=np.arange(len(pivot)); w=.24
    for i,arm in enumerate(ARMS): ax.bar(x+(i-1)*w,pivot[arm],w,label=arm,color=COLORS[i])
    ax.set(xticks=x,xticklabels=pivot.index,ylabel="Agreement rate (%)",title="Age patterns suggest stronger effort-framing sensitivity among older adults"); ax.legend(frameon=False,labelcolor=TEXT); fig.tight_layout(); fig.savefig(FIGURES/"agreement_by_age.png",dpi=180,facecolor=BG); plt.close(fig)


def pct(x): return f"{100*x:.1f}%"


def generate_report(df, summary, effects):
    s=summary.set_index("wording_arm"); e=effects.set_index(["contrast_vs_neutral","outcome"])
    rows="\n".join(f"| {a} | {s.loc[a,'mean_likelihood']:.2f} | {pct(s.loc[a,'agreement_rate'])} | {pct(s.loc[a,'item_nonresponse_rate'])} | {pct(s.loc[a,'completion_rate'])} | {s.loc[a,'median_completion_seconds']:.0f}s |" for a in ARMS)
    erows="\n".join(f"| {a} | {o} | {r.effect:+.2f} | [{r.ci_low:+.2f}, {r.ci_high:+.2f}] |" for (a,o),r in e.iterrows())
    report=f"""# Questionnaire Wording Experiment

## Project Snapshot

| Project type | Dataset | Tools | Outputs |
|---|---|---|---|
| Simulated Survey Experiment | {len(df):,} Randomly Assigned UK Adult Respondents | Python / Pandas / NumPy / Matplotlib | Arm-Level Metrics; A/B Contrasts; Effect Sizes; Confidence Intervals; Subgroup Audit; Dark Figures |

**Skills demonstrated:** Experimental Design · Survey Design · Questionnaire Development · Statistical Analysis · Significance Testing · A/B Testing

## Study Context

This simulated experiment evaluates whether short additions to a questionnaire item change reported likelihood of using a fictional council's online services. Respondents were randomly assigned in equal proportions to neutral wording, a benefit frame mentioning time saved, or an effort frame mentioning setup time. All respondents, organisations and outcomes are synthetic.

## Experimental Design

The three arms differ by one clause while retaining the same five-point response scale. Random assignment identifies the intention-to-treat effect of wording under the simulation. The neutral arm is the pre-specified control; agreement (responses 4–5) is the primary binary outcome. Mean response, item nonresponse, survey completion and duration are secondary outcomes.

| Arm | Questionnaire wording |
|---|---|
"""+"\n".join(f"| {a} | {QUESTIONS[a]} |" for a in ARMS)+f"""

## Results

| Wording arm | Mean (1–5) | Agreement | Item nonresponse | Completion | Median duration |
|---|---:|---:|---:|---:|---:|
{rows}

The benefit frame increased agreement by {e.loc[("Benefit-framed","Agreement rate (pp)"),'effect']:+.1f} percentage points versus neutral (95% CI {e.loc[("Benefit-framed","Agreement rate (pp)"),'ci_low']:+.1f} to {e.loc[("Benefit-framed","Agreement rate (pp)"),'ci_high']:+.1f}). The effort frame changed agreement by {e.loc[("Effort-framed","Agreement rate (pp)"),'effect']:+.1f} points (95% CI {e.loc[("Effort-framed","Agreement rate (pp)"),'ci_low']:+.1f} to {e.loc[("Effort-framed","Agreement rate (pp)"),'ci_high']:+.1f}). These shifts arise from wording alone because assignment is random.

## Effect Sizes and Confidence Intervals

| Contrast | Outcome | Effect | 95% CI |
|---|---|---:|---:|
{erows}

For the mean scale, Cohen's d was {e.loc[("Benefit-framed","Mean likelihood (points)"),'cohens_d']:+.2f} for benefit framing and {e.loc[("Effort-framed","Mean likelihood (points)"),'cohens_d']:+.2f} for effort framing. Confidence intervals use large-sample independent-group standard errors; intervals excluding zero correspond to a two-sided 5% significance test.

## Completion Behaviour and Heterogeneity

Effort framing produced both a longer median interview and lower completion, consistent with the clause making burden more salient. The age audit is exploratory: the simulated negative effort effect is strongest among respondents aged 55+, so it should be treated as a diagnostic rather than a separately powered confirmatory test.

## Interpretation

The experiment demonstrates that apparently modest questionnaire edits can change substantive estimates and response behaviour. Benefit language raises expressed adoption likelihood; effort language lowers it and modestly increases response burden. A production survey should select neutral wording when the goal is measurement rather than persuasion, pre-register one primary estimand, and test wording before trend comparisons or rollout.

## Figures

### Response distributions

![Response distributions](figures/response_distributions.png)

### Effect sizes and confidence intervals

![Effect sizes and confidence intervals](figures/effect_sizes_confidence_intervals.png)

### Agreement by age

![Agreement by age](figures/agreement_by_age.png)

## Project Files

- [`data/questionnaire_wording_responses.csv`](data/questionnaire_wording_responses.csv) — respondent-level synthetic experiment.
- [`data/questionnaire_wording_codebook.csv`](data/questionnaire_wording_codebook.csv) — variable definitions.
- [`data/questionnaire_wording_scenario.csv`](data/questionnaire_wording_scenario.csv) — deterministic design parameters and wording.
- [`outputs/arm_summary.csv`](outputs/arm_summary.csv) — response, nonresponse and completion metrics by arm.
- [`outputs/experimental_effects.csv`](outputs/experimental_effects.csv) — control contrasts, effect sizes and 95% confidence intervals.
- [`outputs/response_distribution.csv`](outputs/response_distribution.csv) — five-point response distribution by arm.
- [`outputs/subgroup_heterogeneity.csv`](outputs/subgroup_heterogeneity.csv) — exploratory age-band results.
- [`figures/`](figures/) — publication-ready dark-theme figures.
"""
    REPORT_FILE.write_text(report.strip()+"\n",encoding="utf-8")


def main():
    sync=check_repository_up_to_date(); DATA.mkdir(exist_ok=True); OUTPUTS.mkdir(exist_ok=True); FIGURES.mkdir(exist_ok=True)
    df=simulate(); summary,effects,dist,subgroup=analyse(df)
    df.to_csv(DATA/"questionnaire_wording_responses.csv",index=False)
    pd.DataFrame([[c,d] for c,d in [("respondent_id","Synthetic respondent identifier"),("wording_arm","Randomised wording condition"),("question_wording","Displayed item text"),("age_band","Age subgroup"),("gender","Simulated gender"),("digital_confidence_z","Standardised digital confidence"),("likelihood_1_5","Five-point outcome; blank means item nonresponse"),("item_missing","Item nonresponse indicator"),("survey_completed","Survey completion indicator"),("completion_seconds","Total survey duration")]],columns=["variable","description"]).to_csv(DATA/"questionnaire_wording_codebook.csv",index=False)
    scenario = [["seed", SEED], ["respondents", N], ["allocation", "1:1:1"]]
    scenario.extend(
        [[f"wording_{a.lower().replace('-', '_')}", q] for a, q in QUESTIONS.items()]
    )
    pd.DataFrame(scenario, columns=["parameter", "value"]).to_csv(
        DATA / "questionnaire_wording_scenario.csv", index=False
    )
    summary.to_csv(OUTPUTS/"arm_summary.csv",index=False); effects.to_csv(OUTPUTS/"experimental_effects.csv",index=False); dist.to_csv(OUTPUTS/"response_distribution.csv",index=False); subgroup.to_csv(OUTPUTS/"subgroup_heterogeneity.csv",index=False)
    create_figures(summary,effects,dist,subgroup); generate_report(df,summary,effects)
    print("Questionnaire Wording Experiment\n================================")
    for _,r in summary.iterrows(): print(f"  {r.wording_arm}: agreement={r.agreement_rate:.1%}, missing={r.item_nonresponse_rate:.1%}, completion={r.completion_rate:.1%}")
    print("\nReport written to: report.md\nOutputs saved to: outputs/\nFigures saved to: figures/")
    save_generated_files(sync)


if __name__ == "__main__": main()
