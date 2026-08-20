# -*- coding: utf-8 -*-
import io
path = r"release.py"
with io.open(path, "r", encoding="utf-8", newline="") as f:
    lines = f.readlines()
eol = "\r\n" if any(l.endswith("\r\n") for l in lines) else "\n"

def find(pred, start=0):
    for i in range(start, len(lines)):
        if pred(lines[i]):
            return i
    return None

notes_new = ('    d[\'notes\'] = (\'v%s：修复 Anima 训练两类崩溃（TensorBoard 日志中文路径崩溃、Qwen3 权重缺失/文件名不规范被误判）；'
             'Qwen3 残缺目录自动备份重下自愈；训练前检测 CPU 版 torch 并预警；监控 3 分钟无进展自动提示，不再假卡住。\') % ver')
idx = find(lambda l: "d['notes'] = " in l or 'd["notes"] = ' in l)
assert idx is not None
lines[idx] = notes_new + eol

# 替换 github_release 的 body
body_old_start = find(lambda l: 'body = (' in l)
assert body_old_start is not None
# 找到 body 字符串结束（以 "安装包 Setup.exe 由维护者手动上传。" 结尾的行）
idx_end = find(lambda l: '安装包 Setup.exe 由维护者手动上传。")' in l, start=body_old_start)
assert idx_end is not None

body_lines = [
 '    body = ("v0.9.20 更新内容：\\n"',
 '            "- 修复：Anima 训练 TensorBoard 日志目录为中文路径时崩溃（FailedPreconditionError: logs is not a directory），自动重定向到英文路径\\n"',
 '            "- 修复：Qwen3-0.6B 只有 config.json 无权重 / 权重文件名不规范被误判为已就绪，训练加载崩溃；现已校验标准权重并自动重新下载\\n"',
 '            "- 自愈：Qwen3 残缺目录自动备份重下，用户无需手动删文件夹\\n"',
 '            "- 预警：训练启动前检测 torch 后端，CPU 版直接提示，不再 CPU 慢训假卡住\\n"',
 '            "- 监控：训练超过 3 分钟无输出自动提示可能卡住或已退出\\n\\n"',
 '            "安装包 Setup.exe 由维护者手动上传。")',
]
lines = lines[:body_old_start] + [l + eol for l in body_lines] + lines[idx_end+1:]

with io.open(path, "w", encoding="utf-8", newline="") as f:
    f.writelines(lines)
print("OK: release.py notes/body 已更新")
