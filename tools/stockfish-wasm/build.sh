#!/bin/sh
# Builds the browser's hint and analysis engine: Stockfish dev-20261028-ff7cee42 (NNUE SFNNv19) as single-threaded
# WebAssembly, with the build system and Web Worker glue of stockfish.js 19.0.1. The result is what the release
# stockfish-dev-20261028-wasm holds and `npm run build` downloads (see README.md).
#
#   tools/stockfish-wasm/build.sh [work folder]      (Linux or WSL; default work folder: tools/stockfish-wasm/work)
#
# Needs git, make, curl, sha256sum, and Emscripten 6.0.9 (emsdk) active in the shell, which also brings Node.
# On arm64 Linux the Closure Compiler runs on Java, so `java` must be on PATH there too.
set -e

SF_TAG=stockfish-dev-20261028-ff7cee42
SFJS_COMMIT=10b49d8bb4539a0743013772ed735a63853a3b05  # stockfish.js 19.0.1
NAME=stockfish-dev-20261028-single
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=${1:-$HERE/work}

mkdir -p "$WORK"
cd "$WORK"
[ -d Stockfish ] || git clone -q --depth 1 --branch $SF_TAG https://github.com/official-stockfish/Stockfish
if [ ! -d stockfish.js ]; then
    git init -q stockfish.js
    git -C stockfish.js fetch -q --depth 1 https://github.com/nmrugg/stockfish.js $SFJS_COMMIT
    git -C stockfish.js checkout -q FETCH_HEAD
fi

# the dev source with the WebAssembly changes (stockfish-wasm.patch: the glue in src/emscripten and glue.*, and
# the __EMSCRIPTEN__ changes merged onto the dev source), built by stockfish.js's build.js and Makefile
rm -rf build && mkdir build
cp -r stockfish.js/build.js stockfish.js/package.json stockfish.js/scripts stockfish.js/Copying.txt build/
cp -r Stockfish/src build/src
(cd build/src && patch -s -p2 < "$HERE/stockfish-wasm.patch")
cp stockfish.js/src/Makefile build/src/Makefile
sed -i 's|nnue/features/half_ka_v2_hm|nnue/features/k32h3|g' build/src/Makefile  # dev's feature files
sed -i 's|"buildVersion": "19"|"buildVersion": "dev"|' build/package.json
(cd build && node build.js --single-threaded --split=6)

rm -rf out && mkdir out
cp build/src/stockfish-dev-single.js out/$NAME.js
for i in 0 1 2 3 4 5; do cp build/src/stockfish-dev-single-part-$i.wasm out/$NAME-part-$i.wasm; done
cp build/Copying.txt out/
(cd out && sha256sum * > SHA256SUMS.txt && cat SHA256SUMS.txt)
