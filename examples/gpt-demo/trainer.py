import math
import logging

from tqdm import tqdm
import numpy as np

import torch
from torch.utils.data.dataloader import DataLoader

logger = logging.getLogger(__name__)


class TrainerConfig:
    max_epochs = 40
    batch_size = 64
    learning_rate = 3e-4
    betas = (0.9, 0.95)
    grad_norm_clip = 1.0
    weight_decay = 0.1  # only applied on matmul weights
    # learning rate decay params: linear warmup followed by cosine decay to
    # 10% of original
    lr_decay = False
    warmup_tokens = 375e6
    final_tokens = 260e9

    ckpt_path = None
    num_workers = 0  # for DataLoader

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class Trainer:
    def __init__(self, model, train_dataset, test_dataset, config):
        self.model = model
        self.train_dataset = train_dataset
        self.test_dataset = test_dataset
        self.config = config

        self.device = "gpu"
        if torch.cuda.is_available():
            self.device = torch.cuda.current_device()
            self.model = torch.nn.DataParallel(self.model).to(self.device)

    def save_checkpoint(self):
        # DataParallel wrappers keep the raw model in the .model attribute
        raw_model = (
            self.model.module if hasattr(self.model, "module") else self.model
        )
        logger.info("saving %s", self.config.ckpt_path)
        torch.save(raw_model.state_dict(), self.config.ckpt_path)

    def train(self):
        model, config = self.model, self.config
        raw_model = model.module if hasattr(self.model, "module") else model
        optimizer = raw_model.configure_optimizers(config)

        def run_epoch(split):
            is_train = split == "train"
            model.train(is_train)
            data = self.train_dataset if is_train else self.test_dataset
            loader = DataLoader(
                data,
                shuffle=True,
                pin_memory=True,
                batch_size=config.batch_size,
                num_workers=config.num_workers,
            )

            losses = []

            pbar = (
                tqdm(enumerate(loader), total=len(loader))
                if is_train
                else enumerate(loader)
            )
            for it, (x, y) in pbar:

                x = x.to(self.device)
                y = y.to(self.device)

                with torch.set_grad_enabled(is_train):
                    logits, loss = model(x, y)
                    loss = (
                        loss.mean()
                    )  # collapse all the loss values if they are scattered
                    # across multiple GPUs.
                    losses.append(loss.item())

                if is_train:
                    model.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(
                        model.parameters(), config.grad_norm_clip
                    )
                    optimizer.step()

                    if config.lr_decay:
                        self.tokens += (
                            y >= 0
                        ).sum()  # Num of tokens processed at this step.
                        if self.tokens < config.warmup_tokens:
                            # linear warmup
                            lr_mult = float(self.tokens) / float(
                                max(1, config.warmup_tokens)
                            )
                        else:
                            # cosine decay
                            progress = float(
                                self.tokens - config.warmup_tokens
                            ) / float(
                                max(
                                    1,
                                    config.final_tokens - config.warmup_tokens,
                                )
                            )
                            lr_mult = max(
                                0.1, 0.5 * (1.0 + math.cos(math.pi * progress))
                            )
                        lr = config.learning_rate * lr_mult
                        for param_group in optimizer.param_groups:
                            param_group["lr"] = lr
                    else:
                        lr = config.learning_rate

                    pbar.set_description(
                        f"epoch {epoch+1} iter {it}: train loss "
                        f"{loss.item():.5f}. lr {lr}"
                    )
            if not is_train:
                test_loss = float(np.mean(losses))
                logger.info("test loss:%f", test_loss)
                return test_loss

        best_loss = float("inf")
        self.tokens = 0
        for epoch in range(config.max_epochs):
            run_epoch("train")
            if self.test_dataset is not None:
                test_loss = run_epoch("test")

            # supports early stopping based on the test loss, or just saves
            # always if no test set is provided.
            good_model = self.test_dataset is None or test_loss < best_loss
            if self.config.ckpt_path is not None and good_model:
                best_loss = test_loss
                self.save_checkpoint()
