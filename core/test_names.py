"""
What a comparison is called, short, in the queue and as a set's pill: "VAE test", "Model + VAE test", "LoRA strength
test", "LLM test", "Workflow test". Not a list of all it compared: each image's own pill says what it ran.
"""
from core import file_tests, llm_tests, workflow_tests

FILE_WORDS = {"model_file": "Model", "text_encoder_file": "Text encoder", "vae_file": "VAE"}


def of_tests(tests):
    """
    A comparison of one workflow's settings by what it varies, from each image's settings (core/lora_tests.py):
    "LoRA strength test", "Model + VAE test". None for no comparison.
    """
    tests = [test for test in tests or () if isinstance(test, dict)]
    if not tests:
        return None
    parts = []
    names = {test.get("lora_name") for test in tests if test.get("lora_name")}
    strengths = {test.get("lora_strength") for test in tests if test.get("lora_name")}
    if len(names) > 1 and len(strengths) > 1:
        parts.append("LoRA style and strength")
    elif len(names) > 1:
        parts.append("LoRA style")
    elif len(strengths) > 1 or names:
        parts.append("LoRA strength")
    for key in file_tests.FILES:
        if len({test.get(key) for test in tests if test.get(key)}) > 1:
            parts.append(FILE_WORDS[key])
    return f"{' + '.join(parts)} test" if parts else None


def of_shots(shots):
    """A set's comparison, from its images: what of_tests says, or "Workflow test" or "LLM test". None for none."""
    shots = shots or []
    if workflow_tests.kind_of(shots):
        inside = of_tests([shot.get("lora_test") for shot in shots])
        return "Workflow + " + inside if inside else "Workflow test"
    if llm_tests.compared(shots):
        return "LLM test"
    return of_tests([shot.get("lora_test") for shot in shots])
