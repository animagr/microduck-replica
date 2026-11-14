#!/usr/bin/env bash
# Fetch the upstream repos. This repo does not re-host upstream code; it only holds generated results and scripts.
set -e
mkdir -p upstream && cd upstream

# Microduck reinforcement learning training stack: the MJCF model and the 47 STLs are here
[ -d microduck_rl ] || git clone --depth 1 https://github.com/pollen-robotics/microduck_rl.git

# Microduck onboard runtime (Rust, tied to the Rockchip RK3566)
[ -d microduck ] || git clone --depth 1 https://github.com/pollen-robotics/microduck.git

# RPI Robot HAT board: the official open-source KiCad project and production files (Gerber / BOM / pick-and-place)
[ -d elec_RPI_Robot_HAT ] || git clone --depth 1 https://github.com/pollen-robotics/elec_RPI_Robot_HAT.git

cd ..
echo ""
echo "完成。重新生成上游装配分析图与预览（非实物打印件）："
echo "  python scripts/render_assembly.py upstream/microduck_rl assembly-drawings"
echo "  python scripts/export_assembly_stl.py upstream/microduck_rl analysis-output/cad-upstream"
