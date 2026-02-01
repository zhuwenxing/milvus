from conan import ConanFile
from conan.tools.cmake import CMakeToolchain, CMakeDeps, cmake_layout


class MilvusConan(ConanFile):
    settings = "os", "compiler", "build_type", "arch"

    def requirements(self):
        # ========================================
        # 只声明 Milvus 直接使用的核心库
        # 传递依赖（protobuf, abseil, glog, fmt 等）由 Conan 自动解析
        # ========================================

        # 版本冲突 override（仅在自动解析失败时添加）
        self.requires("zstd/1.5.7", override=True)  # arrow vs folly
        self.requires("lz4/1.10.0", override=True)  # librdkafka vs folly

        # 存储和数据格式
        self.requires("rocksdb/6.29.5")
        self.requires("arrow/17.0.0")

        # 云存储
        self.requires("google-cloud-cpp/2.28.0")

        # 工具库
        self.requires("folly/2024.08.12.00")
        self.requires("boost/1.85.0")
        self.requires("onetbb/2021.9.0")

        # 消息队列
        self.requires("librdkafka/1.9.1")

        # 监控
        self.requires("prometheus-cpp/1.1.0")

        # 数据结构和算法
        self.requires("roaring/3.0.0")
        self.requires("marisa/0.2.6")
        self.requires("geos/3.12.0")

        # 序列化和解析
        self.requires("yaml-cpp/0.7.0")
        self.requires("rapidjson/cci.20230929")
        self.requires("nlohmann_json/3.11.3")

        # 工具
        self.requires("icu/74.2")
        self.requires("simde/0.8.2")
        self.requires("xxhash/0.8.3")
        self.requires("unordered_dense/4.4.0")

        # 测试
        self.requires("gtest/1.13.0")
        self.requires("benchmark/1.7.0")

    def configure(self):
        # Arrow 选项
        self.options["arrow"].filesystem_layer = True
        self.options["arrow"].parquet = True
        self.options["arrow"].compute = True
        self.options["arrow"].with_re2 = True
        self.options["arrow"].with_zstd = True
        self.options["arrow"].with_boost = True
        self.options["arrow"].with_thrift = True
        self.options["arrow"].with_jemalloc = True
        self.options["arrow"].with_openssl = True
        self.options["arrow"].shared = False
        self.options["arrow"].encryption = True

        # 共享库选项
        self.options["rocksdb"].shared = True
        self.options["rocksdb"].with_zstd = True
        self.options["folly"].shared = True
        self.options["librdkafka"].shared = True
        self.options["librdkafka"].zstd = True
        self.options["librdkafka"].ssl = True
        self.options["librdkafka"].sasl = True

        # 其他选项
        self.options["gtest"].build_gmock = True
        self.options["boost"].without_locale = False
        self.options["boost"].without_test = True
        self.options["prometheus-cpp"].with_pull = False
        self.options["onetbb"].tbbmalloc = False
        self.options["onetbb"].tbbproxy = False
        self.options["hwloc"].shared = True  # onetbb 需要
        self.options["icu"].shared = False
        self.options["icu"].data_packaging = "library"

        # 平台特定配置
        if self.settings.os == "Macos":
            self.options["arrow"].with_jemalloc = False

    def layout(self):
        cmake_layout(self, build_folder="conan")

    def generate(self):
        tc = CMakeToolchain(self)
        tc.generate()
        deps = CMakeDeps(self)
        deps.generate()
