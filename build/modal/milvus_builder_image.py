"""
Milvus Conan 2 Builder 镜像定义 (使用 Modal)

使用方法:
    # 首次运行会构建镜像
    modal run milvus_builder_image.py

    # 进入容器 shell 测试
    modal shell milvus_builder_image.py
"""

import modal
from pathlib import Path

# 获取 Dockerfile 路径
dockerfile_path = Path(__file__).parent.parent / "docker/builder/cpu/ubuntu22.04/Dockerfile.conan2"

# 使用 Dockerfile 构建镜像
milvus_builder_image = modal.Image.from_dockerfile(str(dockerfile_path))

app = modal.App("milvus-conan2-builder")


@app.function(image=milvus_builder_image, timeout=3600)
def test_environment():
    """测试构建环境"""
    import subprocess

    results = {}

    # 测试 Conan 版本
    result = subprocess.run(["conan", "--version"], capture_output=True, text=True)
    results["conan"] = result.stdout.strip()

    # 测试 CMake 版本
    result = subprocess.run(["cmake", "--version"], capture_output=True, text=True)
    results["cmake"] = result.stdout.split('\n')[0]

    # 测试 GCC 版本
    result = subprocess.run(["gcc", "--version"], capture_output=True, text=True)
    results["gcc"] = result.stdout.split('\n')[0]

    # 测试 Go 版本
    result = subprocess.run(["/usr/local/go/bin/go", "version"], capture_output=True, text=True)
    results["go"] = result.stdout.strip()

    # 测试 Rust 版本
    result = subprocess.run(["/root/.cargo/bin/rustc", "--version"], capture_output=True, text=True)
    results["rust"] = result.stdout.strip()

    # 测试 Conan profile
    result = subprocess.run(["conan", "profile", "show"], capture_output=True, text=True)
    results["conan_profile"] = result.stdout

    return results


@app.local_entrypoint()
def main():
    """主入口：测试构建环境"""
    print("Testing Milvus Conan 2 builder environment...")
    results = test_environment.remote()

    print("\n=== Environment Test Results ===")
    for key, value in results.items():
        print(f"\n{key}:")
        print(value)
