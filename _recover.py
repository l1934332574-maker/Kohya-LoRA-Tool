# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r'C:\Users\admin\Desktop\本地生图')
import release
secrets = release.load_secrets()
ver = release.current_version()
print('[恢复] 版本:', ver)
release.upload_ms(ver, secrets)
release.git_push(secrets)
release.github_release(ver, secrets)
print('[恢复] 完成')
