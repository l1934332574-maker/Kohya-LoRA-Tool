"""Opt-in GPU regression: run with the deployed engine Python and KOHYA_MOSS_GPU_TEST=1."""
import os
import unittest


@unittest.skipUnless(os.environ.get("KOHYA_MOSS_GPU_TEST") == "1", "explicit GPU check only")
class MossOffloadingGPUTests(unittest.TestCase):
    def test_mixed_lora_quantized_blocks_preserve_weights_and_dtype(self):
        import torch
        from torch import nn
        from fizgig.families.lora import LoRALinear
        from fizgig.modules.int8_train import apply_int8_training
        from fizgig.modules.offloading import Offloader, weighs_to_device, swap_weight_devices_no_cuda
        torch.manual_seed(123)
        dev=torch.device("cuda")
        for pinned in (False, True):
            quant=nn.Sequential(nn.Linear(128,128,bias=False)).eval().requires_grad_(False)
            apply_int8_training(quant, target_keys=("0",), compute_device=dev)
            quant[0]=LoRALinear(quant[0])
            plain=nn.Sequential(nn.Linear(128,128,bias=False)).eval().requires_grad_(False).to(dtype=torch.bfloat16)
            x=torch.randn(4,128,device=dev,dtype=torch.bfloat16)
            weighs_to_device(quant,dev)
            expected_q=quant(x).clone()
            weighs_to_device(plain,dev)
            expected_p=plain(x).clone()
            weighs_to_device(plain,torch.device("cpu"))
            off=Offloader("repro",2,1,dev,use_pinned_memory=pinned)
            try:
                for swap in (off.swap_weight_devices_cuda, swap_weight_devices_no_cuda):
                    for i in range(3):
                        e=swap(dev,quant,plain)
                        if e is not None:e.synchronize()
                        assert plain[0].weight.dtype==torch.bfloat16, f"block 22 dtype corrupted: {plain[0].weight.dtype}"
                        torch.testing.assert_close(plain(x),expected_p,rtol=0,atol=0)
                        e=swap(dev,plain,quant)
                        if e is not None:e.synchronize()
                        assert quant[0].base.weight.dtype==torch.int8
                        torch.testing.assert_close(quant(x),expected_q,rtol=0,atol=0)
            finally:
                off.thread_pool.shutdown()

if __name__ == "__main__": unittest.main()
