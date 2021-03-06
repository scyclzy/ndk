#!/bin/sh
#
# Copyright (C) 2011 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# This script is used to rebuild the host 'ndk-depends' tool.
#
# Note: The tool is installed under prebuilt/$HOST_TAG/bin/ndk-depends
#       by default.
#
PROGDIR=$(dirname $0)
. $NDK_BUILDTOOLS_PATH/prebuilt-common.sh

PROGRAM_PARAMETERS=""
PROGRAM_DESCRIPTION=\
"This script is used to rebuild the host ndk-depends binary program."

register_jobs_option

BUILD_DIR=
register_var_option "--build-dir=<path>" BUILD_DIR "Specify build directory"

NDK_DIR=$ANDROID_NDK_ROOT
register_var_option "--ndk-dir=<path>" NDK_DIR "Place binary in NDK installation path"

GNUMAKE=
register_var_option "--make=<path>" GNUMAKE "Specify GNU Make program"

DEBUG=
register_var_option "--debug" DEBUG "Build debug version"

SRC_DIR=
register_var_option "--src-dir=<path>" SRC_DIR "Specify binutils source dir.  Must be set for --with-libbfd"

PACKAGE_DIR=
register_var_option "--package-dir=<path>" PACKAGE_DIR "Archive binary into specific directory"

register_canadian_option
register_try64_option

extract_parameters "$@"

prepare_abi_configure_build
prepare_host_build

rm -rf $BUILD_DIR
mkdir -p $BUILD_DIR

prepare_canadian_toolchain $BUILD_DIR

CFLAGS=$HOST_CFLAGS" -O2 -s -ffunction-sections -fdata-sections"
LDFLAGS=$HOST_LDFLAGS
EXTRA_CONFIG=

if [ "$HOST_OS" != "darwin" -a "$DARWIN" != "yes" ]; then
    LDFLAGS=$LDFLAGS" -Wl,-gc-sections"
else
    # In darwin libbfd has to be built with some *linux* target or it won't understand ELF
    EXTRA_CONFIG="-target=arm-linux-androideabi"
fi

if [ "$MINGW" = "yes" ]; then
    LDFLAGS=$LDFLAGS" -static"
fi

NAME=$(get_host_exec_name ndk-depends)
INSTALL_SUBDIR=host-tools/bin
OUT=$BUILD_DIR/$NAME

# GNU Make
if [ -z "$GNUMAKE" ]; then
    GNUMAKE=make
    log "Auto-config: --make=$GNUMAKE"
fi

if [ "$PACKAGE_DIR" ]; then
    mkdir -p "$PACKAGE_DIR"
    fail_panic "Could not create package directory: $PACKAGE_DIR"
fi

# Create output directory
mkdir -p $(dirname $OUT)
if [ $? != 0 ]; then
    echo "ERROR: Could not create output directory: $(dirname $OUT)"
    exit 1
fi

SRCDIR=$ANDROID_NDK_ROOT/sources/host-tools/ndk-depends

export CFLAGS LDFLAGS
run $GNUMAKE -C $SRCDIR -f $SRCDIR/GNUmakefile \
    -B -j$NUM_JOBS \
    PROGNAME="$OUT" \
    BUILD_DIR="$BUILD_DIR" \
    CC="$CC" CXX="$CXX" \
    STRIP="$STRIP" \
    DEBUG=$DEBUG

if [ $? != 0 ]; then
    echo "ERROR: Could not build host program!"
    exit 1
fi

log "Done!"
exit 0
