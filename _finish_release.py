# -*- coding: utf-8 -*-
import os, sys, time
ROOT = r"C:\Users\admin\Desktop\本地生图"
sys.path.insert(0, ROOT)
import release

def retry_upload(ver, secrets, attempts=5):
    for k in range(1, attempts + 1):
        try:
            release.upload_ms(ver, secrets)
            return True
        except Exception as e:
            print("[发布] Setup.exe 上传第 %d 次失败：%s" % (k, e), flush=True)
            if k < attempts:
                print("[发布] 10 秒后重试…", flush=True)
                time.sleep(10)
    return False

def main():
    secrets = release.load_secrets()
    ver = release.current_version()
    print("[发布] 发布 v%s（不重新打包，直接上传 + 推送）" % ver, flush=True)
    if not retry_upload(ver, secrets):
        print("[发布] 上传多次仍失败，中止（可换网络后再跑）", flush=True)
        sys.exit(1)
    release.git_push(secrets)
    release.github_release(ver, secrets)
    print("[发布] ================", flush=True)
    print("[发布] 完成！还差一步：把 Setup.exe 手动传到 GitHub Release v%s" % ver, flush=True)
    print("[发布]   %s" % os.path.join(release.ROOT, "build_exe/installer/Setup.exe"), flush=True)
    print("[发布] 魔搭国内镜像已更新，用户无需代理即可检查/下载更新。", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[发布] 失败:", e, flush=True)
        sys.exit(1)
