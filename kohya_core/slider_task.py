"""Connect slider training to the same visible desktop task/history contract."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import threading
import time
import traceback
from .slider_project import parameters
from .project_config import WORKSPACE_PARAM_KEYS
from .slider_training import train
from .fizgig_engine import _write


def start(bridge, name, use_resume=False):
    if use_resume: return {"ok": False, "error": "滑块首版从头训练；已有检查点保留，续训入口尚未开放。"}
    preflight = bridge.prepare_training(name)
    if not preflight.get("ok"): return preflight
    config = copy.deepcopy(bridge.core.load_project(name))
    params = parameters(config, name)
    plan = preflight["plan"]
    roots = ("mode", "base_type", "base_model", "training_kind", "slider", "unet_only")
    record_config = {key: copy.deepcopy(config[key]) for key in roots if key in config}
    stored = config.get("params") if isinstance(config.get("params"), dict) else {}
    record_config["params"] = {key: value for key, value in stored.items() if key in WORKSPACE_PARAM_KEYS}
    task_id = bridge._begin_task("概念滑块 LoRA 训练", "training", mode=params["mode"], key=name)
    if not task_id: return {"ok": False, "error": "已有任务正在运行，请先等待或停止。"}
    with bridge._task_lock:
        state = bridge._task
        state.update(plan=plan, normalized_params=params, project_config=record_config,
                     message="正在准备滑块训练…", detail="模型加载 / 配对缓存 / 底模生成练习画面")
        started = state["started"]
    bridge.core.reset_stop()
    bridge.core.reset_effective()
    run_record = dict(id=task_id, project_name=name, mode=params["mode"], mode_label="概念滑块 LoRA",
        started=started, ended=None, status="running", message="准备滑块训练", config=record_config,
        normalized_params=params, resume_path="")
    def log(line): bridge._task_log(task_id, line)
    def persist():
        try: bridge._history_store().save(run_record)
        except Exception as exc: log("[WARN] 滑块训练记录保存失败：%s" % exc)
    persist()
    def worker():
        monitor = bridge.core.TrainMonitor()
        done = threading.Event()
        def update():
            while not done.wait(.8):
                snapshot = monitor.snapshot()
                bridge._record_training_metrics(task_id, snapshot)
                total, step = int(snapshot.get("total") or 0), int(snapshot.get("step") or 0)
                with bridge._task_lock:
                    if bridge._task and bridge._task.get("id") == task_id and bridge._task.get("status") == "running":
                        bridge._task.setdefault("effective_params", {}).update(bridge.core.get_effective())
                        phase = snapshot.get("phase")
                        if phase in ("sample", "finish"):
                            bridge._task.update(message=snapshot.get("phase_label") or
                                ("正在生成权重对照" if phase == "sample" else "正在保存模型"), progress=None,
                                detail="训练步数 %d / %d；正在采样验证或保存产物。" % (step, total))
                        elif step:
                            bridge._task.update(message="滑块训练中", progress=min(1.0, step / total) if total else None,
                                detail="Step %d / %d · loss %s" % (step, total, snapshot.get("loss", "—")))
        polling = threading.Thread(target=update, daemon=True, name="SliderProgress")
        polling.start()
        try:
            bridge._release_agent_model_for_task(task_id)
            result = train(bridge.core, config, name, log, monitor)
            with bridge._task_lock:
                if bridge._task and bridge._task.get("id") == task_id:
                    bridge._task.update(status="completed", message=result["message"], progress=1.0,
                                        detail="效果待确认；请查看新场景、不同种子和中间检查点的权重对照。")
        except bridge.core.StopRequested:
            with bridge._task_lock:
                if bridge._task and bridge._task.get("id") == task_id:
                    bridge._task.update(status="cancelled", message="滑块训练已停止；已生成的检查点与对照图保留。")
            log("[停止] 滑块训练已停止。")
        except Exception as exc:
            with bridge._task_lock:
                if bridge._task and bridge._task.get("id") == task_id:
                    bridge._task.update(status="failed", message="滑块训练失败：%s" % exc)
            log("[失败] %s" % exc)
            log(traceback.format_exc())
        finally:
            done.set(); polling.join(timeout=1)
            monitor.finish()
            bridge._record_training_metrics(task_id, monitor.snapshot())
            with bridge._task_lock:
                state.setdefault("effective_params", {}).update(bridge.core.get_effective())
                final = dict(state)
            # A force-stopped child cannot write its terminal result; keep disk status aligned with the task.
            if final["status"] in ("cancelled", "failed"):
                output = bridge.core.get_effective().get("slider_output")
                if output:
                    try:
                        result_path = Path(output) / "result.json"
                        if result_path.is_file():
                            result = json.loads(result_path.read_text(encoding="utf-8"))
                            result.update(status=final["status"], message=final.get("message", ""), completed=time.time())
                            _write(result_path, result)
                    except (OSError, ValueError) as exc:
                        log("[WARN] 滑块停止状态保存失败：%s" % exc)
            run_record.update(ended=time.time(), status=final["status"], message=final.get("message", ""),
                metrics=final.get("metrics"), loss_history=final.get("loss_history", []),
                logs=final.get("logs", [])[-300:], effective_params=final.get("effective_params", {}))
            persist()
    threading.Thread(target=worker, daemon=True, name="SliderTraining").start()
    bridge._log("[训练] 已打开「%s」的滑块训练任务。" % name)
    return {"ok": True, "task_id": task_id}
