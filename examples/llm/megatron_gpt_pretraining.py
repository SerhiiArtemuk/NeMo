import argparse

from pytorch_lightning.loggers import TensorBoardLogger

from nemo import lightning as nl
from nemo.collections import llm
from nemo.collections.llm.api import train
from nemo.collections.llm.gpt.data import PreTrainingDataModule
from nemo.collections.nlp.modules.common.tokenizer_utils import get_nmt_tokenizer
from nemo.lightning import NeMoLogger
from nemo.lightning.pytorch.callbacks import ModelCheckpoint


def get_args():
    parser = argparse.ArgumentParser(description='Train a small GPT model using NeMo 2.0')
    parser.add_argument('--devices', help="Number of devices to use for training")
    parser.add_argument('--max-steps', help="Number of steps to train for")
    parser.add_argument('--experiment-dir', help="directory to write results and checkpoints to")
    parser.add_argument('--data-path', help="Path to data file")
    parser.add_argument('--vocab-path', help="Path to vocab file")
    parser.add_argument('--merges-path', help="Path to merges file")
    parser.add_argument('--index-mapping-dir', help="directory to write index mappings to")

    return parser.parse_args()


if __name__ == '__main__':

    args = get_args()

    seq_length = 2048

    tokenizer = get_nmt_tokenizer(
        "megatron",
        "GPT2BPETokenizer",
        vocab_file=args.vocab_path,
        merges_file=args.merges_path,
    )
    data = PreTrainingDataModule(
        path=args.data_path,
        seq_length=2048,
        global_batch_size=32,
        seed=1234,
        tokenizer=tokenizer,
    )
    gpt_config = llm.GPTConfig(
        num_layers=12,
        hidden_size=768,
        ffn_hidden_size=3072,
        num_attention_heads=12,
        seq_length=seq_length,
        init_method_std=0.023,
        hidden_dropout=0.1,
        attention_dropout=0.1,
        layernorm_epsilon=1e-5,
        make_vocab_size_divisible_by=128,
    )
    model = llm.GPTModel(gpt_config, tokenizer=data.tokenizer)
    strategy = nl.MegatronStrategy()
    checkpoint_callback = ModelCheckpoint(
        every_n_train_steps=5000,
    )
    callbacks = [checkpoint_callback]

    loggers = []
    tensorboard_logger = TensorBoardLogger(
        save_dir='dummy',  ## NOTE: this gets overwritten by default
    )
    loggers.append(tensorboard_logger)

    trainer = nl.Trainer(
        devices=args.devices,
        max_steps=args.max_steps,
        accelerator="gpu",
        strategy=strategy,
        logger=loggers,
        callbacks=callbacks,
        log_every_n_steps=1,
        plugins=nl.MegatronMixedPrecision(precision="bf16-mixed", amp_O2=False),
    )

    nemo_logger = NeMoLogger(
        name=args.experiment_dir,
    )

    train(
        model=model,
        data=data,
        trainer=trainer,
        log=nemo_logger,
        tokenizer='data',
    )
