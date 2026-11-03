from pathlib import Path


def resource_limits(root=Path("/sys/fs/cgroup")):
    try:
        quota, period = (root / "cpu.max").read_text().split()
        memory = (root / "memory.max").read_text().strip()
        swap = (root / "memory.swap.max").read_text().strip()
        cpu_limit = int(quota) / int(period) if quota != "max" else None
        memory_limit = int(memory) if memory != "max" else None
        swap_limit = int(swap) if swap != "max" else None
    except (OSError, ValueError, ZeroDivisionError):
        return {"verified": False, "mechanism": "unavailable"}
    return {
        "verified": cpu_limit == 2 and memory_limit == 8 * 1024**3 and swap_limit == 0,
        "mechanism": "linux_cgroup_v2",
        "cpu_max": f"{quota} {period}",
        "cpu_limit": cpu_limit,
        "memory_limit_bytes": memory_limit,
        "swap_limit_bytes": swap_limit,
        "cpu_set": (root / "cpuset.cpus.effective").read_text().strip()
        if (root / "cpuset.cpus.effective").exists()
        else None,
    }
