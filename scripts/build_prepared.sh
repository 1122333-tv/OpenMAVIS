#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
jobs=${JOBS:-4}
output_root=${OUTPUT_ROOT:-$root}
build_dir=${BUILD_DIR:-$root/build}
cmake -S "$root/Thirdparty/DBoW2" -B "$root/Thirdparty/DBoW2/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$root/Thirdparty/DBoW2/build" -j "$jobs"
if [[ ! -s "$root/Vocabulary/ORBvoc.txt" ]]; then
  tar -xf "$root/Vocabulary/ORBvoc.txt.tar.gz" -C "$root/Vocabulary"
fi
cmake -S "$root" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release -DOPENMAVIS_OUTPUT_ROOT="$output_root"
cmake --build "$build_dir" --target g2o -j "$jobs"
cmake --build "$build_dir" --target multi_inertial_prepared multi_inertial_euroc prepared_camera_audit prepared_match_audit multi_regression -j "$jobs"
python3 "$root/scripts/record_prepared_build.py" --output-root "$output_root" --build-dir "$build_dir"
