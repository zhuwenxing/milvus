"""
端到端编译测试：验证 Conan 2 + CMake 集成
"""

import modal
from pathlib import Path
import os
import subprocess

# 获取路径
dockerfile_path = (
    Path(__file__).parent.parent / "docker/builder/cpu/ubuntu22.04/Dockerfile.conan2"
)
milvus_root = Path(__file__).parent.parent.parent

# 创建持久化 Volume 用于 Conan 缓存
conan_cache_volume = modal.Volume.from_name("milvus-conan-cache", create_if_missing=True)

# 使用 Dockerfile 构建镜像并添加本地代码
# 包含整个 internal/core 目录（用于 CMake 配置和编译）
milvus_builder_image = (
    modal.Image.from_dockerfile(str(dockerfile_path))
    .add_local_dir(
        str(milvus_root / "internal/core"),
        remote_path="/milvus/internal/core",
    )
)

app = modal.App("milvus-cmake-build-test")


def run_cmd(cmd, cwd=None, check=True, env=None, capture=False):
    """运行命令并打印输出"""
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    if cwd:
        print(f"CWD: {cwd}")
    print(f"{'='*60}")

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    if capture:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            shell=isinstance(cmd, str),
            capture_output=True,
            text=True,
            env=merged_env,
        )
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
    else:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            shell=isinstance(cmd, str),
            text=True,
            env=merged_env,
        )

    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed with code {result.returncode}")
    return result


@app.function(
    image=milvus_builder_image,
    volumes={"/conan-volume": conan_cache_volume},
    timeout=14400,  # 4 小时
    cpu=16,  # 增加 CPU 核心数
    memory=65536,  # 64GB
)
def test_cmake_build():
    """测试完整的 CMake 编译流程"""
    import multiprocessing

    print("=" * 80)
    print("端到端编译测试：Conan 2 + CMake 集成")
    print("=" * 80)

    # 配置环境
    os.environ["CONAN_HOME"] = "/root/.conan2"
    CACHE_TARBALL = "/conan-volume/conan-cache.tar.zst"
    cpu_count = multiprocessing.cpu_count()
    os.environ["CMAKE_BUILD_PARALLEL_LEVEL"] = str(cpu_count)
    os.environ["MAKEFLAGS"] = f"-j{cpu_count}"

    # 检查 Conan 版本
    run_cmd(["conan", "--version"])

    # 创建工作目录
    build_dir = "/milvus/cmake_build"
    os.makedirs(build_dir, exist_ok=True)

    # 恢复 Conan 缓存
    if os.path.exists(CACHE_TARBALL):
        print("\n恢复 Conan 缓存...")
        tarball_size = os.path.getsize(CACHE_TARBALL) / (1024 * 1024 * 1024)
        print(f"Tarball size: {tarball_size:.2f} GB")
        run_cmd(
            ["tar", "-I", "zstd", "-xf", CACHE_TARBALL, "-C", "/root"],
            check=False,
        )
    else:
        print("\n未找到 Conan 缓存，将从头开始编译")

    # 配置 Conan profile
    print("\n配置 Conan profile...")
    if not os.path.exists("/root/.conan2/profiles/default"):
        run_cmd(["conan", "profile", "detect", "--force"])

    # 添加平台工具配置
    profile_path = "/root/.conan2/profiles/default"
    with open(profile_path, "a") as f:
        f.write("\n[platform_tool_requires]\n")
        f.write("bison/3.8.2\n")
        f.write("flex/2.6.4\n")

    print("\nConan profile:")
    run_cmd(["cat", profile_path])

    # 配置 global.conf
    global_conf_path = "/root/.conan2/global.conf"
    with open(global_conf_path, "w") as f:
        f.write("tools.build:skip_test=True\n")
        f.write(f"tools.build:jobs={cpu_count}\n")
        f.write("tools.cmake.cmaketoolchain:generator=Ninja\n")

    # 检查 lockfile（验证 JSON 格式是否完整）
    lockfile = "/milvus/internal/core/conan.lock"
    lockfile_opt = []
    if os.path.exists(lockfile):
        import json
        try:
            with open(lockfile) as f:
                json.load(f)
            print(f"\n使用 lockfile: {lockfile}")
            lockfile_opt = ["--lockfile", lockfile]
        except json.JSONDecodeError as e:
            print(f"\nLockfile 格式错误: {e}")
            print("将不使用 lockfile，重新解析依赖版本")
    else:
        print("\n未找到 lockfile，将解析依赖版本")

    # Step 1: Conan Install
    print("\n" + "=" * 80)
    print("Step 1: Conan Install")
    print("=" * 80)

    conan_output = f"{build_dir}/conan"
    os.makedirs(conan_output, exist_ok=True)

    install_cmd = [
        "conan",
        "install",
        "/milvus/internal/core",
        "--output-folder",
        conan_output,
        "--build=missing",
        "--build=!bison/*",
        "--build=!flex/*",
        "-s",
        "build_type=Release",
        "-s",
        "compiler.cppstd=17",
    ] + lockfile_opt

    run_cmd(install_cmd, cwd=build_dir)

    # 查找 Conan 生成的 generators 目录
    # cmake_layout(build_folder="conan") 会创建 conan/Release/generators/ 结构
    print("\n查找 Conan generators 目录...")
    generators_dir = None
    possible_paths = [
        f"{conan_output}/conan/Release/generators",
        f"{conan_output}/Release/generators",
        f"{conan_output}/generators",
        conan_output,
    ]
    for path in possible_paths:
        toolchain_candidate = f"{path}/conan_toolchain.cmake"
        if os.path.exists(toolchain_candidate):
            generators_dir = path
            print(f"找到 generators 目录: {generators_dir}")
            break

    if generators_dir is None:
        # 遍历查找
        print("\n遍历目录查找 conan_toolchain.cmake...")
        for root, dirs, files in os.walk(conan_output):
            if "conan_toolchain.cmake" in files:
                generators_dir = root
                print(f"找到 generators 目录: {generators_dir}")
                break

    if generators_dir is None:
        print(f"\n{conan_output} 目录内容:")
        run_cmd(["find", conan_output, "-type", "f", "-name", "*.cmake"], check=False)
        raise RuntimeError("conan_toolchain.cmake 未生成！")

    # 验证 Conan 生成的文件
    print("\n验证 Conan 生成的文件...")
    cmake_configs = []
    for f in sorted(os.listdir(generators_dir)):
        if f.endswith("-config.cmake") or f.endswith("Config.cmake"):
            cmake_configs.append(f)

    print(f"\n生成的 CMake 配置文件 ({len(cmake_configs)} 个):")
    for f in cmake_configs[:20]:  # 只显示前 20 个
        print(f"  {f}")
    if len(cmake_configs) > 20:
        print(f"  ... 还有 {len(cmake_configs) - 20} 个")

    toolchain = f"{generators_dir}/conan_toolchain.cmake"

    # Step 2: CMake Configure
    print("\n" + "=" * 80)
    print("Step 2: CMake Configure")
    print("=" * 80)

    cmake_cmd = [
        "cmake",
        "-B",
        build_dir,
        "-S",
        "/milvus/internal/core",
        f"-DCMAKE_TOOLCHAIN_FILE={toolchain}",
        f"-DCMAKE_PREFIX_PATH={generators_dir}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_INSTALL_PREFIX=/milvus/output",
        "-DBUILD_UNIT_TEST=OFF",
        "-DBUILD_DISK_ANN=OFF",
        "-GNinja",
    ]

    result = run_cmd(cmake_cmd, cwd=build_dir, check=False)

    if result.returncode != 0:
        print("\nCMake 配置失败！")

        # 打印 CMakeError.log
        error_log = f"{build_dir}/CMakeFiles/CMakeError.log"
        if os.path.exists(error_log):
            print("\n--- CMakeError.log ---")
            with open(error_log) as f:
                print(f.read()[-5000:])

        # 打印 CMakeOutput.log
        output_log = f"{build_dir}/CMakeFiles/CMakeOutput.log"
        if os.path.exists(output_log):
            print("\n--- CMakeOutput.log (last 2000 chars) ---")
            with open(output_log) as f:
                content = f.read()
                print(content[-2000:])

        return {
            "status": "failed",
            "stage": "cmake_configure",
            "cmake_configs": cmake_configs,
        }

    print("\nCMake 配置成功！")

    # Step 3: 尝试编译
    print("\n" + "=" * 80)
    print("Step 3: CMake Build (milvus_pb)")
    print("=" * 80)

    build_cmd = [
        "cmake",
        "--build",
        build_dir,
        "--target",
        "milvus_pb",
        f"-j{cpu_count}",
    ]

    result = run_cmd(build_cmd, cwd=build_dir, check=False)

    pb_success = result.returncode == 0
    if pb_success:
        print("\nmilvus_pb 编译成功！")
    else:
        print("\nmilvus_pb 编译失败")

    # 保存 Conan 缓存
    print("\n保存 Conan 缓存...")
    if os.path.exists(CACHE_TARBALL):
        os.remove(CACHE_TARBALL)
    run_cmd(
        ["tar", "-I", "zstd -T0", "-cf", CACHE_TARBALL, "-C", "/root", ".conan2"],
        check=False,
    )
    conan_cache_volume.commit()

    print("\n" + "=" * 80)
    print("编译测试完成！")
    print("=" * 80)

    return {
        "status": "success" if pb_success else "partial",
        "cmake_configured": True,
        "pb_compiled": pb_success,
        "cmake_configs": cmake_configs,
    }


@app.local_entrypoint()
def main():
    """本地入口"""
    print("启动端到端编译测试...")
    result = test_cmake_build.remote()
    print(f"\n最终结果: {result}")


if __name__ == "__main__":
    main()
