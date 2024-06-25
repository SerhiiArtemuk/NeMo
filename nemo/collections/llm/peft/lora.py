from dataclasses import dataclass, field
from typing import List, Literal

from megatron.core import parallel_state

from nemo.collections.llm.adapter.base import PEFT, AdapterWrapper
from nemo.collections.nlp.modules.common.megatron.adapters.parallel_adapters import ParallelLinearAdapter
from nemo.utils import logging


class AdapterParallelAdd(AdapterWrapper):
    """Example: LoRA Adapter"""

    def forward(self, x):
        linear_output, bias = self.to_wrap(x)
        if isinstance(linear_output, tuple) and len(linear_output) == 2:
            linear_output, layernorm_output = linear_output
            adapter_output = self.adapter(layernorm_output)
        else:
            adapter_output = self.adapter(x)
        return linear_output + adapter_output, bias


@dataclass
class LoRA(PEFT):
    """
    Implements the LoRA (Low-Rank Adaptation) module for parameter-efficient fine-tuning.

    LoRA uses a low-rank projection to adapt the weights of a pre-trained model to a new downstream task.
    This class facilitates the application of LoRA to specific modules within the model architecture.

    Args:
        target_modules (List[str], optional): A list of module names to apply LoRA to.
            Defaults to ['linear_qkv', 'linear_proj']. Possible choices include:
                - 'linear_qkv': Apply LoRA to the fused linear layer used for query, key, and value projections
                                in self-attention modules.
                - 'linear_proj': Apply LoRA to the linear layer used for projecting the output of self-attention modules.
                - 'linear_fc1': Apply LoRA to the first fully-connected layer in MLP.
                - 'linear_fc2': Apply LoRA to the second fully-connected layer in MLP.
        dim (int): Dimension of the low-rank projection space. Defaults to 32.
        alpha (int): Weighting factor for the low-rank projection. Defaults to 32.
        dropout (float): Dropout rate for the low-rank projection. Defaults to 0.0.
        dropout_position (Literal['pre', 'post'], optional): Position for applying dropout.
            Can be 'pre' (before the low-rank projection) or 'post' (after). Defaults to 'post'.

    Example:
    --------
        >>> from nemo.collections import llm
        >>> lora = llm.peft.LoRA(target_modules=['linear_qkv', 'linear_proj'], dim=32)
        >>> model = llm.Mistral7BModel(model_transform=lora)
        >>> # (set up trainer and data)
        >>> trainer.fit(model, data)

    )
    """

    target_modules: List[str] = field(default_factory=lambda: ['linear_qkv', 'linear_proj'])
    dim: int = 32
    alpha: int = 32
    dropout: float = 0.0
    dropout_position: Literal['pre', 'post'] = 'post'

    def transform(self, m, name=None, prefix=None):
        """
        Applies LoRA to a specific module within the model architecture.

        Args:
            m (nn.Module): The module to apply LoRA to.
            name (str, optional): Name of the module (if applicable). Defaults to None.
            prefix (str, optional): Prefix for the module name (if applicable). Defaults to None.

        Returns:
            nn.Module: The modified module with LoRA applied, or the original module if not a target.
        """
        tp_size = parallel_state.get_tensor_model_parallel_world_size()
        if name in self.target_modules:
            # m.in_features and m.out_features are divided by tp_size already,
            # but in_features and out_features passed to ParallelLinearAdapter are not.
            if name in ['linear_qkv', 'linear_fc1']:
                # Column Parallel Linear
                input_is_parallel = False
                in_features = m.in_features
                out_features = m.out_features * tp_size
            else:  # name in ['linear_proj', 'linear_fc2']
                # Row Parallel Linear
                input_is_parallel = True
                in_features = m.in_features * tp_size
                out_features = m.out_features

            logging.info("Adding lora to:", f"{prefix}.{name}", f"{m.in_features}x{m.out_features}")
            adapter = ParallelLinearAdapter(
                in_features,
                out_features,
                self.dim,
                activation='identity',
                norm_position=None,
                norm_type=None,
                column_init_method="normal",
                row_init_method="zero",
                gather_output=False,
                input_is_parallel=input_is_parallel,
                dropout=self.dropout,
                dropout_position=self.dropout_position,
                alpha=self.alpha,
            )
            return AdapterParallelAdd(m, adapter)
        return m
