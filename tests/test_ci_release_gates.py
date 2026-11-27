"""The release gates in CI block a bad image before any tag points at it (OPS-9, OPS-10)."""

import os

import yaml

CI = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".github", "workflows", "ci.yml")


def _jobs():
    with open(CI, encoding="utf-8") as f:
        return yaml.safe_load(f)["jobs"]


def _steps(job="publish"):
    return _jobs()[job]["steps"]


def _index(steps, prefix):
    return next(i for i, s in enumerate(steps) if s.get("name", "").startswith(prefix))


# Each release gate and the job that runs it (the image is built and checked while the tests
# run; CI speed-up, 12 Nov 2026)
GATES = {
    "Smoke-test the built image (amd64": "check-image",
    "Smoke-test the built image (arm64": "smoke-arm64",
    "Scan image with Trivy": "check-image",
    "Upgrade and rollback test": "update-test",
}


def test_arm64_smoke_and_upgrade_tests_are_blocking():
    jobs = _jobs()
    for prefix in ("Smoke-test the built image (arm64", "Upgrade and rollback test"):
        job = jobs[GATES[prefix]]
        step = job["steps"][_index(job["steps"], prefix)]
        assert not step.get("continue-on-error"), prefix
        assert not job.get("continue-on-error"), prefix


def test_every_gate_runs_before_the_image_is_signed_and_tagged():
    jobs = _jobs()
    steps = jobs["publish"]["steps"]
    assert _index(steps, "Sign image digest") < _index(steps, "Publish tags")
    needs = set(jobs["publish"]["needs"])
    # every test job and every image check must pass before anything is signed or tagged
    assert {
        "lint",
        "lint-and-test",
        "frontend",
        "frontend-checks",
        "e2e-integration",
        "still-latest",
        "build-image",
    } <= needs
    assert "frontend-checks" in jobs["still-latest"]["needs"]
    assert "lint" in jobs["still-latest"]["needs"]
    # the idle minute (PERF-10) is still one of the browser-test jobs
    e2e = jobs["e2e-integration"]["strategy"]["matrix"]["include"]
    assert any(e["idle"] is True for e in e2e) and all(e["tests"] for e in e2e if not e["idle"])
    for prefix, job in GATES.items():
        assert job in needs, prefix
        _index(jobs[job]["steps"], prefix)  # the gate is really in that job
        # and is not skipped while the build runs: no condition, or exactly the build's own
        assert jobs[job].get("if") in (None, jobs["build-image"]["if"]), job
    # nothing before the publish job tags or signs the image
    for name, job in jobs.items():
        if name in ("publish", "create-release"):
            continue
        for s in job.get("steps", []):
            run = str(s.get("run", ""))
            assert "cosign sign" not in run, (name, s.get("name"))
            # the join prints the two architectures' index with --dry-run and stores it by digest:
            # a tag is pushed only by publish
            for line in run.splitlines():
                if "imagetools create" in line:
                    assert "--dry-run" in line, (name, s.get("name"), line)
    # a version's release also waits for the update from the release before (os-upgrade); main's
    # publishing does not, so a push deploys as fast as before
    assert jobs["create-release"]["needs"] == ["publish", "os-upgrade", "os-secure-boot"]
    assert "os-upgrade" not in jobs["publish"]["needs"] and "os-secure-boot" not in jobs["publish"]["needs"]
    # a release is signed only after the owner's approval; main keeps publishing without one
    assert jobs["publish"]["environment"] == "${{ startsWith(github.ref, 'refs/tags/v') && 'release' || '' }}"


def test_smoke_script_runs_each_platform_by_its_own_manifest():
    """Running a second platform of an already pulled digest fails ("cannot overwrite digest")."""
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, "scripts", "smoke_test.sh"), encoding="utf-8") as f:
        script = f.read()
    assert "imagetools inspect --raw" in script and 'ref="$repo@$platform_digest"' in script


def test_published_images_can_be_smoke_tested_on_demand():
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, ".github", "workflows", "smoke.yml"), encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    run = wf["jobs"]["smoke"]["steps"][-1]["run"]
    assert "scripts/smoke_test.sh" in run
    assert "${{" not in run  # inputs reach the script through env, never pasted into the shell


def test_changed_backend_lines_must_be_tested():
    """Diff coverage: new code cannot hide behind the overall percentage."""
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        job = yaml.safe_load(f)["jobs"]["lint-and-test"]
    run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "diff-cover coverage.xml" in run and "--fail-under=80" in run
    assert job["steps"][0]["with"]["fetch-depth"] == 0
    with open(os.path.join(root, "requirements-dev.txt"), encoding="utf-8") as f:
        assert "diff-cover==" in f.read()


def test_the_unit_suite_also_runs_on_the_python_kiboto_os_uses():
    """Kiboto OS makes its environment from Debian 13's python3, not the image's Python. The suite
    runs there too, before anything is signed, tagged or deployed."""
    jobs = _jobs()
    job = jobs["unit-debian13"]
    assert job["container"] == "debian:13"  # Debian 13's current Python, as the machines get it
    steps = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "apt-get install" in steps and "python3 python3-venv" in steps
    assert "setup-python" not in str(job["steps"])  # never a Python from elsewhere
    assert "pip install --require-hashes -r requirements.lock" in steps
    assert "-m pytest" in steps and "continue-on-error" not in str(job)
    assert "unit-debian13" in jobs["publish"]["needs"] and "unit-debian13" in jobs["still-latest"]["needs"]
    # a timing test among parallel workers fails by chance: it is timed alone, in the other job
    assert "--deselect tests/test_rag_eval_baseline.py::test_search_stays_fast" in steps
    other = "\n".join(str(step.get("run", "")) for step in jobs["lint-and-test"]["steps"])
    assert "tests/test_rag_eval_baseline.py::test_search_stays_fast" in other


def test_every_browser_test_runs_in_exactly_one_part():
    """The browser tests are split across runners by name; one left out would never run."""
    import ast
    import glob

    root = os.path.dirname(os.path.dirname(__file__))
    every = set()
    for path in glob.glob(os.path.join(root, "tests", "test_e2e_*.py")):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        rel = "tests/" + os.path.basename(path)
        every |= {
            f"{rel}::{n.name}" for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        }
    seen = []
    for part in _jobs()["e2e-integration"]["strategy"]["matrix"]["include"]:
        words = str(part["tests"]).split()
        dropped = {words[i + 1] for i, w in enumerate(words) if w == "--deselect"}
        for w in words:
            if w == "--deselect" or w in dropped:
                continue
            if "::" in w:
                seen.append(w)
            else:
                seen += [t for t in every if t.startswith(w + "::") and t not in dropped]
    assert sorted(seen) == sorted(every), "a browser test runs twice or never"
