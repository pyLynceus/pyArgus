#!/bin/sh
# Scope WSL's D3D12 setup to this application; native Linux uses its own drivers.
if [ -n "${WSL_DISTRO_NAME:-}" ] && [ -r /usr/lib/wsl/lib/libd3d12.so ]; then
    export LD_LIBRARY_PATH="/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export GALLIUM_DRIVER="${GALLIUM_DRIVER:-d3d12}"
fi
exec "$(dirname "$0")/pyArgus" "$@"
