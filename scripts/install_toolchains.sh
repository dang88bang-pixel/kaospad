#!/usr/bin/env bash
# Install JDK 17, CMake, Rust and Android NDK into $HOME/toolchains when mirrors are reachable.
set -euo pipefail
ROOT="${TOOLCHAIN_ROOT:-$HOME/toolchains}"
mkdir -p "$ROOT" /tmp/kaoss-toolchains
cd /tmp/kaoss-toolchains

fetch() {
  local url="$1" out="$2"
  echo "fetch $url"
  curl -fL --retry 5 --retry-delay 2 -o "$out" "$url"
}

if [[ ! -x "$ROOT/jdk/bin/java" ]]; then
  fetch "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.13%2B11/OpenJDK17U-jdk_x64_linux_hotspot_17.0.13_11.tar.gz" jdk.tgz
  mkdir -p "$ROOT/jdk-extract"
  tar -xzf jdk.tgz -C "$ROOT/jdk-extract"
  mv "$ROOT/jdk-extract"/jdk-17* "$ROOT/jdk"
fi

if [[ ! -x "$ROOT/cmake/bin/cmake" ]]; then
  fetch "https://github.com/Kitware/CMake/releases/download/v3.29.6/cmake-3.29.6-linux-x86_64.tar.gz" cmake.tgz
  tar -xzf cmake.tgz -C "$ROOT"
  ln -sfn "$ROOT"/cmake-3.29.6-linux-x86_64 "$ROOT/cmake"
fi

if ! command -v rustc >/dev/null 2>&1; then
  fetch "https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init" rustup-init || true
  if [[ -f rustup-init ]]; then
    chmod +x rustup-init
    ./rustup-init -y --default-toolchain stable
  fi
fi

if [[ ! -d "$ROOT/android-ndk" ]]; then
  fetch "https://dl.google.com/android/repository/android-ndk-r26d-linux.zip" ndk.zip
  unzip -q ndk.zip -d "$ROOT"
  ln -sfn "$ROOT"/android-ndk-r26d "$ROOT/android-ndk"
fi

# wasm32-Toolchain für den Browser-DSP-Kern (make wasm / make test-wasm-parity)
if ! command -v emcc >/dev/null 2>&1 && ! python3 -c "import ziglang" >/dev/null 2>&1; then
  python3 -m pip install --break-system-packages ziglang >/dev/null 2>&1 \
    || python3 -m pip install ziglang >/dev/null 2>&1 \
    || echo "ziglang install fehlgeschlagen – make wasm braucht emcc, zig oder clang+wasm-ld"
fi

cat > "$ROOT/env.sh" <<EOF
export JAVA_HOME="$ROOT/jdk"
export ANDROID_NDK_HOME="$ROOT/android-ndk"
export CMAKE_HOME="$ROOT/cmake"
export PATH="\$JAVA_HOME/bin:\$CMAKE_HOME/bin:\$HOME/.cargo/bin:\$PATH"
EOF
echo "toolchains ready under $ROOT"
# shellcheck disable=SC1091
source "$ROOT/env.sh"
java -version || true
"$ROOT/cmake/bin/cmake" --version || true
rustc --version || true
ls "$ROOT/android-ndk" | head || true
