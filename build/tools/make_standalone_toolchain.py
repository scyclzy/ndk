#!/usr/bin/env python
#
# Copyright (C) 2016 The Android Open Source Project
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
"""Creates a toolchain installation for a given Android target.

The output of this tool is a more typical cross-compiling toolchain. It is
indended to be used with existing build systems such as autotools.
"""
import argparse
import atexit
from distutils.dir_util import copy_tree
import inspect
import logging
import platform
import os
import shutil
import stat
import sys
import tempfile
import textwrap


THIS_DIR = os.path.realpath(os.path.dirname(__file__))
NDK_DIR = os.path.realpath(os.path.join(THIS_DIR, '../..'))


def logger():
    """Return the main logger for this module."""
    return logging.getLogger(__name__)


def check_ndk_or_die():
    """Verify that our NDK installation is sane or die."""
    checks = [
        'build/core',
        'prebuilt',
        'toolchain',
    ]

    for check in checks:
        check_path = os.path.join(NDK_DIR, check)
        if not os.path.exists(check_path):
            sys.exit('Failed sanity check: missing {}'.format(check_path))


def get_triple(arch):
    """Return the triple for the given architecture."""
    return {
        'arm': 'arm-linux-androideabi',
        'arm64': 'aarch64-linux-android',
        'x86': 'i686-linux-android',
        'x86_64': 'x86_64-linux-android',
    }[arch]


def get_host_tag_or_die():
    """Return the host tag for this platform. Die if not supported."""
    if platform.system() == 'Linux':
        return 'linux-x86_64'
    elif platform.system() == 'Darwin':
        return 'darwin-x86_64'
    elif platform.system() == 'Windows':
        host_tag = 'windows-x86_64'
        if not os.path.exists(os.path.join(NDK_DIR, 'prebuilt', host_tag)):
            host_tag = 'windows'
        return host_tag
    sys.exit('Unsupported platform: ' + platform.system())


def get_toolchain_path_or_die():
    """Return the toolchain path or die."""
    toolchain_path = os.path.join(NDK_DIR, 'toolchain')
    if not os.path.exists(toolchain_path):
        sys.exit('Could not find toolchain: {}'.format(toolchain_path))
    return toolchain_path


def make_clang_scripts(install_dir, triple, api, windows):
    """Creates Clang wrapper scripts.

    The Clang in standalone toolchains historically was designed to be used as
    a drop-in replacement for GCC for better compatibility with existing
    projects. Since a large number of projects are not set up for cross
    compiling (and those that are expect the GCC style), our Clang should
    already know what target it is building for.

    Create wrapper scripts that invoke Clang with `-target` and `--sysroot`
    preset.
    """
    with open(os.path.join(install_dir, 'AndroidVersion.txt')) as version_file:
        major, minor, _build = version_file.read().strip().split('.')

    version_number = major + minor

    exe = ''
    if windows:
        exe = '.exe'

    bin_dir = os.path.join(install_dir, 'bin')
    shutil.move(os.path.join(bin_dir, 'clang' + exe),
                os.path.join(bin_dir, 'clang{}'.format(version_number) + exe))
    shutil.move(os.path.join(bin_dir, 'clang++' + exe),
                os.path.join(bin_dir, 'clang{}++'.format(
                    version_number) + exe))

    arch, os_name, env = triple.split('-')
    if arch == 'arm':
        arch = 'armv7a'  # Target armv7, not armv5.

    target = '-'.join([arch, 'none', os_name, env])
    flags = '-target {}{} -stdlib=libc++'.format(target, api)

    # We only need mstackrealign to fix issues on 32-bit x86 pre-24. After 24,
    # this consumes an extra register unnecessarily, which can cause issues for
    # inline asm.
    # https://github.com/android-ndk/ndk/issues/693
    if arch == 'i686' and api < 24:
        flags += ' -mstackrealign'

    clang_path = os.path.join(install_dir, 'bin/clang')
    with open(clang_path, 'w') as clang:
        clang.write(textwrap.dedent("""\
            #!/bin/bash
            if [ "$1" != "-cc1" ]; then
                `dirname $0`/clang{version} {flags} "$@"
            else
                # target/triple already spelled out.
                `dirname $0`/clang{version} "$@"
            fi
        """.format(version=version_number, flags=flags)))

    mode = os.stat(clang_path).st_mode
    os.chmod(clang_path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    clangpp_path = os.path.join(install_dir, 'bin/clang++')
    with open(clangpp_path, 'w') as clangpp:
        clangpp.write(textwrap.dedent("""\
            #!/bin/bash
            if [ "$1" != "-cc1" ]; then
                `dirname $0`/clang{version}++ {flags} "$@"
            else
                # target/triple already spelled out.
                `dirname $0`/clang{version}++ "$@"
            fi
        """.format(version=version_number, flags=flags)))

    mode = os.stat(clangpp_path).st_mode
    os.chmod(clangpp_path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    shutil.copy2(os.path.join(install_dir, 'bin/clang'),
                 os.path.join(install_dir, 'bin', triple + '-clang'))
    shutil.copy2(os.path.join(install_dir, 'bin/clang++'),
                 os.path.join(install_dir, 'bin', triple + '-clang++'))

    if windows:
        for pp_suffix in ('', '++'):
            exe_name = 'clang{}{}.exe'.format(version_number, pp_suffix)
            clangbat_text = textwrap.dedent("""\
                @echo off
                setlocal
                call :find_bin
                if "%1" == "-cc1" goto :L

                set "_BIN_DIR=" && %_BIN_DIR%{exe} {flags} %*
                if ERRORLEVEL 1 exit /b 1
                goto :done

                :L
                rem target/triple already spelled out.
                set "_BIN_DIR=" && %_BIN_DIR%{exe} %*
                if ERRORLEVEL 1 exit /b 1
                goto :done

                :find_bin
                rem Accommodate a quoted arg0, e.g.: "clang"
                rem https://github.com/android-ndk/ndk/issues/616
                set _BIN_DIR=%~dp0
                exit /b

                :done
            """.format(exe=exe_name, flags=flags))

            for triple_prefix in ('', triple + '-'):
                clangbat_path = os.path.join(
                    install_dir, 'bin',
                    '{}clang{}.cmd'.format(triple_prefix, pp_suffix))
                with open(clangbat_path, 'w') as clangbat:
                    clangbat.write(clangbat_text)


def replace_gcc_wrappers(install_path, triple, is_windows):
    cmd = '.cmd' if is_windows else ''

    gcc = os.path.join(install_path, 'bin', triple + '-gcc' + cmd)
    clang = os.path.join(install_path, 'bin', 'clang' + cmd)
    shutil.copy2(clang, gcc)

    gpp = os.path.join(install_path, 'bin', triple + '-g++' + cmd)
    clangpp = os.path.join(install_path, 'bin', 'clang++' + cmd)
    shutil.copy2(clangpp, gpp)


def create_toolchain(install_path, arch, api, toolchain_path, host_tag):
    """Create a standalone toolchain."""
    copy_tree(toolchain_path, install_path)
    triple = get_triple(arch)
    make_clang_scripts(
        install_path, triple, api, host_tag.startswith('windows'))
    replace_gcc_wrappers(install_path, triple, host_tag.startswith('windows'))

    prebuilt_path = os.path.join(NDK_DIR, 'prebuilt', host_tag)
    copy_tree(prebuilt_path, install_path)

    gdbserver_path = os.path.join(
        NDK_DIR, 'prebuilt', 'android-' + arch, 'gdbserver')
    gdbserver_install = os.path.join(install_path, 'share', 'gdbserver')
    shutil.copytree(gdbserver_path, gdbserver_install)


def warn_unnecessary(is_windows):
    if is_windows:
        ndk_var = '%NDK%'
        prompt = 'C:\>'
    else:
        ndk_var = '$NDK'
        prompt = '$ '

    standalone_toolchain = os.path.join(ndk_var, 'build', 'tools',
                                        'make_standalone_toolchain.py')
    toolchain_dir = os.path.join(ndk_var, 'toolchain', 'bin')
    old_clang = os.path.join('toolchain', 'bin', 'clang++')
    new_clang = os.path.join(ndk_var, 'toolchain', 'bin',
                             'armv7a-linux-androideabi21-clang++')

    logger().warning(
        textwrap.dedent("""\
        make_standalone_toolchain.py is no longer necessary. The
        {toolchain_dir} directory contains target-specific scripts that perform
        the same task. For example, instead of:

            {prompt}python {standalone_toolchain} \\
                --arch arm --api 21 --install-dir toolchain
            {prompt}{old_clang} src.cpp

        Instead use:

            {prompt}{new_clang} src.cpp
        """.format(
            toolchain_dir=toolchain_dir,
            prompt=prompt,
            standalone_toolchain=standalone_toolchain,
            old_clang=old_clang,
            new_clang=new_clang)))


def parse_args():
    """Parse command line arguments from sys.argv."""
    parser = argparse.ArgumentParser(
        description=inspect.getdoc(sys.modules[__name__]))

    parser.add_argument(
        '--arch', required=True,
        choices=('arm', 'arm64', 'x86', 'x86_64'))
    parser.add_argument(
        '--api', type=int,
        help='Target the given API version (example: "--api 24").')
    parser.add_argument(
        '--stl', help='Ignored. Retained for compatibility until NDK r19.')

    parser.add_argument(
        '--force', action='store_true',
        help='Remove existing installation directory if it exists.')
    parser.add_argument(
        '-v', '--verbose', action='count', help='Increase output verbosity.')

    def path_arg(arg):
        return os.path.realpath(os.path.expanduser(arg))

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        '--package-dir', type=path_arg, default=os.getcwd(),
        help=('Build a tarball and install it to the given directory. If '
              'neither --package-dir nor --install-dir is specified, a '
              'tarball will be created and installed to the current '
              'directory.'))
    output_group.add_argument(
        '--install-dir', type=path_arg,
        help='Install toolchain to the given directory instead of packaging.')

    return parser.parse_args()


def main():
    """Program entry point."""
    args = parse_args()

    if args.verbose is None:
        logging.basicConfig(level=logging.WARNING)
    elif args.verbose == 1:
        logging.basicConfig(level=logging.INFO)
    elif args.verbose >= 2:
        logging.basicConfig(level=logging.DEBUG)

    host_tag = get_host_tag_or_die()

    warn_unnecessary(host_tag.startswith('windows'))

    check_ndk_or_die()

    lp32 = args.arch in ('arm', 'x86')
    min_api = 16 if lp32 else 21
    api = args.api
    if api is None:
        logger().warning(
            'Defaulting to target API %d (minimum supported target for %s)',
            min_api, args.arch)
        api = min_api
    elif api < min_api:
        sys.exit('{} is less than minimum platform for {} ({})'.format(
            api, args.arch, min_api))

    triple = get_triple(args.arch)
    toolchain_path = get_toolchain_path_or_die()

    if args.install_dir is not None:
        install_path = args.install_dir
        if os.path.exists(install_path):
            if args.force:
                logger().info('Cleaning installation directory %s',
                              install_path)
                shutil.rmtree(install_path)
            else:
                sys.exit('Installation directory already exists. Use --force.')
    else:
        tempdir = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, tempdir)
        install_path = os.path.join(tempdir, triple)

    create_toolchain(install_path, args.arch, api, toolchain_path, host_tag)

    if args.install_dir is None:
        if host_tag.startswith('windows'):
            package_format = 'zip'
        else:
            package_format = 'bztar'

        package_basename = os.path.join(args.package_dir, triple)
        shutil.make_archive(
            package_basename, package_format,
            root_dir=os.path.dirname(install_path),
            base_dir=os.path.basename(install_path))


if __name__ == '__main__':
    main()
