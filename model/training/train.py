"""
Fine-tune Gemma 4 E2B with QLoRA using Unsloth.

Usage:
    conda run -n finedgar python model/training/train.py
    conda run -n finedgar python model/training/train.py --config model/configs/qlora_e4b.yaml
    conda run -n finedgar python model/training/train.py --data data/training/finedgar_train.jsonl

Requires:
    - NVIDIA GPU with >= 12GB VRAM
    - Unsloth installed
    - Training data at data/training/finedgar_train.jsonl
"""

import argparse
from pathlib import Path

import torch
import yaml
from datasets import load_dataset
from transformers import DataCollatorWithPadding

# CRITICAL: Import unsloth BEFORE trl/transformers for optimizations
from unsloth import FastVisionModel


def load_config(config_path: str = "model/configs/qlora_e4b.yaml") -> dict:
    """Read YAML configuration file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def setup_model(config: dict):
    """
    Load the base model with 4-bit quantization and attach LoRA adapters.

    GOTCHA: Loss values of 13-15 can be normal for Gemma multimodal checkpoints. Do not stop early.
    GOTCHA: Loss 100+ or 300+ means gradient_accumulation_steps is misconfigured.
    GOTCHA: Must use use_cache=True during inference to avoid corrupted outputs.
    GOTCHA: OOM fallback: first reduce max_seq_length to 1024, then reduce r to 16.
    """
    model, tokenizer = FastVisionModel.from_pretrained(
        config["model"]["name"],
        load_in_4bit=config["model"]["load_in_4bit"],
        max_seq_length=config["model"]["max_seq_length"],
        dtype=config["model"]["dtype"],
    )

    model = FastVisionModel.get_peft_model(
        model,
        r=config["lora"]["r"],
        lora_alpha=config["lora"]["lora_alpha"],
        lora_dropout=config["lora"]["lora_dropout"],
        bias=config["lora"]["bias"],
        use_gradient_checkpointing=config["lora"]["use_gradient_checkpointing"],
        finetune_vision_layers=config["lora"]["finetune_vision_layers"],
    )

    return model, tokenizer


def load_training_data(data_path: str, tokenizer, max_length: int = 2048):
    """Load JSONL, apply chat template, and tokenize for training.

    Labels are masked over the prompt so the model is trained to predict
    assistant tokens only, not user instructions.
    """
    ds = load_dataset("json", data_files=data_path, split="train")

    # Gemma 4 E4B uses a processor (multimodal), not a plain tokenizer.
    # Get the underlying text tokenizer for direct tokenization.
    text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)

    def tokenize_example(example):
        messages = example["messages"]
        text = text_tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
        prompt_text = text_tokenizer.apply_chat_template(
            messages[:-1],
            tokenize=False,
            add_generation_prompt=True,
        )
        tokenized_full = text_tokenizer(
            text,
            truncation=True,
            max_length=max_length,
            padding=False,
        )
        prompt_ids = text_tokenizer(
            prompt_text,
            truncation=True,
            max_length=max_length,
            padding=False,
        )["input_ids"]

        labels = tokenized_full["input_ids"].copy()
        prompt_len = min(len(prompt_ids), len(labels))
        labels[:prompt_len] = [-100] * prompt_len
        tokenized_full["labels"] = labels
        return tokenized_full

    ds = ds.map(tokenize_example, remove_columns=ds.column_names)
    return ds


class CausalLMCollator:
    """Pad variable-length causal LM batches and mask label padding."""

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.base_collator = DataCollatorWithPadding(
            tokenizer=tokenizer,
            padding=True,
            return_tensors="pt",
        )

    def __call__(self, features):
        labels = [feature["labels"] for feature in features]
        inputs = [
            {key: value for key, value in feature.items() if key != "labels"}
            for feature in features
        ]

        batch = self.base_collator(inputs)
        max_len = batch["input_ids"].shape[1]
        padded_labels = []
        for label in labels:
            pad_len = max_len - len(label)
            padded_labels.append(label + ([-100] * pad_len))
        batch["labels"] = torch.tensor(padded_labels, dtype=torch.long)
        return batch


def train(config: dict, data_path: str, eval_data_path: str | None = None):
    """
    Run the full training loop.

    GOTCHA: Loss values of 13-15 can be normal for Gemma multimodal checkpoints. Do not stop early.
    GOTCHA: Loss 100+ or 300+ means gradient_accumulation_steps is misconfigured.
    GOTCHA: Must use use_cache=True during inference to avoid corrupted outputs.
    GOTCHA: OOM fallback: first reduce max_seq_length to 1024, then reduce r to 16.
    """
    model, tokenizer = setup_model(config)
    max_seq_len = config["model"]["max_seq_length"]
    dataset = load_training_data(data_path, tokenizer, max_length=max_seq_len)
    text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    eval_dataset = None
    if eval_data_path:
        eval_path = Path(eval_data_path)
        if eval_path.exists():
            eval_dataset = load_training_data(str(eval_path), tokenizer, max_length=max_seq_len)
        else:
            print(f"Eval dataset not found at {eval_path}; continuing without eval.")

    tc = config["training"]
    # PyYAML safe_load parses scientific notation (e.g. 2e-4) as strings
    for key in ("learning_rate", "weight_decay"):
        if isinstance(tc.get(key), str):
            tc[key] = float(tc[key])

    eval_strategy = tc.get("evaluation_strategy", "epoch") if eval_dataset is not None else "no"
    save_strategy = tc.get("save_strategy", "steps")
    if eval_dataset is not None and eval_strategy != "no" and save_strategy != eval_strategy:
        save_strategy = eval_strategy

    from transformers import TrainingArguments
    training_args = TrainingArguments(
        output_dir=config["output"]["dir"],
        per_device_train_batch_size=tc["per_device_train_batch_size"],
        per_device_eval_batch_size=tc.get("per_device_eval_batch_size", 2),
        gradient_accumulation_steps=tc["gradient_accumulation_steps"],
        learning_rate=tc["learning_rate"],
        num_train_epochs=tc["num_train_epochs"],
        warmup_steps=tc["warmup_steps"],
        optim=tc["optim"],
        weight_decay=tc["weight_decay"],
        lr_scheduler_type=tc["lr_scheduler_type"],
        max_steps=tc["max_steps"],
        logging_steps=tc["logging_steps"],
        save_steps=tc["save_steps"],
        seed=tc["seed"],
        eval_strategy=eval_strategy,
        save_strategy=save_strategy,
        load_best_model_at_end=eval_dataset is not None,
        metric_for_best_model="eval_loss" if eval_dataset is not None else None,
        greater_is_better=False if eval_dataset is not None else None,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        remove_unused_columns=False,
        report_to="wandb" if config["output"].get("wandb_project") else "none",
    )

    from transformers import Trainer
    trainer = Trainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        eval_dataset=eval_dataset,
        data_collator=CausalLMCollator(text_tokenizer),
        args=training_args,
    )

    print(f"Training on {len(dataset)} examples from train split.")
    if eval_dataset is not None:
        print(f"Evaluating on {len(eval_dataset)} examples from internal_secqa_dev.")
    print(
        f"Estimated steps: "
        f"{len(dataset) // tc['gradient_accumulation_steps'] * tc['num_train_epochs']}"
    )
    trainer.train()

    # Save final LoRA adapters
    output_dir = config["output"]["dir"]
    lora_path = f"{output_dir}/lora-final"
    Path(lora_path).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(lora_path)
    tokenizer.save_pretrained(lora_path)
    print(f"Saved LoRA adapters to {lora_path}")

    return model, tokenizer


def main():
    parser = argparse.ArgumentParser(description="Fine-tune Gemma 4 E2B with QLoRA")
    parser.add_argument(
        "--config",
        type=str,
        default="model/configs/qlora_e4b.yaml",
        help="Path to YAML config file",
    )
    parser.add_argument(
        "--data",
        type=str,
        default="data/training/finedgar_train.jsonl",
        help="Path to training data JSONL",
    )
    parser.add_argument(
        "--eval-data",
        type=str,
        default="data/training/internal_secqa_dev.jsonl",
        help="Path to held-out internal SEC QA dev split",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    train(config, args.data, eval_data_path=args.eval_data)


if __name__ == "__main__":
    main()
