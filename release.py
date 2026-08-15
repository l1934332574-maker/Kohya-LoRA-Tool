import io, os, re, sys, json, subprocess, shutil, zipfile, tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))

HELP = '''一键发布脚本（打包 + 魔搭国内镜像 + 推送 GitHub/Gitee）

用法:
  python release.py                用当前 APP_VERSION 重新打包发布
  python release.py 0.9.1          先升到 0.9.1 再发布
  python release.py --github       打包后顺便上传 Setup.exe 到 GitHub Release（慢，可选）

流程:
  1) (可选) 升版本号到 Kohya一键工具.py / installer.iss
  2) PyInstaller 打包 + 复制配套文件
  3) Inno Setup 编译 Setup.exe
  4) 生成便携 zip
  5) 更新 update.json（version/setup_url；setup_url_cn 自动指魔搭）
  6) 上传 Setup.exe + update.json 到魔搭（国内镜像，覆盖同名文件）
  7) 提交并推送 GitHub main + Gitee main
  8) 提示：把 Setup.exe 传到 GitHub Release（自动更新兜底用）

令牌: release_secrets.json（已 gitignore）或环境变量 MS_TOKEN / GITEE_TOKEN
'''


def log(msg):
    print('[发布] ' + msg, flush=True)


def load_secrets():
    fp = os.path.join(ROOT, 'release_secrets.json')
    d = {}
    if os.path.isfile(fp):
        try:
            d = json.load(open(fp, encoding='utf-8'))
        except Exception as e:
            print('警告: release_secrets.json 读取失败:', e)
    d['ms_token'] = d.get('ms_token') or os.environ.get('MS_TOKEN') or ''
    d['gitee_token'] = d.get('gitee_token') or os.environ.get('GITEE_TOKEN') or ''
    d.setdefault('gitee_user', 'FGtiancai')
    d.setdefault('gitee_repo', 'FGtiancai/Kohya-LoRA-Tool')
    d.setdefault('ms_repo', 'FGtiancai/Kohya-LoRA-Tool')
    d.setdefault('github_repo', 'l1934332574-maker/Kohya-LoRA-Tool')
    if not d['ms_token']:
        print('错误: 缺少魔搭令牌（release_secrets.json 的 ms_token 或环境变量 MS_TOKEN）'); sys.exit(1)
    if not d['gitee_token']:
        print('错误: 缺少 Gitee 令牌（release_secrets.json 的 gitee_token 或环境变量 GITEE_TOKEN）'); sys.exit(1)
    return d


def current_version():
    src = open(os.path.join(ROOT, 'Kohya一键工具.py'), encoding='utf-8-sig').read()
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src)
    return m.group(1) if m else None


def bump_version(newver):
    def _rep(path, pat, repl):
        src = open(path, encoding='utf-8-sig' if path.endswith('.py') else 'utf-8').read()
        n = len(re.findall(pat, src))
        if n == 0:
            raise RuntimeError('%s 未找到版本号模式' % path)
        open(path, 'w', encoding='utf-8-sig' if path.endswith('.py') else 'utf-8').write(re.sub(pat, repl, src))
    _rep(os.path.join(ROOT, 'Kohya一键工具.py'), r'APP_VERSION\s*=\s*"[^"]*"', 'APP_VERSION = "%s"' % newver)
    _rep(os.path.join(ROOT, 'build_exe/installer/installer.iss'), r'#define MyAppVersion\s*"[^"]*"', '#define MyAppVersion "%s"' % newver)
    log('版本号已更新为 ' + newver)


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError('命令失败: ' + ' '.join(str(x) for x in cmd))
    return r


def build():
    log('PyInstaller 打包…')
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
         '--distpath', 'build_exe/dist', '--workpath', 'build_exe/work',
         'build_exe/Kohya一键工具.spec'], cwd=ROOT)
    pkg = os.path.join(ROOT, 'build_exe/dist/Kohya一键工具')
    for f in ['preprocess.py', 'video_caption.py', 'model_downloader.py', 'README_使用说明.md',
              'LICENSE', 'THIRD_PARTY_NOTICES.md', '01_一键安装_Setup.bat', '02_数据预处理_Preprocess.bat',
              '03_启动UI_StartUI.bat', '04_一键训练_TrainCLI.bat', '安装本地依赖.bat',
              '手动安装_ManualInstall.bat', '_common.bat']:
        shutil.copy2(os.path.join(ROOT, f), os.path.join(pkg, f))
    for d in ['installers', 'configs', 'wd14_tagger_model']:
        if not os.path.isdir(os.path.join(pkg, d)):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(pkg, d))
    os.makedirs(os.path.join(pkg, 'models/base'), exist_ok=True)
    open(os.path.join(pkg, 'kohya_dir.txt'), 'w').write('')
    log('配套文件已复制')

    log('Inno Setup 编译 Setup.exe…')
    iscc = None
    for c in (os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs/Inno Setup 6/ISCC.exe'),
              r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
              r'C:\Program Files\Inno Setup 6\ISCC.exe'):
        if os.path.isfile(c):
            iscc = c; break
    if not iscc:
        raise RuntimeError('未找到 Inno Setup ISCC.exe')
    run([iscc, os.path.join(ROOT, 'build_exe/installer/installer.iss')], cwd=ROOT)

    log('生成便携 zip…')
    ver = current_version()
    zip_path = os.path.join(ROOT, 'build_exe/dist/KohyaLoraTool_v%s_portable.zip' % ver)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(pkg):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, pkg))
    log('便携 zip: %s (%.1f MB)' % (os.path.basename(zip_path), os.path.getsize(zip_path) / 1048576))
    return ver


def update_json(ver, secrets):
    p = os.path.join(ROOT, 'update.json')
    d = json.load(open(p, encoding='utf-8'))
    d['version'] = 'v' + ver
    d['setup_url'] = 'https://github.com/%s/releases/download/v%s/Setup.exe' % (secrets['github_repo'], ver)
    d['setup_url_cn'] = 'https://modelscope.cn/models/%s/resolve/master/Setup.exe' % secrets['ms_repo']
    d['notes'] = 'v%s：应用内自动更新 + 多项修复（国内魔搭镜像下载）' % ver
    json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    log('update.json 已更新（version=%s, 魔搭=%s）' % (d['version'], d['setup_url_cn']))


def upload_ms(ver, secrets):
    from modelscope.hub.api import HubApi
    api = HubApi(token=secrets['ms_token'])
    repo = secrets['ms_repo']
    log('上传 Setup.exe 到魔搭（覆盖）…')
    api.upload_file(repo, os.path.join(ROOT, 'build_exe/installer/Setup.exe'), path_in_repo='Setup.exe')
    log('上传 update.json 到魔搭（覆盖）…')
    api.upload_file(repo, os.path.join(ROOT, 'update.json'), path_in_repo='update.json')
    log('魔搭完成: https://modelscope.cn/models/%s' % repo)


def git_push(secrets):
    log('提交并推送 GitHub…')
    run(['git', 'add', '-A'], cwd=ROOT)
    st = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if st:
        run(['git', 'commit', '-m', 'release: v%s（自动发布）' % current_version()], cwd=ROOT)
    else:
        log('无改动，跳过 commit')
    run(['git', 'push', 'origin', 'main'], cwd=ROOT)
    log('推送 Gitee…')
    gt = 'https://%s:%s@gitee.com/%s.git' % (secrets['gitee_user'], secrets['gitee_token'], secrets['gitee_repo'])
    run(['git', 'push', gt, 'main'], cwd=ROOT)
    log('Gitee 已同步')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    do_github = '--github' in sys.argv
    if '-h' in sys.argv or '--help' in sys.argv:
        print(HELP); return
    secrets = load_secrets()
    if args:
        newver = args[0]
        if not re.match(r'^\d+\.\d+\.\d+$', newver):
            print('版本号格式应为 x.y.z，例如 0.9.1'); sys.exit(1)
        bump_version(newver)
    ver = current_version()
    log('发布版本: v%s' % ver)
    build()
    update_json(ver, secrets)
    upload_ms(ver, secrets)
    git_push(secrets)
    log('=' * 50)
    log('发布完成！还差一步：')
    log('  把 Setup.exe 传到 GitHub Release v%s（自动更新兜底用）：' % ver)
    log('    %s' % os.path.join(ROOT, 'build_exe/installer/Setup.exe'))
    log('  魔搭国内镜像已自动更新，用户无需代理即可检查/下载更新。')
    if do_github:
        log('（--github 上传待实现/可手动执行）')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('[发布] 失败:', e)
        sys.exit(1)
