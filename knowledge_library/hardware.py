"""Startup device selection and local first-run system checks."""
import platform
from pathlib import Path
import shutil


def select_device(torch_module=None):
    if torch_module is None:
        import torch as torch_module
    try:
        if torch_module.cuda.is_available():
            # Availability alone can succeed with an unsupported GPU/driver.
            probe=torch_module.empty(1,device='cuda')
            probe.add_(1)
            torch_module.cuda.synchronize()
            return dict(device='cuda',gpu_name=torch_module.cuda.get_device_name(0),reason='CUDA execution check passed.')
    except (RuntimeError,AssertionError,OSError) as error:
        return dict(device='cpu',gpu_name=None,reason='CUDA execution check failed; using CPU.')
    return dict(device='cpu',gpu_name=None,reason='No usable CUDA device detected; using CPU.')


def system_report(library,selection):
    import psutil
    target=Path(library).resolve()
    while not target.exists() and target!=target.parent:target=target.parent
    ram=psutil.virtual_memory().total
    free=shutil.disk_usage(target).free
    warnings=[]
    if ram<8*1024**3:warnings.append('8 GB RAM or more is recommended. Large libraries may index slowly on this computer.')
    if free<5*1024**3:warnings.append('Less than 5 GB free for your library. Free some space before a large scan.')
    return dict(**selection,ram_bytes=ram,free_disk_bytes=free,architecture=platform.machine(),warnings=warnings)
