#!/usr/bin/env bash

set -euo pipefail

coverage_root="${1:?usage: prepare_e2e_cpp_gcov.sh COVERAGE_ROOT [GCOV_BINARY]}"
gcov_bin="${2:-gcov}"
metadata="${coverage_root}/milvus-e2e-gcno.tar.gz"
counter_dir="${coverage_root}/cpp/cmake_build/src"
report_dir="${coverage_root}/cpp-gcov"

test -f "${metadata}"
test -d "${counter_dir}"
mkdir -p "${report_dir}"
tar -xzf "${metadata}" -C "${report_dir}"
cp -a "${counter_dir}/." "${report_dir}/cmake_build/src/"

processed=0
failed=0
while IFS= read -r -d '' notes; do
  object_dir="$(dirname "${notes}")"
  object_name="$(basename "${notes}" .gcno)"
  if (cd "${object_dir}" && "${gcov_bin}" --json-format --preserve-paths "${object_name}.gcno" >/dev/null 2>&1); then
    processed=$((processed + 1))
  else
    failed=$((failed + 1))
  fi
done < <(find "${report_dir}/cmake_build/src" -name '*.gcno' -print0)

printf 'gcov processed %s object files; %s failed\n' "${processed}" "${failed}"
test "${processed}" -gt 0
test "${failed}" -eq 0
find "${report_dir}" -name '*.gcov.json.gz' -print -quit | grep -q .
