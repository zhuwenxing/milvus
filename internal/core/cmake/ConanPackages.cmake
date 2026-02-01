# ConanPackages.cmake
# Conan 2 兼容层：使用 find_package 查找 Conan 安装的包，并设置兼容变量

# =========================================
# 使用 find_package 查找所有 Conan 包
# =========================================

# 核心依赖
find_package(RocksDB REQUIRED)
find_package(Arrow REQUIRED)
# Parquet 是 Arrow 的组件，不需要单独 find_package
# Arrow 在启用 parquet 选项后会包含 Parquet 组件
find_package(Boost REQUIRED)
find_package(folly REQUIRED)
find_package(TBB REQUIRED)

# 消息队列
find_package(RdKafka REQUIRED)

# 监控
find_package(prometheus-cpp REQUIRED)

# 数据结构
find_package(roaring REQUIRED)
find_package(marisa REQUIRED)
find_package(geos REQUIRED)

# 序列化
find_package(yaml-cpp REQUIRED)
find_package(RapidJSON REQUIRED)

# 工具库
find_package(ICU REQUIRED)
find_package(simde REQUIRED)
find_package(xxHash REQUIRED)
find_package(unordered_dense REQUIRED)

# 云存储（可选）
find_package(google-cloud-cpp CONFIG)

# 测试
find_package(GTest REQUIRED)
find_package(benchmark REQUIRED)

# Protobuf (由传递依赖自动引入)
find_package(Protobuf REQUIRED)

# glog (由传递依赖自动引入)
find_package(glog REQUIRED)

# fmt (由传递依赖自动引入)
find_package(fmt REQUIRED)

# gflags (由传递依赖自动引入)
find_package(gflags REQUIRED)

# OpenSSL (由传递依赖自动引入)
find_package(OpenSSL REQUIRED)

# nlohmann_json (由传递依赖自动引入)
find_package(nlohmann_json REQUIRED)

# =========================================
# 设置 Conan 1 兼容变量
# =========================================

# 收集所有 include 目录
set(CONAN_INCLUDE_DIRS "")

# RocksDB
if(TARGET RocksDB::rocksdb)
    get_target_property(_ROCKSDB_INCLUDE RocksDB::rocksdb INTERFACE_INCLUDE_DIRECTORIES)
    if(_ROCKSDB_INCLUDE)
        list(APPEND CONAN_INCLUDE_DIRS ${_ROCKSDB_INCLUDE})
        set(CONAN_INCLUDE_DIRS_ROCKSDB ${_ROCKSDB_INCLUDE})
    endif()
endif()

# RdKafka
if(TARGET RdKafka::rdkafka)
    get_target_property(_RDKAFKA_INCLUDE RdKafka::rdkafka INTERFACE_INCLUDE_DIRECTORIES)
    if(_RDKAFKA_INCLUDE)
        list(APPEND CONAN_INCLUDE_DIRS ${_RDKAFKA_INCLUDE})
        set(CONAN_INCLUDE_DIRS_LIBRDKAFKA ${_RDKAFKA_INCLUDE})
    endif()
endif()

# Boost
if(TARGET Boost::boost)
    get_target_property(_BOOST_INCLUDE Boost::boost INTERFACE_INCLUDE_DIRECTORIES)
    if(_BOOST_INCLUDE)
        list(APPEND CONAN_INCLUDE_DIRS ${_BOOST_INCLUDE})
        # Conan 1 兼容：设置 CONAN_BOOST_ROOT
        list(GET _BOOST_INCLUDE 0 _BOOST_FIRST)
        get_filename_component(CONAN_BOOST_ROOT "${_BOOST_FIRST}" DIRECTORY)
    endif()
endif()

# Arrow
if(TARGET arrow::arrow)
    get_target_property(_ARROW_INCLUDE arrow::arrow INTERFACE_INCLUDE_DIRECTORIES)
elseif(TARGET Arrow::arrow_static)
    get_target_property(_ARROW_INCLUDE Arrow::arrow_static INTERFACE_INCLUDE_DIRECTORIES)
endif()
if(_ARROW_INCLUDE)
    list(APPEND CONAN_INCLUDE_DIRS ${_ARROW_INCLUDE})
endif()

# fmt
if(TARGET fmt::fmt-header-only)
    get_target_property(_FMT_INCLUDE fmt::fmt-header-only INTERFACE_INCLUDE_DIRECTORIES)
elseif(TARGET fmt::fmt)
    get_target_property(_FMT_INCLUDE fmt::fmt INTERFACE_INCLUDE_DIRECTORIES)
endif()
if(_FMT_INCLUDE)
    list(APPEND CONAN_INCLUDE_DIRS ${_FMT_INCLUDE})
endif()

# Protobuf
if(TARGET protobuf::libprotobuf)
    get_target_property(_PROTOBUF_INCLUDE protobuf::libprotobuf INTERFACE_INCLUDE_DIRECTORIES)
    if(_PROTOBUF_INCLUDE)
        list(APPEND CONAN_INCLUDE_DIRS ${_PROTOBUF_INCLUDE})
    endif()
endif()

# nlohmann_json
if(TARGET nlohmann_json::nlohmann_json)
    get_target_property(_JSON_INCLUDE nlohmann_json::nlohmann_json INTERFACE_INCLUDE_DIRECTORIES)
    if(_JSON_INCLUDE)
        list(APPEND CONAN_INCLUDE_DIRS ${_JSON_INCLUDE})
    endif()
endif()

# 去重
list(REMOVE_DUPLICATES CONAN_INCLUDE_DIRS)

# =========================================
# 设置 CONAN_LIBS（所有链接目标）
# =========================================

set(CONAN_LIBS
    RocksDB::rocksdb
    Boost::boost
    Boost::filesystem
    Boost::system
    Boost::locale
    folly::folly
    TBB::tbb
    RdKafka::rdkafka
    prometheus-cpp::core
    prometheus-cpp::push
    roaring::roaring
    marisa::marisa
    GEOS::geos
    yaml-cpp::yaml-cpp
    rapidjson
    ICU::uc
    ICU::data
    simde::simde
    xxHash::xxhash
    unordered_dense::unordered_dense
    protobuf::libprotobuf
    glog::glog
    gflags::gflags
    fmt::fmt
    OpenSSL::SSL
    OpenSSL::Crypto
    nlohmann_json::nlohmann_json
)

# Arrow 和 Parquet（Parquet 是 Arrow 的组件）
# Conan 2 的 Arrow 包在启用 parquet 选项后会提供 arrow::parquet 目标
if(TARGET arrow::arrow)
    list(APPEND CONAN_LIBS arrow::arrow)
elseif(TARGET Arrow::arrow_static)
    list(APPEND CONAN_LIBS Arrow::arrow_static)
endif()

# Parquet 组件（如果可用）
if(TARGET arrow::parquet)
    list(APPEND CONAN_LIBS arrow::parquet)
elseif(TARGET Arrow::parquet_static)
    list(APPEND CONAN_LIBS Arrow::parquet_static)
endif()

# Google Cloud（可选）
if(TARGET google-cloud-cpp::storage)
    list(APPEND CONAN_LIBS google-cloud-cpp::storage)
endif()

message(STATUS "Conan 2 packages loaded via find_package()")
message(STATUS "CONAN_INCLUDE_DIRS: ${CONAN_INCLUDE_DIRS}")
message(STATUS "CONAN_BOOST_ROOT: ${CONAN_BOOST_ROOT}")
