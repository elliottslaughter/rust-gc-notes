#!/bin/bash

# Script I used for running the Rust test suite with GC, in various
# configurations. First make sure to apply test-gc.diff, or GC won't
# be enabled on the individual tests.

build_libcore_with_gc=false
if [ $build_libcore_with_gc = true ]; then

git stash save &&
git fetch &&
git reset --hard origin/gc &&
git stash pop &&
./configure --prefix=$(pwd)/install --disable-optimize --disable-manage-submodules &&
(RUSTFLAGS='--gc -Z no-landing-pads' make -j8) &&
RUST_THREADS=1 make check -k 2>&1 | tee tests.log

else

git stash save &&
git fetch &&
git reset --hard origin/gc &&
git stash pop &&
./configure --prefix=$(pwd)/install --disable-optimize --disable-manage-submodules &&
(RUSTFLAGS='-O' make -j8) &&
RUST_THREADS=1 make check -k 2>&1 | tee tests.log

fi
