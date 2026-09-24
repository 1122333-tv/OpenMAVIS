#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
jobs=${JOBS:-4}
cmake -S "$root/Thirdparty/DBoW2" -B "$root/Thirdparty/DBoW2/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$root/Thirdparty/DBoW2/build" -j "$jobs"
if [[ ! -s "$root/Vocabulary/ORBvoc.txt" ]]; then
  tar -xf "$root/Vocabulary/ORBvoc.txt.tar.gz" -C "$root/Vocabulary"
fi
cmake -S "$root" -B "$root/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$root/build" --target g2o -j "$jobs"
cmake --build "$root/build" --target multi_inertial_prepared multi_inertial_euroc prepared_camera_audit -j "$jobs"
