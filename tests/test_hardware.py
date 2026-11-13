from types import SimpleNamespace
from knowledge_library.hardware import select_device,system_report


def fake_torch(available=True,broken=False):
    calls=[]
    def empty(*args,**kwargs):
        calls.append(kwargs.get('device'))
        if broken:raise RuntimeError('CUDA kernel is unavailable')
        return SimpleNamespace(add_=lambda n:None)
    cuda=SimpleNamespace(is_available=lambda:available,synchronize=lambda:None,get_device_name=lambda n:'Test GPU')
    return SimpleNamespace(cuda=cuda,empty=empty),calls


def test_usable_cuda_is_selected_and_actually_probed():
    torch,calls=fake_torch()
    result=select_device(torch)
    assert result['device']=='cuda' and result['gpu_name']=='Test GPU' and calls==['cuda']


def test_missing_cuda_uses_cpu_without_gpu_allocation():
    torch,calls=fake_torch(False)
    result=select_device(torch)
    assert result['device']=='cpu' and not calls and result['reason']


def test_broken_driver_or_unsupported_kernel_falls_back_to_cpu():
    torch,calls=fake_torch(broken=True)
    assert select_device(torch)['device']=='cpu'
    assert calls==['cuda']


def test_hardware_report_checks_data_disk_and_reports_selected_device(tmp_path):
    report=system_report(tmp_path/'new-library',dict(device='cpu',gpu_name=None,reason='No CUDA device'))
    assert report['device']=='cpu' and report['ram_bytes']>0 and report['free_disk_bytes']>0
    assert isinstance(report['warnings'],list)
