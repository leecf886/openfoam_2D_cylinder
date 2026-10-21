#!/usr/bin/env python3
"""Fresh-run orchestration; keep 0_org immutable and restore trial controls."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

from monitor import Recorder
from resources import resources

CASE = Path(__file__).resolve().parents[1]
RUN_FILES = ("log.potentialFoam", "log.decomposePar", "log.foamRun", "log.Allmesh",
             "log.checkMesh", "log.resources.json", "log.reconstructPar",
             "monitoring.csv", "monitoring.png")


def outputs():
    found = []
    for path in CASE.iterdir():
        if (path.name in RUN_FILES or path.name == "postProcessing"
                or re.fullmatch(r"processors?\d+(?:_\d+-\d+)?", path.name)
                or (path.is_dir() and re.fullmatch(r"\d+(?:\.\d*)?(?:[eE][-+]?\d+)?", path.name)
                    and float(path.name) != 0)):
            found.append(path)
    cell_proc = CASE / "constant/polyMesh/cellProc"
    if cell_proc.exists():
        found.append(cell_proc)
    return found


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def restore_zero():
    backup = CASE / "0_org"
    if not backup.is_dir() or backup.is_symlink():
        raise RuntimeError("需要真实的 0_org 目录；拒绝覆盖备份或使用符号链接")
    if not all((backup / field).is_file() for field in ("U", "p")):
        raise RuntimeError("0_org 中缺少 U 或 p")
    remove(CASE / "0")
    shutil.copytree(backup, CASE / "0")


def execute(command, log_name, recorder=None):
    print("运行：" + " ".join(command), flush=True)
    environment = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    with open(CASE / log_name, "w", buffering=1) as log:
        process = subprocess.Popen(command, cwd=CASE, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1, start_new_session=True)
        try:
            for line in process.stdout:
                log.write(line)
                print(line, end="", flush=True)
                if recorder:
                    recorder.feed(line)
            code = process.wait()
            if code:
                raise RuntimeError(f"命令失败（退出码 {code}）：查看 {log_name}")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            process.stdout.close()


def dictionary(path, entry, value=None):
    command = ["foamDictionary", str(path), "-entry", entry]
    command += ["-value"] if value is None else ["-set", str(value)]
    return subprocess.check_output(command, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description="恢复 0_org、势流初始化、MPI 计算及实时记录")
    parser.add_argument("-np", type=int, help="MPI 进程数，默认按可用物理核心自动选择")
    parser.add_argument("--mesh", action="store_true", help="重新导入网格")
    parser.add_argument("--test", action="store_true", help="仅试运行5步，临时固定 dt=0.0001 s")
    parser.add_argument("--clean", action="store_true", help="删除计算输出并从 0_org 恢复 0")
    args = parser.parse_args()
    os.chdir(CASE)
    # Both Allrun and Allclean take the same lock; never erase an active run.
    with open(CASE / ".case.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("此算例正在运行或清理，请先停止已有任务")
        if args.clean:
            # Validate the backup before deleting any output.
            if not all((CASE / "0_org" / field).is_file() for field in ("U", "p")):
                raise RuntimeError("0_org 不完整，拒绝清理")
            if (CASE / "0_org").is_symlink():
                raise RuntimeError("0_org 不得为符号链接")
            for path in outputs():
                print(f"清除 {path.name}")
                remove(path)
            restore_zero()
            print("已恢复 0；保留 0_org、网格、配置及网格导入日志。")
            return
        if os.environ.get("WM_PROJECT_VERSION") != "14":
            raise RuntimeError("请先 source /opt/openfoam14/etc/bashrc")
        for executable in ("potentialFoam", "foamRun", "foamDictionary", "decomposePar", "checkMesh", "mpirun"):
            if not shutil.which(executable):
                raise RuntimeError(f"找不到 {executable}")
        previous = outputs()
        if previous:
            raise RuntimeError("存在计算输出；需要从头计算时先执行 ./Allclean："
                               + ", ".join(path.name for path in previous))
        report = resources()
        ranks = args.np if args.np is not None else report["recommended_mpi_ranks"]
        if not 1 <= ranks <= report["cpu_capacity"]:
            raise RuntimeError(f"进程数必须在 1–{report['cpu_capacity']} 之间")
        report["selected_mpi_ranks"] = ranks
        (CASE / "log.resources.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
        restore_zero()
        if args.mesh or not (CASE / "constant/polyMesh/points").is_file():
            execute(["bash", "Allmesh"], "log.Allmesh")
        execute(["checkMesh"], "log.checkMesh")
        mesh_report = (CASE / "log.checkMesh").read_text()
        known_unused_points = (
            "Failed 1 mesh checks." in mesh_report
            and "number unused by faces: 2 number unused by cells: 2" in mesh_report
            and mesh_report.count("***") == 1
        )
        if "Mesh OK." not in mesh_report:
            if known_unused_points:
                print("原始网格的已知检查项：2 个未被面/单元使用的孤立点；"
                      "其余检查通过，允许继续。详见 log.checkMesh。", flush=True)
            else:
                raise RuntimeError("网格检查失败，停止计算，请检查 log.checkMesh")
        control = CASE / "system/controlDict"
        original = control.read_bytes()
        recorder = None
        success = False
        try:
            dictionary(control, "startFrom", "startTime")
            dictionary(control, "startTime", 0)
            if args.test:
                for entry, value in dict(endTime=0.0005, deltaT=0.0001,
                                         adjustTimeStep="no", writeControl="timeStep",
                                         writeInterval=1).items():
                    dictionary(control, entry, value)
            initial_dt = float(dictionary(control, "deltaT"))
            execute(["potentialFoam", "-initialiseUBCs", "-writep"], "log.potentialFoam")
            if ranks > 1:
                dictionary(CASE / "system/decomposeParDict", "numberOfSubdomains", ranks)
                execute(["decomposePar"], "log.decomposePar")
                binding = ["--map-by", "core", "--bind-to", "core"]
                if ranks > report["physical_cores"]:
                    binding = ["--use-hwthread-cpus", "--map-by", "hwthread", "--bind-to", "hwthread"]
                # Single-host run: shared-memory MPI avoids WSL virtual NIC pairing warnings.
                command = ["mpirun", "-np", str(ranks), *binding,
                           "--mca", "pml", "ob1", "--mca", "btl", "^tcp",
                           "foamRun", "-parallel"]
            else:
                command = ["foamRun"]
            recorder = Recorder(CASE / "monitoring.csv", initial_dt)
            execute(command, "log.foamRun", recorder)
            recorder.finish_step()
            if recorder.steps == 0 or (args.test and recorder.steps != 5):
                raise RuntimeError(f"时间步数异常：{recorder.steps}")
            success = True
            print(f"完成 {recorder.steps} 个时间步，监控数据：monitoring.csv")
        finally:
            if recorder:
                recorder.close(successful=success)
            control.write_bytes(original)
            if args.test:
                print("试运行结束，已恢复正式 controlDict；结果保留供检查，./Allclean 可清除。")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"错误：{error}")
    except KeyboardInterrupt:
        sys.exit("计算已中断；日志保留，controlDict 已恢复。")
