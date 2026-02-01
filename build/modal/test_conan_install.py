"""
测试 Conan 2 安装依赖（使用 conancenter 标准 recipes）

功能:
    1. 使用 Volume 缓存 Conan 包，后续 build 复用
    2. 生成 lockfile 锁定依赖版本

使用方法:
    modal run test_conan_install.py
"""

import modal
from pathlib import Path

# 获取路径
dockerfile_path = Path(__file__).parent.parent / "docker/builder/cpu/ubuntu22.04/Dockerfile.conan2"
milvus_root = Path(__file__).parent.parent.parent

# 创建持久化 Volume 用于 Conan 缓存
conan_cache_volume = modal.Volume.from_name("milvus-conan-cache", create_if_missing=True)

# 使用 Dockerfile 构建镜像并添加本地代码
milvus_builder_image = (
    modal.Image.from_dockerfile(str(dockerfile_path))
    .add_local_dir(
        str(milvus_root / "internal/core"),
        remote_path="/workspace/milvus/internal/core",
    )
)

app = modal.App("milvus-conan2-test")


@app.function(
    image=milvus_builder_image,
    timeout=14400,  # 4 小时，因为从头编译需要更长时间
    cpu=8,  # Modal 会自动 scale
    memory=16384,  # 16GB 足够
    # 挂载 Volume 用于存储 tarball 缓存（避免直接在 Volume 上运行 Conan）
    volumes={"/conan-volume": conan_cache_volume},
)
def test_conan_install():
    """测试 Conan 2 安装依赖，生成 lockfile"""
    import subprocess
    import os
    import shutil
    import multiprocessing
    import time

    # 使用本地磁盘（默认 Conan home）
    os.environ["CONAN_HOME"] = "/root/.conan2"
    CACHE_TARBALL = "/conan-volume/conan-cache.tar.zst"

    # 修复 autotools 包（如 bison）的临时文件问题
    # Modal 容器可能有特殊的文件系统限制
    os.makedirs("/tmp", exist_ok=True)
    os.chmod("/tmp", 0o1777)  # 确保 /tmp 有正确的权限
    os.environ["TMPDIR"] = "/tmp"
    os.environ["TMP"] = "/tmp"
    os.environ["TEMP"] = "/tmp"

    # 确保 HOME 目录存在并可写
    os.makedirs("/root", exist_ok=True)
    os.environ["HOME"] = "/root"

    # ===== 从 Volume 恢复缓存 =====
    # 使用 tarball 方式避免 Volume I/O 性能问题
    if os.path.exists(CACHE_TARBALL):
        print(f"=== Restoring cache from {CACHE_TARBALL} ===")
        tarball_size = os.path.getsize(CACHE_TARBALL) / (1024 * 1024 * 1024)
        print(f"Tarball size: {tarball_size:.2f} GB")
        restore_result = subprocess.run(
            ["tar", "-I", "zstd", "-xf", CACHE_TARBALL, "-C", "/root"],
            capture_output=True, text=True
        )
        if restore_result.returncode == 0:
            print("Cache restored successfully")
        else:
            print(f"Cache restore failed: {restore_result.stderr}")
    else:
        print("No cache tarball found, starting fresh build")

    # 设置并行编译参数
    cpu_count = multiprocessing.cpu_count()
    os.environ["CONAN_CPU_COUNT"] = str(cpu_count)
    os.environ["CMAKE_BUILD_PARALLEL_LEVEL"] = str(cpu_count)
    os.environ["MAKEFLAGS"] = f"-j{cpu_count}"
    print(f"Using {cpu_count} CPUs for parallel build")
    print(f"CONAN_HOME: {os.environ['CONAN_HOME']}")
    print(f"TMPDIR: {os.environ['TMPDIR']}")

    # 初始化 profile（使用 Docker 镜像中已检测的 profile）
    if not os.path.exists("/root/.conan2/profiles/default"):
        subprocess.run(["conan", "profile", "detect", "--force"])

    os.chdir("/workspace/milvus")

    # 显示 Conan remotes
    print("=== Conan remotes ===")
    subprocess.run(["conan", "remote", "list"])

    # 显示缓存状态
    print("\n=== Conan cache status ===")
    result = subprocess.run(["conan", "list", "*"], capture_output=True, text=True)
    cache_count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
    print(f"Cached packages: {cache_count}")

    # 显示 conanfile.py 内容
    print("\n=== conanfile.py ===")
    with open("internal/core/conanfile.py") as f:
        print(f.read())

    # 创建构建目录
    os.makedirs("cmake_build/conan", exist_ok=True)
    os.chdir("cmake_build")

    # Step 1: 生成 lockfile（解析依赖图但不编译）
    print("\n\n=== Step 1: Creating lockfile ===")
    lock_result = subprocess.run([
        "conan", "lock", "create", "../internal/core",
        "--lockfile-out", "conan.lock",
        "-s", "build_type=Release",
        "-s", "compiler.version=12",
        "-s", "compiler.libcxx=libstdc++11",
        "-s", "compiler.cppstd=17",
    ], capture_output=True, text=True)

    print("STDOUT:")
    print(lock_result.stdout[-10000:] if len(lock_result.stdout) > 10000 else lock_result.stdout)

    if lock_result.returncode != 0:
        print("\nSTDERR:")
        print(lock_result.stderr[-5000:] if len(lock_result.stderr) > 5000 else lock_result.stderr)
        return {
            "step": "lock",
            "returncode": lock_result.returncode,
            "success": False,
        }

    # 显示生成的 lockfile
    print("\n=== Generated lockfile (conan.lock) ===")
    if os.path.exists("conan.lock"):
        with open("conan.lock") as f:
            lockfile_content = f.read()
            # 只显示前 200 行
            lines = lockfile_content.split('\n')
            if len(lines) > 200:
                print('\n'.join(lines[:200]))
                print(f"\n... ({len(lines) - 200} more lines)")
            else:
                print(lockfile_content)

    # Step 2: 使用 lockfile 安装依赖
    print("\n\n=== Step 2: Installing with lockfile ===")
    cpu_count = os.cpu_count() or 8

    # 修复 autotools 包构建问题：设置额外的环境变量
    # 某些 autotools 包（如 bison）需要 touch 命令能正常工作
    subprocess.run(["touch", "/tmp/test_touch"], check=False)
    if os.path.exists("/tmp/test_touch"):
        os.remove("/tmp/test_touch")
        print("Touch command works in /tmp")
    else:
        print("WARNING: Touch command failed in /tmp")

    # 配置 Conan 全局设置
    global_conf_path = "/root/.conan2/global.conf"
    os.makedirs("/root/.conan2", exist_ok=True)
    with open(global_conf_path, "w") as f:
        f.write("tools.build:skip_test=True\n")
        f.write(f"tools.build:jobs={cpu_count}\n")
        f.write("tools.cmake.cmaketoolchain:generator=Ninja\n")
        # 配置系统包管理器，让 bison/flex 使用系统版本
        f.write("tools.system.package_manager:mode=check\n")
        f.write("tools.system.package_manager:sudo=True\n")
    print(f"Written global.conf to {global_conf_path}")

    # 配置 profile，让 bison 和 flex 使用系统版本
    profile_path = "/root/.conan2/profiles/default"
    with open(profile_path, "a") as f:
        f.write("\n[platform_tool_requires]\n")
        f.write("bison/3.8.2\n")
        f.write("flex/2.6.4\n")
    print("Configured profile to use system bison/flex")

    # 第一次尝试：只使用预编译包（不从源码构建）
    # 如果失败，记录哪些包需要构建
    print("\n=== Trying with prebuilt packages only ===")
    test_cmd = [
        "conan", "install", "../internal/core",
        "--lockfile", "conan.lock",
        "--output-folder", "conan",
        "--build=never",  # 只使用预编译包
        "-s", "build_type=Release",
        "-s", "compiler.version=12",
        "-s", "compiler.libcxx=libstdc++11",
        "-s", "compiler.cppstd=17",
    ]
    test_result = subprocess.run(test_cmd, capture_output=True, text=True)
    if test_result.returncode != 0:
        print("Some packages need to be built from source:")
        print(test_result.stderr[-3000:] if len(test_result.stderr) > 3000 else test_result.stderr)
        print("\nProceeding with --build=missing...")

    # 使用 Popen 实时输出，便于跟踪构建进度
    # 使用 --build=missing --build=!bison/* --build=!flex/* 排除 bison/flex 源码构建
    # 让 Conan 使用系统安装的版本
    install_cmd = [
        "conan", "install", "../internal/core",
        "--lockfile", "conan.lock",
        "--output-folder", "conan",
        "--build=missing",
        "--build=!bison/*",
        "--build=!flex/*",
        "-s", "build_type=Release",
        "-s", "compiler.version=12",
        "-s", "compiler.libcxx=libstdc++11",
        "-s", "compiler.cppstd=17",
    ]
    print(f"Running: {' '.join(install_cmd)}")

    install_process = subprocess.Popen(
        install_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    install_output = []
    for line in install_process.stdout:
        print(line, end='', flush=True)
        install_output.append(line)

    install_result_code = install_process.wait()
    install_stdout = ''.join(install_output)

    # 检查生成的文件
    print("\n=== Generated files in conan/ ===")
    if os.path.exists("conan"):
        for f in sorted(os.listdir("conan")):
            print(f"  {f}")

    # 保存 lockfile 到输出
    lockfile_path = "/workspace/milvus/cmake_build/conan.lock"
    lockfile_content = ""
    if os.path.exists("conan.lock"):
        with open("conan.lock") as f:
            lockfile_content = f.read()

    # ===== 保存缓存到 Volume =====
    # 只有构建成功时才保存缓存
    cache_saved = False
    if install_result_code == 0:
        print("\n=== Saving cache to Volume ===")
        # 先删除旧的 tarball
        if os.path.exists(CACHE_TARBALL):
            os.remove(CACHE_TARBALL)

        # 使用 zstd 压缩（比 gzip 快且压缩率更高）
        save_result = subprocess.run(
            ["tar", "-I", "zstd -T0", "-cf", CACHE_TARBALL, "-C", "/root", ".conan2"],
            capture_output=True, text=True
        )
        if save_result.returncode == 0:
            tarball_size = os.path.getsize(CACHE_TARBALL) / (1024 * 1024 * 1024)
            print(f"Cache saved successfully: {tarball_size:.2f} GB")
            cache_saved = True
            # 提交 Volume 变更
            conan_cache_volume.commit()
        else:
            print(f"Cache save failed: {save_result.stderr}")

    return {
        "step": "complete",
        "lock_returncode": lock_result.returncode,
        "install_returncode": install_result_code,
        "success": install_result_code == 0,
        "cache_saved": cache_saved,
        "lockfile": lockfile_content[:5000] if lockfile_content else None,
    }


@app.local_entrypoint()
def main():
    """主入口：测试 Conan install"""
    print("Testing Conan 2 install with lockfile and cache...")
    result = test_conan_install.remote()

    print(f"\n=== Final Result ===")
    print(f"Step: {result['step']}")
    if 'lock_returncode' in result:
        print(f"Lock return code: {result['lock_returncode']}")
    if 'install_returncode' in result:
        print(f"Install return code: {result['install_returncode']}")
    print(f"Success: {result['success']}")

    # 保存 lockfile 到本地
    if result.get('lockfile'):
        lockfile_path = Path(__file__).parent / "conan.lock"
        with open(lockfile_path, 'w') as f:
            f.write(result['lockfile'])
        print(f"\nLockfile saved to: {lockfile_path}")
