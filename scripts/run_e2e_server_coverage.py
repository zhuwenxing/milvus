"""Run one Python client case per isolated Milvus deployment and collect server coverage."""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

COVERAGE_ROOT = "/tmp/milvus-e2e-coverage"
REPO = Path(__file__).resolve().parent.parent


def command(argv, *, env=None, input_text=None, check=True):
    result = subprocess.run(
        argv,
        cwd=REPO,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"{' '.join(argv)} failed: stderr={result.stderr[-2000:]!r}; "
            f"stdout={result.stdout[-2000:]!r}"
        )
    return result


def json_command(argv, **kwargs):
    return json.loads(command(argv, **kwargs).stdout)


def validate_case(case_id):
    """Limit -k to an unambiguous, non-parameterized Python test function."""
    parts = case_id.split("::")
    if len(parts) not in (2, 3) or not parts[0].startswith("tests/python_client/"):
        raise ValueError(f"case must be a Python client pytest node ID: {case_id}")
    path = REPO / parts[0]
    if not path.resolve().is_relative_to((REPO / "tests/python_client").resolve()):
        raise ValueError(f"test file must remain under tests/python_client: {parts[0]}")
    if not path.is_file() or not path.name.startswith("test_") or path.suffix != ".py":
        raise ValueError(f"test file does not exist: {parts[0]}")
    name = parts[-1]
    if not re.fullmatch(r"test_[A-Za-z0-9_]+", name):
        raise ValueError(
            f"only non-parameterized test functions are supported: {case_id}"
        )
    tree = ast.parse(path.read_text())
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    if len(matches) != 1:
        raise ValueError(f"-k {name} would not uniquely identify one test in {path}")
    if len(parts) == 3 and not any(
        isinstance(node, ast.ClassDef)
        and node.name == parts[1]
        and any(child is matches[0] for child in node.body)
        for node in ast.walk(tree)
    ):
        raise ValueError(f"test function is not in class {parts[1]}")
    if any(
        "parametrize" in ast.unparse(decorator)
        for decorator in matches[0].decorator_list
    ):
        raise ValueError(
            f"parameterized test requires an exact pytest node selector: {case_id}"
        )
    return parts[0], name


def kube_environment(deploy):
    command(["milvus-cell", "kubeconfig", "--sync"])
    env = os.environ.copy()
    env["KUBECONFIG"] = str(Path.home() / ".milvus-cell/kubeconfig")
    server = command(
        [
            "kubectl",
            "config",
            "view",
            "--minify",
            "-o",
            "jsonpath={.clusters[0].cluster.server}",
        ],
        env=env,
    ).stdout.strip()
    if server.rstrip("/") != deploy["cluster"].rstrip("/"):
        raise RuntimeError(
            "active kubeconfig does not target the Dev CLI deployment cluster"
        )
    return env


def kubectl(env, namespace, pod, *args, check=True, input_text=None):
    return command(
        [
            "kubectl",
            "-n",
            namespace,
            "exec",
            pod,
            "-c",
            "standalone",
            *(["-i"] if input_text is not None else []),
            "--",
            *args,
        ],
        env=env,
        check=check,
        input_text=input_text,
    )


def wait_marker(env, namespace, pod, marker, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (
            kubectl(
                env,
                namespace,
                pod,
                "test",
                "-f",
                f"{COVERAGE_ROOT}/{marker}",
                check=False,
            ).returncode
            == 0
        ):
            return
        time.sleep(1)
    raise TimeoutError(f"Milvus did not acknowledge {marker} within {timeout}s")


def safe_case_dir(root, case_id):
    slug = re.sub(r"[^a-z0-9]+", "-", case_id.lower()).strip("-")[-75:]
    return root / f"{slug}-{uuid.uuid4().hex[:8]}"


def copy_from_pod(env, namespace, pod, remote, local):
    command(
        [
            "kubectl",
            "-n",
            namespace,
            "cp",
            "--retries=3",
            "-c",
            "standalone",
            f"{namespace}/{pod}:{remote}",
            str(local),
        ],
        env=env,
    )


def copy_large_archive(env, namespace, pod, remote, local):
    """Copy a gcov archive in small chunks across the vCluster API proxy."""
    kubectl(
        env,
        namespace,
        pod,
        "split",
        "-b",
        "4m",
        "-d",
        "-a",
        "3",
        remote,
        remote + ".part.",
    )
    parts = kubectl(
        env, namespace, pod, "sh", "-c", f"ls {remote}.part.*"
    ).stdout.splitlines()
    if not parts or any(
        not re.fullmatch(re.escape(remote) + r"\.part\.\d{3}", part) for part in parts
    ):
        raise RuntimeError("gcov archive was not split into numbered parts")
    with local.open("wb") as assembled:
        for part in parts:
            chunk = local.parent / Path(part).name
            copy_from_pod(env, namespace, pod, part, chunk)
            with chunk.open("rb") as data:
                while block := data.read(1024 * 1024):
                    assembled.write(block)
            chunk.unlink()


def collect(env, namespace, pod, output_dir):
    kubectl(env, namespace, pod, "sh", "-c", 'kill -USR1 "$(pidof milvus)"')
    wait_marker(env, namespace, pod, "snapshot.done")
    kubectl(
        env,
        namespace,
        pod,
        "cp",
        "/milvus/lib/milvus-e2e-gcno.tar.gz",
        f"{COVERAGE_ROOT}/milvus-e2e-gcno.tar.gz",
    )
    script = (REPO / "scripts/prepare_e2e_cpp_gcov.sh").read_text()
    kubectl(
        env,
        namespace,
        pod,
        "bash",
        "-s",
        "--",
        COVERAGE_ROOT,
        "/milvus/lib/milvus-e2e-gcov",
        input_text=script,
    )
    kubectl(
        env,
        namespace,
        pod,
        "bash",
        "-c",
        f"cd {COVERAGE_ROOT} && find cpp-gcov -name '*.gcov.json.gz' -print0 | tar --null -czf cpp-json.tar.gz -T -",
    )
    output_dir.mkdir(parents=True)
    copy_from_pod(env, namespace, pod, f"{COVERAGE_ROOT}/go", output_dir / "go-raw")
    copy_large_archive(
        env,
        namespace,
        pod,
        f"{COVERAGE_ROOT}/cpp-json.tar.gz",
        output_dir / "cpp-json.tar.gz",
    )
    command(
        [
            "go",
            "tool",
            "covdata",
            "textfmt",
            f"-i={output_dir / 'go-raw'}",
            f"-o={output_dir / 'go.cov'}",
        ]
    )
    json_dir = output_dir / "cpp-json"
    json_dir.mkdir()
    with tarfile.open(output_dir / "cpp-json.tar.gz", "r:gz") as archive:
        for member in archive.getmembers():
            if (
                not member.name.startswith("cpp-gcov/")
                or ".." in Path(member.name).parts
                or not member.name.endswith(".gcov.json.gz")
            ):
                raise ValueError(f"unexpected gcov archive member: {member.name}")
        archive.extractall(json_dir, filter="data")
    return json_dir


def run_case(args, case_id, head):
    target, expression = validate_case(case_id)
    deploy_name = f"e2e-cov-{expression[:25].replace('_', '-')}-{uuid.uuid4().hex[:6]}"
    output_dir = safe_case_dir(args.output_root, case_id)
    print(f"Running {case_id} in new deployment {deploy_name}", flush=True)
    json_command(
        [
            "milvus-dev-cli",
            "deploy",
            "create",
            args.build_id,
            "--name",
            deploy_name,
            "--mode",
            "standalone",
            "--cu",
            str(args.cu),
        ]
    )
    deploy = json_command(["milvus-dev-cli", "deploy", "status", deploy_name])
    if deploy["status"] != "Healthy" or not deploy["updated"]:
        raise RuntimeError(f"deployment {deploy_name} is not ready")
    if head[:7] not in deploy["image"]:
        raise RuntimeError(
            f"image {deploy['image']} does not match source commit {head}"
        )
    standalone = [
        pod
        for pod in deploy["pods"]
        if pod["component"] == "standalone" and pod["phase"] == "Running"
    ]
    if len(standalone) != 1:
        raise RuntimeError(
            f"expected exactly one standalone pod, found {len(standalone)}"
        )
    pod = standalone[0]["name"]
    namespace = deploy["namespace"]
    env = kube_environment(deploy)
    kubectl(
        env,
        namespace,
        pod,
        "sh",
        "-c",
        f"rm -rf {COVERAGE_ROOT} && mkdir -p {COVERAGE_ROOT}",
    )
    kubectl(env, namespace, pod, "sh", "-c", 'kill -USR2 "$(pidof milvus)"')
    wait_marker(env, namespace, pod, "reset.done")

    started_at = datetime.now(timezone.utc).isoformat()
    test = command(
        [
            "milvus-dev-cli",
            "pysdk-e2e",
            "local",
            str(REPO),
            "-b",
            args.base,
            "--deploy",
            deploy_name,
            "-t",
            target,
            "-k",
            expression,
        ],
        check=False,
    )
    try:
        task = json.loads(test.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Dev CLI did not return a test task: {test.stderr or test.stdout}"
        ) from exc
    status = task.get("status")
    if status not in ("succeeded", "failed"):
        raise RuntimeError(f"test task ended unexpectedly: {status}")
    if task.get("targets") != [target] or task.get("test_case") != expression:
        raise RuntimeError(
            "Dev CLI task did not run the requested file and case expression"
        )
    after = json_command(["milvus-dev-cli", "deploy", "status", deploy_name])
    after_pods = {item["name"]: item for item in after["pods"]}
    if (
        pod not in after_pods
        or after_pods[pod]["restarts"] != standalone[0]["restarts"]
    ):
        raise RuntimeError(
            "Milvus pod changed during the case; coverage window is invalid"
        )

    json_dir = collect(env, namespace, pod, output_dir)
    command(
        [
            sys.executable,
            str(REPO / "scripts/report_e2e_server_coverage.py"),
            "--case-id",
            case_id,
            "--go-profile",
            str(output_dir / "go.cov"),
            "--cpp-json-dir",
            str(json_dir),
            "--output-dir",
            str(output_dir),
            "--server-commit",
            head,
            "--image",
            deploy["image"],
            "--test-task-id",
            task["id"],
            "--test-status",
            status,
        ]
    )
    (output_dir / "run.json").write_text(
        json.dumps(
            {
                "case_id": case_id,
                "server_commit": head,
                "image": deploy["image"],
                "deployment": deploy_name,
                "pod": pod,
                "test_task_id": task["id"],
                "test_status": status,
                "started_at": started_at,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "attribution": "isolated deployment and post-readiness counter window; background work may also be counted",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Coverage saved to {output_dir}; test status: {status}", flush=True)
    if args.cleanup and status == "succeeded":
        command(["milvus-dev-cli", "deploy", "delete", deploy_name])
    if status != "succeeded":
        raise RuntimeError(
            f"E2E task {task['id']} failed; deployment {deploy_name} was kept for diagnosis"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-id", required=True, help="Dev CLI coverage build ID")
    parser.add_argument(
        "--case",
        action="append",
        required=True,
        help="Full non-parameterized pytest node ID; repeat for more cases",
    )
    parser.add_argument(
        "--output-root", type=Path, default=REPO / "artifacts/e2e-server-coverage-runs"
    )
    parser.add_argument("--base", default="master", choices=("master", "2.6", "3.0"))
    parser.add_argument("--cu", type=int, default=2)
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete only successfully completed deployments created by this run",
    )
    args = parser.parse_args()
    if args.cu < 1:
        parser.error("--cu must be positive")
    head = command(["git", "rev-parse", "HEAD"]).stdout.strip()
    if command(["git", "status", "--porcelain"]).stdout.strip():
        parser.error(
            "commit coverage code before running so image and report share one revision"
        )
    for case_id in args.case:
        run_case(args, case_id, head)


if __name__ == "__main__":
    main()
