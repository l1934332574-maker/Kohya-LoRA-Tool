# -*- coding: utf-8 -*-
"""显卡检测（渐进式拆分，从 Kohya一键工具.py 迁出）。"""
import os
import re
import subprocess

__all__ = [
    "detect_nvidia_gpu", "nvidia_driver_version", "_dxgi_adapters", "detect_vram_gb",
    "_registry_vram_gb", "detect_gpu_vendor", "detect_gpu_name", "detect_gpu_info",
    "detect_torch_backend", "detect_ram_gb",
]

def detect_nvidia_gpu():
    """检测是否有 NVIDIA 显卡（调用 nvidia-smi）。返回 bool。"""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        return False

def nvidia_driver_version():
    """读取 NVIDIA 驱动主版本号（nvidia-smi 的 Driver Version，如 572.xx -> 572）。失败返回 None。"""
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=20)
        for line in (r.stdout or "").splitlines():
            if "Driver Version" in line:
                m = re.search(r"Driver Version:\s*([\d.]+)", line)
                if m:
                    try:
                        return int(m.group(1).split(".")[0])
                    except Exception:
                        return None
        return None
    except Exception:
        return None

def _dxgi_adapters():
    """用 DXGI 枚举显卡，返回 [(名称, 独显显存字节数)]。

    DXGI 的 DedicatedVideoMemory 是 Windows 给显卡的权威独显显存值，
    NVIDIA / AMD / Intel 都准确（RX 5600=6GB、7800XT=16GB、4070=8GB），
    比注册表 qwMemorySize（AMD 有时误报）和 WMI AdapterRAM（>4GB 溢出）可靠。
    """
    try:
        import ctypes

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

        class _ADAPTER_DESC(ctypes.Structure):
            _fields_ = [
                ("Description", ctypes.c_wchar * 128),
                ("VendorId", ctypes.c_uint), ("DeviceId", ctypes.c_uint),
                ("SubSysId", ctypes.c_uint), ("Revision", ctypes.c_uint),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", ctypes.c_longlong),
            ]

        IID_IDXGIFactory = _GUID(0x7b7166ec, 0x21c7, 0x44ae, (0xb2, 0x1a, 0xc9, 0xae, 0x32, 0x1a, 0xe3, 0x69))
        dxgi = ctypes.WinDLL("dxgi.dll")
        dxgi.CreateDXGIFactory.argtypes = [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        dxgi.CreateDXGIFactory.restype = ctypes.c_long
        factory = ctypes.c_void_p()
        hr = dxgi.CreateDXGIFactory(ctypes.byref(IID_IDXGIFactory), ctypes.byref(factory))
        if hr != 0 or not factory.value:
            return []
        obj = factory.value
        vtbl = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0],
                           ctypes.POINTER(ctypes.c_void_p))
        # IDXGIFactory: IUnknown(0-2)+IDXGIObject(3-6)+EnumAdapters(7)
        EnumAdapters = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint,
                                          ctypes.POINTER(ctypes.c_void_p))(vtbl[7])
        out = []
        i = 0
        while True:
            adapter = ctypes.c_void_p()
            hr2 = EnumAdapters(obj, i, ctypes.byref(adapter))
            if hr2 == 0x887A0027 or hr2 != 0 or not adapter.value:   # DXGI_ERROR_NOT_FOUND
                break
            av = ctypes.cast(ctypes.cast(adapter.value, ctypes.POINTER(ctypes.c_void_p))[0],
                             ctypes.POINTER(ctypes.c_void_p))
            # IDXGIAdapter: IUnknown(0-2)+IDXGIObject(3-6)+EnumOutputs(7)+GetDesc(8)
            GetDesc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_ADAPTER_DESC))(av[8])
            desc = _ADAPTER_DESC()
            if GetDesc(adapter.value, ctypes.byref(desc)) == 0:
                out.append((desc.Description or "", desc.DedicatedVideoMemory))
            i += 1
        return out
    except Exception:
        return []

def _is_igpu_name(name):
    """判断显卡名称是否为核显/基础显示适配器。

    AMD 平台的核显在 DXGI/WMI 里常排第一，且「设备管理器禁用核显」后 WMI 仍会列出
    （禁用不卸载设备），必须靠名称特征跳过，否则 detect_gpu_name() 会优先取到核显。
    覆盖：
    - Microsoft Basic Display / Basic Render（基础显示适配器）
    - Intel 核显：HD/UHD/Iris Graphics（如 "Intel(R) UHD Graphics"）
    - AMD 核显：Radeon(TM) Graphics / Radeon Graphics / Radeon Vega（APU）
      / Radeon 6xxM~8xxM（610M/680M/780M/880M/890M 等新命名）
    不误杀独显：Radeon RX / Radeon PRO / Intel Arc A 系列。
    """
    if not name:
        return False
    d = str(name).lower()
    if "microsoft basic" in d or "basic display" in d or "basic render" in d:
        return True
    if "intel" in d:
        # Intel Arc 独显（A310/A380/A580/A750/A770 等）不是核显
        if "arc" in d and re.search(r"\ba\d{3}\b", d):
            return False
        if "graphics" in d or "hd graphics" in d or "uhd" in d or "iris" in d:
            return True
        return False
    if "radeon" in d:
        if "graphics" in d:
            return True
        # APU 核显新命名：Radeon 610M/660M/680M/740M/760M/780M/880M/890M 等
        # （独显笔记本是 RX 6600M/6800M 等 4 位数 + M，靠 3 位数 + M 且前后非数字区分）
        if re.search(r"radeon[^0-9]*?(?<![0-9])\d{3}m(?![0-9])", d):
            return True
        return False
    return False


def detect_vram_gb():
    """检测显卡显存（GB）。优先 DXGI（各品牌权威）；失败回退 nvidia-smi（N 卡）/注册表。返回 None=未知。"""
    try:
        adapters = _dxgi_adapters()
        if adapters:
            best = None
            for _d, _mem in adapters:
                # 排除核显/基础显示适配器（AMD 核显常排第一，靠名称特征跳过）
                if _is_igpu_name(_d):
                    continue
                gb = float(_mem) / (1024.0 ** 3)
                if gb > 0:
                    best = gb if best is None else max(best, gb)
            if best:
                return best
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0:
            vals = []
            for line in r.stdout.strip().splitlines():
                line = line.strip()
                if line.replace(".", "").isdigit():
                    vals.append(float(line))
            if vals:
                return vals[0] / 1024.0
    except Exception:
        pass
    return _registry_vram_gb()

def detect_ram_gb():
    """检测系统物理内存总量（GB）。Windows 用 GlobalMemoryStatusEx（权威），失败回退 WMI。返回 None=未知。"""
    try:
        import ctypes

        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        ms = _MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            gb = float(ms.ullTotalPhys) / (1024.0 ** 3)
            if gb > 0:
                return gb
    except Exception:
        pass
    try:
        ps = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
              "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2)"]
        r = subprocess.run(ps, capture_output=True, text=True, timeout=30)
        val = (r.stdout or "").strip()
        if val:
            return float(val)
    except Exception:
        pass
    return None


def _registry_vram_gb():
    """从显卡注册表读取真实显存（HardwareInformation.qwMemorySize，QWORD，单位字节）。

    兼容 AMD / Intel / NVIDIA（WMI 的 AdapterRAM 会溢出到 4GB，不可靠）。
    遍历所有显示适配器：排除核显/基础显示适配器后取最大显存，
    避免双显卡机器（核显 + 独显）取到核显的小显存（如 7800XT 被误报成核显 8GB）。
    """
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        adapters = []  # (desc_lower, gb)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + "\\" + sub) as sk:
                        desc = ""
                        try:
                            desc, _ = winreg.QueryValueEx(sk, "DriverDesc")
                        except Exception:
                            pass
                        try:
                            val, _ = winreg.QueryValueEx(sk, "HardwareInformation.qwMemorySize")
                        except Exception:
                            continue
                        if not val:
                            continue
                        gb = float(val) / (1024.0 ** 3)
                        # 部分驱动把数值记为 MB/KB，做单位探测
                        if 0 < gb < 0.02:
                            gb = float(val) / (1024.0 ** 2)
                        if 0 < gb < 0.02:
                            gb = float(val) / 1024.0
                        if gb > 0:
                            adapters.append((desc.lower(), gb))
                except Exception:
                    continue
        if not adapters:
            return None

        discrete = [g for d, g in adapters if not _is_igpu_name(d)]
        pool = discrete if discrete else [g for _, g in adapters]
        return max(pool)
    except Exception:
        return None

def detect_gpu_vendor():
    """检测显卡厂商：'nvidia' | 'amd' | 'intel' | 'unknown'（任何异常都不抛出）。"""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and (r.stdout or "").strip():
            return "nvidia"
    except Exception:
        pass
    try:
        ps = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
              "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name + '|' + $_.AdapterCompatibility }"]
        r = subprocess.run(ps, capture_output=True, text=True, timeout=30)
        low = (r.stdout or "").lower()
        if any(k in low for k in ("amd", "ati", "radeon")):
            return "amd"
        if "intel" in low:
            return "intel"
    except Exception:
        pass
    return "unknown"

def detect_gpu_name():
    """返回独显名称（N 卡走 nvidia-smi；AMD/Intel 用 DXGI 取专用显存最大的适配器，
    天然跳过核显——AMD 核显常排第一，禁用后 WMI 仍会列出；DXGI 失败回退 WMI 遍历过滤核显）。
    失败返回 None。"""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            lines = [ln.strip() for ln in (r.stdout or "").strip().splitlines() if ln.strip()]
            if lines:
                return lines[0]
    except Exception:
        pass
    try:
        adapters = _dxgi_adapters()
        if adapters:
            best = None
            for _d, _mem in adapters:
                if _is_igpu_name(_d):
                    continue
                gb = float(_mem) / (1024.0 ** 3)
                if best is None or gb > best[1]:
                    best = (_d, gb)
            if best and best[1] > 0:
                return best[0]
    except Exception:
        pass
    try:
        ps = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
              "(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }) -join '|'"]
        r = subprocess.run(ps, capture_output=True, text=True, timeout=30)
        names = [n.strip() for n in (r.stdout or "").split("|") if n.strip()]
        for n in names:
            if not _is_igpu_name(n):
                return n
        if names:
            return names[0]
    except Exception:
        pass
    return None

def detect_gpu_info():
    """统一显卡信息：{'vendor','name','vram_gb'}。任何一步失败都不抛异常。"""
    return {"vendor": detect_gpu_vendor(), "name": detect_gpu_name(), "vram_gb": detect_vram_gb()}

def detect_torch_backend(vpy=None):
    """检测训练环境（kohya venv）里 torch 的后端：
    'rocm'=AMD ROCm 版 | 'zluda'=AMD 卡 + CUDA torch 且可用（ZLUDA 生效）
    | 'cuda'=N 卡 CUDA | 'cpu'=无 GPU 后端 | None=无法读取。"""
    if not vpy or not os.path.isfile(vpy):
        return None
    code = ("import torch;"
            "print('CUDA=%s' % (getattr(torch.version,'cuda',None) or ''));"
            "print('HIP=%s' % (getattr(torch.version,'hip',None) or ''));"
            "print('AVAIL=%s' % torch.cuda.is_available());"
            "print('NAME=%s' % (torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''))")
    try:
        r = subprocess.run([vpy, "-c", code], capture_output=True, text=True, timeout=120)
        info = {}
        for ln in (r.stdout or "").strip().splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                info[k] = v
        if info.get("HIP"):
            return "rocm"
        if info.get("AVAIL") == "True":
            if detect_gpu_vendor() == "amd":
                return "zluda"
            return "cuda"
        return "cpu"
    except Exception:
        return None
