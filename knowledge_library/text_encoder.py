"""Inference-only implementation of the pinned Transformer → mean → normalize recipe.

Avoids importing Sentence Transformers' training and multimodal processing stack.
The checkpoint, text inputs, dtype, attention, pooling and normalization stay pinned.
"""
import json
import numpy as np


class TextEncoder:
    def __init__(self,path,*,device,config_kwargs,model_kwargs):
        import torch
        from .import_index import enable
        enable()
        from transformers import AutoConfig,AutoModel,AutoTokenizer
        self.torch=torch;self.device=device
        modules=json.loads((path/'modules.json').read_text())
        if [m['type'].rsplit('.',1)[-1] for m in modules]!=['Transformer','Pooling','Normalize']:
            raise ValueError('Unsupported embedding pipeline; revalidate the encoder')
        pooling=json.loads((path/'1_Pooling/config.json').read_text())
        if pooling!=dict(embedding_dimension=768,pooling_mode='mean',include_prompt=True):
            raise ValueError('Unsupported embedding pooling; revalidate the encoder')
        self.prompts=json.loads((path/'config_sentence_transformers.json').read_text())['prompts']
        config=AutoConfig.from_pretrained(str(path),local_files_only=True,trust_remote_code=False,**config_kwargs)
        self.auto_model=AutoModel.from_pretrained(str(path),config=config,local_files_only=True,trust_remote_code=False,**model_kwargs).to(device)
        self.tokenizer=AutoTokenizer.from_pretrained(str(path),local_files_only=True,trust_remote_code=False)

    def __getitem__(self,index):
        if index!=0:raise IndexError(index)
        return self

    def eval(self):self.auto_model.eval();return self
    def parameters(self):return self.auto_model.parameters()
    def get_embedding_dimension(self):return self.auto_model.config.text_config.embedding_dim

    def encode(self,texts,*,convert_to_tensor=True,normalize_embeddings=True,batch_size=8,show_progress_bar=False,prompt_name=None,prompt=None):
        torch=self.torch
        prefix=self.prompts[prompt_name] if prompt_name else prompt or ''
        inputs=[prefix+text for text in texts]
        # Match SentenceTransformer.encode's length-sorted batches and restore order.
        order=np.argsort([-len(text) for text in inputs]).tolist()
        output=[None]*len(inputs)
        for start in range(0,len(order),batch_size):
            indices=order[start:start+batch_size]
            features=self.tokenizer([inputs[i] for i in indices],padding=True,truncation='longest_first',max_length=8192,return_tensors='pt')
            features={k:v.to(self.device) for k,v in features.items()}
            tokens=self.auto_model(**features).last_hidden_state
            mask=features['attention_mask'].unsqueeze(-1).expand_as(tokens).to(tokens.dtype)
            pooled=(tokens*mask).sum(dim=1)/mask.sum(dim=1).clamp(min=1e-9)
            pooled=torch.nn.functional.normalize(pooled,p=2,dim=1)
            if normalize_embeddings:pooled=torch.nn.functional.normalize(pooled,p=2,dim=1)
            for i,row in zip(indices,pooled):output[i]=row
        result=torch.stack(output)
        return result if convert_to_tensor else result.float().cpu().numpy()
