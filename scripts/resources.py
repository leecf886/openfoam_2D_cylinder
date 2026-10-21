#!/usr/bin/env python3
"""Resources visible to this Linux process, including affinity/cgroup limits."""
import json
import os
from pathlib import Path


def resources():
    affinity = sorted(os.sched_getaffinity(0))
    cores = set()
    for cpu in affinity:
        topology = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        try:
            cores.add(((topology / "physical_package_id").read_text().strip(),
                       (topology / "core_id").read_text().strip()))
        except OSError:
            cores.add(("unknown", cpu))
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.split()[0]) * 1024
    allowed_cpus = len(affinity)
    available = memory["MemAvailable"]
    limits = []
    # Walk all ancestors: a parent cgroup can impose a tighter limit.
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        if line.startswith("0::"):
            root = Path("/sys/fs/cgroup")
            group = root / line[3:].lstrip("/")
            for directory in [group, *group.parents]:
                if directory != root and root not in directory.parents:
                    continue
                cpu_file = directory / "cpu.max"
                mem_file = directory / "memory.max"
                if cpu_file.is_file():
                    quota, period = cpu_file.read_text().split()
                    if quota != "max":
                        allowed_cpus = min(allowed_cpus, max(1, int(quota) // int(period)))
                        limits.append(f"{cpu_file}: {quota} {period}")
                if mem_file.is_file() and mem_file.read_text().strip() != "max":
                    maximum = int(mem_file.read_text())
                    used = int((directory / "memory.current").read_text())
                    available = min(available, max(0, maximum - used))
                    limits.append(f"{mem_file}: {maximum}")
    model = next((line.split(":", 1)[1].strip()
                  for line in Path("/proc/cpuinfo").read_text().splitlines()
                  if line.startswith("model name")), "unknown")
    return dict(cpu_model=model, logical_cpus=len(affinity),
                physical_cores=len(cores), affinity=affinity,
                cpu_capacity=allowed_cpus,
                recommended_mpi_ranks=min(len(cores), allowed_cpus),
                memory_total_gib=round(memory["MemTotal"] / 2**30, 3),
                memory_available_gib=round(available / 2**30, 3),
                swap_total_gib=round(memory["SwapTotal"] / 2**30, 3),
                cgroup_limits=limits)


if __name__ == "__main__":
    print(json.dumps(resources(), indent=2, ensure_ascii=False))
