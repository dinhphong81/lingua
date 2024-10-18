# Copyright (c) Meta Platforms, Inc. and affiliates.

from dataclasses import dataclass
from typing import Optional

import torch
from torch import nn

from lingua.transformer import RMSNorm, cross_entropy
from apps.fastRNN.minLSTM.core_lstm import BaseMinLSTMArgs, BaseMinLSTM


@dataclass
class LMMinLSTMArgs(BaseMinLSTMArgs):

    seed: int = 42

    vocab_size: int = -1
    weight_tying: bool = False

    loss_reduction: str = "mean"


class LMMinLSTM(BaseMinLSTM):
    def __init__(self, args: LMMinLSTMArgs) -> None:
        super().__init__(args)
        self.weight_tying = args.weight_tying
        self.loss_reduction = args.loss_reduction
        self.seed = args.seed

        assert args.vocab_size > 0

        self.tok_embeddings = torch.nn.Embedding(args.vocab_size, args.dim)

        self.norm = RMSNorm(args.dim, eps=args.norm_eps)

        self.output = nn.Linear(
            args.dim,
            args.vocab_size,
            bias=False,
        )

        if args.weight_tying:
            self.output.weight = self.embeddings.tok_embeddings.weight

        self.init_weights()

    def forward(
        self,
        token_values: torch.Tensor,
        target: Optional[torch.Tensor] = None,
        cu_seqlens: Optional[int] = None,
        impl: str = "parallel",
    ) -> torch.Tensor:

        h = self.tok_embeddings(token_values)

        h = super().forward(h, cu_seqlens=cu_seqlens, impl=impl)

        logits = self.output(self.norm(h))
        if target is not None:
            return cross_entropy(
                logits.flatten(0, 1),
                target.flatten(0, 1),
                reduction=self.loss_reduction,
            )
        else:
            return logits

    def reset_parameters(self, init_std=None):
        # Either use fixed base std or sqrt model dim
        super().reset_parameters()
        init_std = init_std or (self.dim ** (-0.5))
        self.norm.reset_parameters()
        nn.init.trunc_normal_(
            self.tok_embeddings.weight,
            mean=0.0,
            std=init_std,
            a=-3 * init_std,
            b=3 * init_std,
        )
        if not self.weight_tying:
            nn.init.trunc_normal_(
                self.output.weight,
                mean=0.0,
                std=init_std,
                a=-3 * init_std,
                b=3 * init_std,
            )

    def _get_no_recompute_ops(self):
        return get_no_recompute_ops()


def get_no_recompute_ops():
    return {
        torch.ops.aten.mm.default,
        torch.ops.aten._scaled_mm.default,
        torch.ops.c10d_functional.reduce_scatter_tensor.default,
        torch.ops.scan.scan_fwd.default,
    }