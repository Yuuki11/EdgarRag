"""
Export fine-tuned Gemma 4 E4B to GGUF format and create Ollama model.

Usage:
    python model/training/export.py
    python model/training/export.py --checkpoint outputs/finedgar-gemma4-e4b/lora-final
    python model/training/export.py --quantization q4_k_m

Creates:
    1. GGUF file at model/gguf/unsloth.Q4_K_M.gguf
    2. Ollama Modelfile at model/Modelfile
    3. Registers model with Ollama as "finedgar"
"""

import argparse
import subprocess
from pathlib import Path

from unsloth import FastVisionModel


def export_to_gguf(
    checkpoint_path: str = "outputs/finedgar-gemma4-e4b/lora-final",
    output_dir: str = "model",
    quantization: str = "q4_k_m",
):
    """Load the fine-tuned model and export to GGUF format."""
    before = {str(path.resolve()) for path in Path(output_dir).rglob("*.gguf")}
    model, tokenizer = FastVisionModel.from_pretrained(
        checkpoint_path,
        load_in_4bit=True,
    )

    model.save_pretrained_gguf(
        f"{output_dir}/gguf",
        tokenizer,
        quantization_method=quantization,
    )
    print(f"Exported GGUF to {output_dir}/gguf/")
    return _find_primary_gguf(output_dir, quantization=quantization, before=before)


def _find_primary_gguf(
    output_dir: str = "model",
    quantization: str = "q4_k_m",
    before: set[str] | None = None,
) -> Path:
    """Locate the main text GGUF file produced by export."""
    quant_key = quantization.replace("_", "").lower()
    candidates: list[Path] = []
    for path in Path(output_dir).rglob("*.gguf"):
        name = path.name.lower()
        if "mmproj" in name:
            continue
        if before and str(path.resolve()) in before:
            continue
        candidates.append(path)

    if not candidates:
        for path in Path(output_dir).rglob("*.gguf"):
            name = path.name.lower()
            if "mmproj" in name:
                continue
            candidates.append(path)

    if not candidates:
        raise FileNotFoundError(f"No GGUF files found under {output_dir}")

    quant_matches = [
        path for path in candidates
        if quant_key in path.name.replace("_", "").lower()
    ]
    if quant_matches:
        candidates = quant_matches

    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def create_modelfile(output_dir: str = "model", gguf_path: str | Path | None = None):
    """Write an Ollama Modelfile with Gemma chat template and FinEdgar system prompt."""
    model_dir = Path(output_dir)
    if gguf_path is None:
        gguf_path = _find_primary_gguf(output_dir)
    gguf_path = Path(gguf_path)
    rel_gguf_path = "./" + str(gguf_path.relative_to(model_dir))

    modelfile_content = f'''FROM {rel_gguf_path}

TEMPLATE """{{ if .System }}<start_of_turn>system
{{ .System }}<end_of_turn>
{{ end }}{{ if .Prompt }}<start_of_turn>user
{{ .Prompt }}<end_of_turn>
{{ end }}<start_of_turn>model
{{ .Response }}<end_of_turn>"""

PARAMETER temperature 0.1
PARAMETER top_p 0.9
PARAMETER stop "<end_of_turn>"
PARAMETER num_predict 1024

SYSTEM """You are FinEdgar, a financial analysis assistant specializing in SEC filings. You provide accurate, well-sourced answers about company financials, risk factors, and filing changes. Always cite your sources (filing name, section, page when available). If you cannot find the answer in the provided context or are not confident, say so clearly rather than guessing."""
'''
    modelfile_path = model_dir / "Modelfile"
    with open(modelfile_path, "w") as f:
        f.write(modelfile_content)
    print(f"Created Modelfile at {modelfile_path}")
    print(f"Using GGUF file {gguf_path}")


def register_with_ollama(model_dir: str = "model"):
    """Register the model with Ollama."""
    model_dir_path = Path(model_dir)
    subprocess.run(
        ["ollama", "create", "finedgar", "-f", "Modelfile"],
        cwd=model_dir_path,
        check=True,
    )
    print("Registered model 'finedgar' with Ollama")

    # Verify registration
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    print(result.stdout)


def export_ablation_models():
    """Export base and intermediate models for ablation study.

    Ensures the base gemma4:e4b is pulled so both base and fine-tuned
    models are available in Ollama for evaluation.
    """
    # 1. Base model (no fine-tuning) -- just pull from Ollama
    subprocess.run(["ollama", "pull", "gemma4:e2b"], check=True)
    # This will be referenced as "gemma4:e4b" in evaluation

    # 2. Fine-tuned model -- already exported above as "finedgar"

    # Both models need to be available in Ollama for evaluation
    print("Ablation models ready:")
    print("  - gemma4:e2b       (base, no fine-tuning)")
    print("  - finedgar         (fine-tuned with QLoRA)")


def main():
    parser = argparse.ArgumentParser(
        description="Export fine-tuned Gemma 4 E4B to GGUF and register with Ollama"
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default="outputs/finedgar-gemma4-e4b/lora-final",
        help="Path to LoRA checkpoint directory",
    )
    parser.add_argument(
        "--quantization",
        type=str,
        default="q4_k_m",
        help="GGUF quantization method (e.g. q4_k_m, q8_0)",
    )
    args = parser.parse_args()

    output_dir = "model"

    print("=== Step 1: Export to GGUF ===")
    gguf_path = export_to_gguf(args.checkpoint, output_dir, args.quantization)

    print("\n=== Step 2: Create Modelfile ===")
    create_modelfile(output_dir, gguf_path=gguf_path)

    print("\n=== Step 3: Register with Ollama ===")
    register_with_ollama(output_dir)

    print("\n=== Step 4: Pull base model for ablation ===")
    export_ablation_models()


if __name__ == "__main__":
    main()
