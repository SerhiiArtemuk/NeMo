from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import torch.nn as nn
from megatron.core.dist_checkpointing.mapping import ShardedStateDict

from nemo.lightning.megatron_parallel import MegatronParallel


class AdapterWrapper(nn.Module):
    def __init__(self, to_wrap: nn.Module, adapter: nn.Module):
        super(AdapterWrapper, self).__init__()
        self.to_wrap = to_wrap
        self.adapter = adapter

    def state_dict(self, destination=None, prefix='', keep_vars=False):
        if destination is None:
            destination = {}

        # Get state dict of the main module
        main_state_dict = self.to_wrap.state_dict(destination, prefix, keep_vars)

        # Store adapter state dict under the special "adapters" key in the destination dict
        adapter_state_dict = self.adapter.state_dict(None, prefix, keep_vars)
        destination[f'{prefix}adapters'] = adapter_state_dict
        return main_state_dict

    def sharded_state_dict(
        self,
        prefix: str = '',
        sharded_offsets: Tuple[Tuple[int, int, int]] = (),
        metadata: Optional[dict] = None,
    ) -> ShardedStateDict:
        sharded_state_dict = {}
        sharded_state_dict.update(self.to_wrap.sharded_state_dict(prefix, sharded_offsets, metadata))
        sharded_state_dict.update(self.adapter.sharded_state_dict(f"{prefix}adapter.", sharded_offsets, metadata))
        return sharded_state_dict

    def load_state_dict(self, state_dict, strict=True):
        # Check if the 'adapters' key is present in the state_dict
        if 'adapters' in state_dict:
            adapter_state_dict = state_dict.pop('adapters')
        else:
            adapter_state_dict = {}

        # Load the main module state dict
        self.to_wrap.load_state_dict(state_dict, strict)

        # Load the adapter module state dict if present
        if adapter_state_dict:
            self.adapter.load_state_dict(adapter_state_dict, strict)


@dataclass
class PEFTConfig:
    def wrap_fn(self, m, name=None, prefix=None):
        raise NotImplementedError


def peft_model_transform(wrap_fn: Callable):
    '''
    Apply model transform function for PEFT training.
    Returns a function which first freezes the base model, then recursively applies a
    model wrap function to the top level module.

    wrap_fn is an instance of PEFTConfig.wrap_fn
    '''

    def model_fn(m: MegatronParallel):
        m.freeze()  # freeze the base model
        m.walk(wrap_fn)  # add adapter weights (newly added weights are unfrozen)

    return model_fn