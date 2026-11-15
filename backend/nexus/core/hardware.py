"""Hardware real del equipo donde corre NEXUS (Doc 04 §12: métricas reales, nunca inventadas; D19:
NEXUS se adapta al equipo destino en vez de asumir el de desarrollo).

Portado de Primitivo Worker `hardware.py` (psutil + nvidia-smi). Sin nvidia-smi no hay forma
portable de leer VRAM (AMD/Intel): se trata como "sin GPU dedicada" y el router usa solo RAM.
"""
import shutil
import subprocess

import psutil


def get_hardware_info() -> dict:
    vm = psutil.virtual_memory()
    gpu, vram_total, vram_free = _nvidia_gpu()
    return {
        "ram_total_gb": round(vm.total / 1024 ** 3, 2),
        "ram_free_gb": round(vm.available / 1024 ** 3, 2),
        "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "cpu_percent": psutil.cpu_percent(interval=None),
        "gpu": gpu,
        "vram_total_gb": vram_total,
        "vram_free_gb": vram_free,
    }


def _nvidia_gpu() -> tuple[str | None, float, float]:
    """(nombre, VRAM total GB, VRAM libre GB) de la primera GPU NVIDIA, o (None, 0, 0)."""
    if not shutil.which("nvidia-smi"):
        return None, 0.0, 0.0
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
        name, total, free = (p.strip() for p in out[0].split(","))
        return name, round(float(total) / 1024, 2), round(float(free) / 1024, 2)
    except Exception:  # nvidia-smi presente pero sin driver/GPU usable
        return None, 0.0, 0.0
