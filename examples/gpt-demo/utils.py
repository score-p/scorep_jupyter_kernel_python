import random
import numpy as np 
import torch
import torch.nn as nn
from torch.nn import functional as F

def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def top_k_logits(logits, k):
    v, ix = torch.topk(logits, k)
    out = logits.clone()
    out[out < v[:, [-1]]] = -float('Inf')
    return out

@torch.no_grad()
def sample(model, x, steps, temperature=1.0, sample=False, top_k=None):
    """
    take a conditioning sequence of indices in x (of shape (b,t)) and predict the next token in
    the sequence, feeding the predictions back into the model each time. Clearly the sampling
    has quadratic complexity unlike an RNN that is only linear, and has a finite context window
    of block_size, unlike an RNN that has an infinite context window.
    """
    block_size = model.get_block_size()
    model.eval()

    for k in range(steps):
        x_cond = x if x.size(1) <= block_size else x[:, -block_size:]
        logits, _ = model(x_cond)
        
        logits = logits[:, -1, :] / temperature
        if top_k is not None:
            logits = top_k_logits(logits, top_k)
        
        probs = F.softmax(logits, dim = -1)
        if sample:
            ix = torch.multinomial(probs, num_samples = 1)
        else:
            _, ix = torch.topk(probs, k=1, dim =-1)
        x = torch.cat((x, ix), dim = 1)
    
    return x
