"""CPU check of the generated launcher against Fizgig's real FamilyLoRA."""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from kohya_core.lora_continue import FIZGIG_LAUNCHER, guarded, inspect

SOURCE = Path.home() / "kohya_ss/fizgig_versions/v8.9.6/source"
try:
    import torch
    import safetensors
except ImportError:
    torch = None

SCRIPT = """
from types import SimpleNamespace
import os
import torch
from fizgig.families.lora import FamilyLoRA

class Driver:
    description = SimpleNamespace(display_name="test", trainable_dtype="fp32", lora=SimpleNamespace(kohya=False, file_prefix="diffusion_model.", down="lora_down", up="lora_up", alpha_key="{prefix}.alpha"))
    def lora_target_names(self, model): return ["proj"]
    def block_of(self, name): return 0

model = torch.nn.Module()
model.proj = torch.nn.Linear(2, 2, bias=False)
net = FamilyLoRA(model, Driver(), device="cpu")
net.add_trainable(2, 2)
if os.environ.get("MAKE_SOURCE"):
    with torch.no_grad():
        for p in net.parameters(): p.fill_(0.25)
    net.save(os.environ["SOURCE_FILE"], dtype=torch.float32)
else:
    for p in net.parameters(): assert torch.all(p == 0.25), "initial weight mismatch"
    opt = torch.optim.SGD(net.parameters(), lr=0.1)
    before = [p.detach().clone() for p in net.parameters()]
    model.proj(torch.ones(1,2)).sum().backward()
    opt.step()
    assert any(not torch.equal(a, b) for a, b in zip(before, net.parameters()))
    print("CPU_INITIAL_AND_STEP_OK")
"""

@unittest.skipUnless(torch is not None and SOURCE.is_dir(), "Fizgig and torch required")
class FizgigLauncherCPU(unittest.TestCase):
    def test_loads_real_trainable_weights_before_optimizer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "train.py"
            script.write_text(textwrap.dedent(SCRIPT), encoding="utf-8")
            launcher = root / "launch.py"
            launcher.write_text(guarded(FIZGIG_LAUNCHER), encoding="utf-8")
            source_weights = root / "source.safetensors"
            env = os.environ.copy()
            env["PYTHONPATH"] = str(SOURCE / "src")
            env["MAKE_SOURCE"] = "1"
            env["SOURCE_FILE"] = str(source_weights)
            subprocess.run([sys.executable, str(script)], env=env, check=True, capture_output=True, text=True)
            self.assertEqual(inspect(source_weights)["rank"], 2)
            env.pop("MAKE_SOURCE")
            run = subprocess.run([sys.executable, str(launcher), str(SOURCE), str(source_weights), str(script)], env=env, check=True, capture_output=True, text=True)
            self.assertIn("CPU_INITIAL_AND_STEP_OK", run.stdout)

if __name__ == "__main__": unittest.main()
