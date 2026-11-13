"""Static checkpoint inventory only; never equate file bytes with process RAM."""
from collections import Counter
import json
import math
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[2]


def main():
    lock=json.loads((ROOT/'model-lock.json').read_text())
    qwen=json.loads((ROOT/'qwen-lock.json').read_text())
    path=ROOT/'models/embeddinggemma-2'/lock['revision']/lock['weight_file']
    with path.open('rb') as source:
        length=struct.unpack('<Q',source.read(8))[0]
        if length>64*1024*1024:raise ValueError('Unexpected header size')
        header=json.loads(source.read(length))
    elements=Counter();payload=Counter()
    for name,item in header.items():
        if name=='__metadata__':continue
        elements[name.split('.')[0]]+=math.prod(item['shape'])
        payload[name.split('.')[0]]+=item['data_offsets'][1]-item['data_offsets'][0]
    result=dict(target_device_ram='8 GB, user stated; phone/SoC/OS unknown',
        embedding_checkpoint_file_bytes=path.stat().st_size,
        tensor_elements_by_component=dict(elements),tensor_payload_bytes_by_component=dict(payload),
        active_text_component='language_model; vision/audio explicitly disabled by current configuration',
        text_fp32_tensor_payload_estimate=elements['language_model']*4,
        qwen_quantized_file_bytes=qwen['size_bytes'],
        caveat='Static on-disk metadata, not measured process RSS/PSS, active memory, activation/KV allocation or Android feasibility. Quantized Qwen file bytes are not a runtime RAM estimate.')
    (ROOT/'results/patent-8gb-envelope.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
