#
# Copyright (C) 2015 The Android Open Source Project
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
import fnmatch
import imp
import logging
import multiprocessing
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree

import ndk.abis
import ndk.ansi
import ndk.ext.os
import ndk.ext.shutil
import ndk.ext.subprocess
import ndk.hosts
import ndk.ndkbuild
import ndk.test.config
import ndk.test.result


def logger():
    """Return the logger for this module."""
    return logging.getLogger(__name__)


def _get_jobs_args():
    cpus = multiprocessing.cpu_count()
    return ['-j{}'.format(cpus), '-l{}'.format(cpus)]


def _prep_build_dir(src_dir, out_dir):
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(src_dir, out_dir)


def _run_build_sh_test(test, build_dir, test_dir, ndk_path, ndk_build_flags,
                       abi, platform):
    _prep_build_dir(test_dir, build_dir)
    with ndk.ext.os.cd(build_dir):
        build_cmd = ['bash', 'build.sh'] + _get_jobs_args() + ndk_build_flags
        test_env = dict(os.environ)
        test_env['NDK'] = ndk_path
        if abi is not None:
            test_env['APP_ABI'] = abi
        test_env['APP_PLATFORM'] = 'android-{}'.format(platform)
        rc, out = ndk.ext.subprocess.call_output(build_cmd, env=test_env)
        if rc == 0:
            return ndk.test.result.Success(test)
        else:
            return ndk.test.result.Failure(test, out)


def _run_ndk_build_test(test, obj_dir, dist_dir, test_dir, ndk_path,
                        ndk_build_flags, abi, platform):
    _prep_build_dir(test_dir, obj_dir)
    with ndk.ext.os.cd(obj_dir):
        args = [
            'APP_ABI=' + abi,
            'NDK_LIBS_OUT=' + dist_dir,
        ]
        args.extend(_get_jobs_args())
        if platform is not None:
            args.append('APP_PLATFORM=android-{}'.format(platform))
        rc, out = ndk.ndkbuild.build(ndk_path, args + ndk_build_flags)
        if rc == 0:
            return ndk.test.result.Success(test)
        else:
            return ndk.test.result.Failure(test, out)


def _run_cmake_build_test(test, obj_dir, dist_dir, test_dir, ndk_path,
                          cmake_flags, abi, platform):
    _prep_build_dir(test_dir, obj_dir)

    # Add prebuilts to PATH.
    prebuilts_host_tag = ndk.hosts.get_default_host() + '-x86'
    prebuilts_bin = ndk.paths.android_path(
        'prebuilts', 'cmake', prebuilts_host_tag, 'bin')
    env_path = prebuilts_bin + os.pathsep + os.environ['PATH']

    # Fail if we don't have a working cmake executable, either from the
    # prebuilts, or from the SDK, or if a new enough version is installed.
    cmake_bin = ndk.ext.shutil.which('cmake', path=env_path)
    if cmake_bin is None:
        return ndk.test.result.Failure(test, 'cmake executable not found')

    out = subprocess.check_output([cmake_bin, '--version']).decode('utf-8')
    version_pattern = r'cmake version (\d+)\.(\d+)\.'
    version = [int(v) for v in re.match(version_pattern, out).groups()]
    if version < [3, 6]:
        return ndk.test.result.Failure(test, 'cmake 3.6 or above required')

    # Also require a working ninja executable.
    ninja_bin = ndk.ext.shutil.which('ninja', path=env_path)
    if ninja_bin is None:
        return ndk.test.result.Failure(test, 'ninja executable not found')
    rc, _ = ndk.ext.subprocess.call_output([ninja_bin, '--version'])
    if rc != 0:
        return ndk.test.result.Failure(test, 'ninja --version failed')

    toolchain_file = os.path.join(ndk_path, 'build', 'cmake',
                                  'android.toolchain.cmake')
    objs_dir = os.path.join(obj_dir, abi)
    libs_dir = os.path.join(dist_dir, abi)
    args = [
        '-H' + obj_dir,
        '-B' + objs_dir,
        '-DCMAKE_TOOLCHAIN_FILE=' + toolchain_file,
        '-DANDROID_ABI=' + abi,
        '-DCMAKE_RUNTIME_OUTPUT_DIRECTORY=' + libs_dir,
        '-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=' + libs_dir,
        '-GNinja',
        '-DCMAKE_MAKE_PROGRAM=' + ninja_bin,
    ]
    if platform is not None:
        args.append('-DANDROID_PLATFORM=android-{}'.format(platform))
    rc, out = ndk.ext.subprocess.call_output(
        [cmake_bin] + cmake_flags + args)
    if rc != 0:
        return ndk.test.result.Failure(test, out)
    rc, out = ndk.ext.subprocess.call_output(
        [cmake_bin, '--build', objs_dir, '--'] + _get_jobs_args())
    if rc != 0:
        return ndk.test.result.Failure(test, out)
    return ndk.test.result.Success(test)


class Test(object):
    def __init__(self, name, test_dir, config, ndk_path):
        self.name = name
        self.test_dir = test_dir
        self.config = config
        self.ndk_path = ndk_path

    def get_test_config(self):
        return ndk.test.config.TestConfig.from_test_dir(self.test_dir)

    def run(self, obj_dir, dist_dir, test_filters):
        raise NotImplementedError

    def __str__(self):
        return '{} [{}]'.format(self.name, self.config)


class BuildTest(Test):
    def __init__(self, name, test_dir, config, ndk_path):
        super(BuildTest, self).__init__(name, test_dir, config, ndk_path)

        if self.api is None:
            raise ValueError

    @property
    def abi(self):
        return self.config.abi

    @property
    def api(self):
        return self.config.api

    @property
    def platform(self):
        return self.api

    @property
    def ndk_build_flags(self):
        flags = self.config.get_extra_ndk_build_flags()
        if flags is None:
            flags = []
        return flags + self.get_extra_ndk_build_flags()

    @property
    def cmake_flags(self):
        flags = self.config.get_extra_cmake_flags()
        if flags is None:
            flags = []
        return flags + self.get_extra_cmake_flags()

    def run(self, obj_dir, dist_dir, _test_filters):
        raise NotImplementedError

    def check_broken(self):
        return self.get_test_config().build_broken(self.abi, self.platform)

    def check_unsupported(self):
        return self.get_test_config().build_unsupported(
            self.abi, self.platform)

    def is_negative_test(self):
        return self.get_test_config().is_negative_test()

    def get_extra_cmake_flags(self):
        return self.get_test_config().extra_cmake_flags()

    def get_extra_ndk_build_flags(self):
        return self.get_test_config().extra_ndk_build_flags()


class PythonBuildTest(BuildTest):
    """A test that is implemented by test.py.

    A test.py test has a test.py file in its root directory. This module
    contains a run_test function which returns a tuple of `(boolean_success,
    string_failure_message)` and takes the following kwargs (all of which
    default to None):

    abi: ABI to test as a string.
    platform: Platform to build against as a string.
    ndk_build_flags: Additional build flags that should be passed to ndk-build
                     if invoked as a list of strings.
    """
    def __init__(self, name, test_dir, config, ndk_path):
        api = config.api
        if api is None:
            api = ndk.abis.min_api_for_abi(config.abi)
        config = ndk.test.spec.BuildConfiguration(config.abi, api)
        super(PythonBuildTest, self).__init__(name, test_dir, config, ndk_path)

        if self.abi not in ndk.abis.ALL_ABIS:
            raise ValueError('{} is not a valid ABI'.format(self.abi))

        try:
            int(self.platform)
        except ValueError:
            raise ValueError(
                '{} is not a valid platform number'.format(self.platform))

        # Not a ValueError for this one because it should be impossible. This
        # is actually a computed result from the config we're passed.
        assert self.ndk_build_flags is not None

    def get_build_dir(self, out_dir):
        return os.path.join(out_dir, str(self.config), 'test.py', self.name)

    def run(self, obj_dir, _dist_dir, _test_filters):
        build_dir = self.get_build_dir(obj_dir)
        logger().info('Building test: %s', self.name)
        _prep_build_dir(self.test_dir, build_dir)
        with ndk.ext.os.cd(build_dir):
            module = imp.load_source('test', 'test.py')
            success, failure_message = module.run_test(
                self.ndk_path, self.abi, self.platform, self.ndk_build_flags)
            if success:
                return ndk.test.result.Success(self), []
            else:
                return ndk.test.result.Failure(self, failure_message), []


class ShellBuildTest(BuildTest):
    def __init__(self, name, test_dir, config, ndk_path):
        api = config.api
        if api is None:
            api = ndk.abis.min_api_for_abi(config.abi)
        config = ndk.test.spec.BuildConfiguration(config.abi, api)
        super(ShellBuildTest, self).__init__(name, test_dir, config, ndk_path)

    def get_build_dir(self, out_dir):
        return os.path.join(out_dir, str(self.config), 'build.sh', self.name)

    def run(self, obj_dir, _dist_dir, _test_filters):
        build_dir = self.get_build_dir(obj_dir)
        logger().info('Building test: %s', self.name)
        if os.name == 'nt':
            reason = 'build.sh tests are not supported on Windows'
            return ndk.test.result.Skipped(self, reason), []
        else:
            result = _run_build_sh_test(
                self, build_dir, self.test_dir, self.ndk_path,
                self.ndk_build_flags, self.abi, self.platform)
            return result, []


def _platform_from_application_mk(test_dir):
    """Determine target API level from a test's Application.mk.

    Args:
        test_dir: Directory of the test to read.

    Returns:
        Integer portion of APP_PLATFORM if found, else None.

    Raises:
        ValueError: Found an unexpected value for APP_PLATFORM.
    """
    application_mk = os.path.join(test_dir, 'jni/Application.mk')
    if not os.path.exists(application_mk):
        return None

    with open(application_mk) as application_mk_file:
        for line in application_mk_file:
            if line.startswith('APP_PLATFORM'):
                _, platform_str = line.split(':=')
                break
        else:
            return None

    platform_str = platform_str.strip()
    if not platform_str.startswith('android-'):
        raise ValueError(platform_str)

    _, api_level_str = platform_str.split('-')
    return int(api_level_str)


def _get_or_infer_app_platform(platform_from_user, test_dir, abi):
    """Determines the platform level to use for a test using ndk-build.

    Choose the platform level from, in order of preference:
    1. Value given as argument.
    2. APP_PLATFORM from jni/Application.mk.
    3. Default value for the target ABI.

    Args:
        platform_from_user: A user provided platform level or None.
        test_dir: The directory containing the ndk-build project.
        abi: The ABI being targeted.

    Returns:
        The platform version the test should build against.
    """
    if platform_from_user is not None:
        return platform_from_user

    minimum_version = ndk.abis.min_api_for_abi(abi)
    platform_from_application_mk = _platform_from_application_mk(test_dir)
    if platform_from_application_mk is not None:
        if platform_from_application_mk >= minimum_version:
            return platform_from_application_mk

    return minimum_version


class NdkBuildTest(BuildTest):
    def __init__(self, name, test_dir, config, ndk_path, dist):
        api = _get_or_infer_app_platform(config.api, test_dir, config.abi)
        config = ndk.test.spec.BuildConfiguration(config.abi, api)
        super(NdkBuildTest, self).__init__(name, test_dir, config, ndk_path)
        self.dist = dist

    def get_dist_dir(self, obj_dir, dist_dir):
        if self.dist:
            return self.get_build_dir(dist_dir)
        else:
            return os.path.join(self.get_build_dir(obj_dir), 'dist')

    def get_build_dir(self, out_dir):
        return os.path.join(out_dir, str(self.config), 'ndk-build', self.name)

    def run(self, obj_dir, dist_dir, _test_filters):
        logger().info('Building test: %s', self.name)
        obj_dir = self.get_build_dir(obj_dir)
        dist_dir = self.get_dist_dir(obj_dir, dist_dir)
        result = _run_ndk_build_test(
            self, obj_dir, dist_dir, self.test_dir, self.ndk_path,
            self.ndk_build_flags, self.abi, self.platform)
        return result, []


class CMakeBuildTest(BuildTest):
    def __init__(self, name, test_dir, config, ndk_path, dist):
        api = _get_or_infer_app_platform(config.api, test_dir, config.abi)
        config = ndk.test.spec.BuildConfiguration(config.abi, api)
        super(CMakeBuildTest, self).__init__(name, test_dir, config, ndk_path)
        self.dist = dist

    def get_dist_dir(self, obj_dir, dist_dir):
        if self.dist:
            return self.get_build_dir(dist_dir)
        else:
            return os.path.join(self.get_build_dir(obj_dir), 'dist')

    def get_build_dir(self, out_dir):
        return os.path.join(out_dir, str(self.config), 'cmake', self.name)

    def run(self, obj_dir, dist_dir, _test_filters):
        obj_dir = self.get_build_dir(obj_dir)
        dist_dir = self.get_dist_dir(obj_dir, dist_dir)
        logger().info('Building test: %s', self.name)
        result = _run_cmake_build_test(
            self, obj_dir, dist_dir, self.test_dir, self.ndk_path,
            self.cmake_flags, self.abi, self.platform)
        return result, []


def get_xunit_reports(xunit_file, test_base_dir, config, ndk_path):
    tree = xml.etree.ElementTree.parse(xunit_file)
    root = tree.getroot()
    cases = root.findall('.//testcase')

    reports = []
    for test_case in cases:
        mangled_test_dir = test_case.get('classname')

        # The classname is the path from the root of the libc++ test directory
        # to the directory containing the test (prefixed with 'libc++.')...
        mangled_path = '/'.join([mangled_test_dir, test_case.get('name')])

        # ... that has had '.' in its path replaced with '_' because xunit.
        test_matches = find_original_libcxx_test(mangled_path, ndk_path)
        if len(test_matches) == 0:
            raise RuntimeError('Found no matches for test ' + mangled_path)
        if len(test_matches) > 1:
            raise RuntimeError('Found multiple matches for test {}: {}'.format(
                mangled_path, test_matches))
        assert len(test_matches) == 1

        # We found a unique path matching the xunit class/test name.
        name = test_matches[0]
        test_dir = os.path.dirname(name)[len('libc++.'):]

        failure_nodes = test_case.findall('failure')
        if len(failure_nodes) == 0:
            reports.append(XunitSuccess(
                name, test_base_dir, test_dir, config, ndk_path))
            continue

        if len(failure_nodes) != 1:
            msg = ('Could not parse XUnit output: test case does not have a '
                   'unique failure node: {}'.format(name))
            raise RuntimeError(msg)

        failure_node = failure_nodes[0]
        failure_text = failure_node.text
        reports.append(XunitFailure(
            name, test_base_dir, test_dir, failure_text, config, ndk_path))
    return reports


def get_lit_cmd():
    # The build server doesn't install lit to a virtualenv, so use it from the
    # source location if possible.
    lit_path = ndk.paths.android_path('external/llvm/utils/lit/lit.py')
    if os.path.exists(lit_path):
        return ['python', lit_path]
    elif ndk.ext.shutil.which('lit'):
        return ['lit']
    return None


def find_original_libcxx_test(name, ndk_path):
    """Finds the original libc++ test file given the xunit test name.

    LIT mangles test names to replace all periods with underscores because
    xunit. This returns all tests that could possibly match the xunit test
    name.
    """

    name = ndk.paths.to_posix_path(name)

    # LIT special cases tests in the root of the test directory (such as
    # test/nothing_to_do.pass.cpp) as "libc++.libc++/$TEST_FILE.pass.cpp" for
    # some reason. Strip it off so we can find the tests.
    if name.startswith('libc++.libc++/'):
        name = 'libc++.' + name[len('libc++.libc++/'):]

    test_prefix = 'libc++.'
    if not name.startswith(test_prefix):
        raise ValueError('libc++ test name must begin with "libc++."')

    name = name[len(test_prefix):]
    test_pattern = name.replace('_', '?')
    matches = []

    # On Windows, a multiprocessing worker process does not inherit ALL_TESTS,
    # so we must scan libc++ tests in each worker.
    ndk.test.scanner.LibcxxTestScanner.find_all_libcxx_tests(ndk_path)

    all_libcxx_tests = ndk.test.scanner.LibcxxTestScanner.ALL_TESTS
    for match in fnmatch.filter(all_libcxx_tests, test_pattern):
        matches.append(test_prefix + match)
    return matches


class LibcxxTest(Test):
    def __init__(self, name, test_dir, config, ndk_path):
        if config.api is None:
            config.api = ndk.abis.min_api_for_abi(config.abi)

        super(LibcxxTest, self).__init__(name, test_dir, config, ndk_path)

    @property
    def abi(self):
        return self.config.abi

    @property
    def api(self):
        return self.config.api

    def get_build_dir(self, out_dir):
        return os.path.join(out_dir, str(self.config), 'libcxx', self.name)

    def run_lit(self, build_dir, filters):
        libcxx_dir = os.path.join(self.ndk_path, 'sources/cxx-stl/llvm-libc++')
        device_dir = '/data/local/tmp/libcxx'

        arch = ndk.abis.abi_to_arch(self.abi)
        host_tag = ndk.hosts.get_host_tag(self.ndk_path)
        triple = ndk.abis.arch_to_triple(arch)
        toolchain = ndk.abis.arch_to_toolchain(arch)

        replacements = [
            ('abi', self.abi),
            ('api', self.api),
            ('arch', arch),
            ('host_tag', host_tag),
            ('toolchain', toolchain),
            ('triple', '{}{}'.format(triple, self.api)),
            ('use_pie', True),
            ('build_dir', build_dir),
        ]
        lit_cfg_args = []
        for key, value in replacements:
            lit_cfg_args.append('--param={}={}'.format(key, value))

        shutil.copy2(os.path.join(libcxx_dir, 'test/lit.ndk.cfg.in'),
                     os.path.join(libcxx_dir, 'test/lit.site.cfg'))

        xunit_output = os.path.join(build_dir, 'xunit.xml')

        lit_args = get_lit_cmd() + [
            '-sv',
            '--param=device_dir=' + device_dir,
            '--param=unified_headers=True',
            '--param=build_only=True',
            '--no-progress-bar',
            '--show-all',
            '--xunit-xml-output=' + xunit_output,
        ] + lit_cfg_args

        default_test_path = os.path.join(libcxx_dir, 'test')
        test_paths = list(filters)
        if len(test_paths) == 0:
            test_paths.append(default_test_path)
        for test_path in test_paths:
            lit_args.append(test_path)

        # Ignore the exit code. We do most XFAIL processing outside the test
        # runner so expected failures in the test runner will still cause a
        # non-zero exit status. This "test" only fails if we encounter a Python
        # exception. Exceptions raised from our code are already caught by the
        # test runner. If that happens in LIT, the xunit output will not be
        # valid and we'll fail get_xunit_reports and raise an exception anyway.
        with open(os.devnull, 'w') as dev_null:
            stdout = dev_null
            stderr = dev_null
            if logger().isEnabledFor(logging.INFO):
                stdout = None
                stderr = None
            env = dict(os.environ)
            env['NDK'] = self.ndk_path
            subprocess.call(lit_args, env=env, stdout=stdout, stderr=stderr)

    def run(self, obj_dir, dist_dir, test_filters):
        if get_lit_cmd() is None:
            return ndk.test.result.Failure(self, 'Could not find lit'), []

        build_dir = self.get_build_dir(dist_dir)

        if not os.path.exists(build_dir):
            os.makedirs(build_dir)

        xunit_output = os.path.join(build_dir, 'xunit.xml')
        libcxx_subpath = 'sources/cxx-stl/llvm-libc++'
        libcxx_path = os.path.join(self.ndk_path, libcxx_subpath)
        libcxx_so_path = os.path.join(
            libcxx_path, 'libs', self.config.abi, 'libc++_shared.so')
        libcxx_test_path = os.path.join(libcxx_path, 'test')
        shutil.copy2(libcxx_so_path, build_dir)

        # The libc++ test runner's filters are path based. Assemble the path to
        # the test based on the late_filters (early filters for a libc++ test
        # would be simply "libc++", so that's not interesting at this stage).
        filters = []
        for late_filter in test_filters.late_filters:
            filter_pattern = late_filter.pattern
            if not filter_pattern.startswith('libc++.'):
                continue

            _, _, path = filter_pattern.partition('.')
            if not os.path.isabs(path):
                path = os.path.join(libcxx_test_path, path)

            # If we have a filter like "libc++.std", we'll run everything in
            # std, but all our XunitReport "tests" will be filtered out.  Make
            # sure we have something usable.
            if path.endswith('*'):
                # But the libc++ test runner won't like that, so strip it.
                path = path[:-1]
            else:
                assert os.path.isfile(path)

            filters.append(path)
        self.run_lit(build_dir, filters)

        for root, _, files in os.walk(libcxx_test_path):
            for test_file in files:
                if not test_file.endswith('.dat'):
                    continue
                test_relpath = os.path.relpath(root, libcxx_test_path)
                dest_dir = os.path.join(build_dir, test_relpath)
                if not os.path.exists(dest_dir):
                    continue

                shutil.copy2(os.path.join(root, test_file), dest_dir)

        # We create a bunch of fake tests that report the status of each
        # individual test in the xunit report.
        test_reports = get_xunit_reports(
            xunit_output, self.test_dir, self.config, self.ndk_path)

        return ndk.test.result.Success(self), test_reports

    # pylint: disable=no-self-use
    def check_broken(self):
        # Actual results are reported individually by pulling them out of the
        # xunit output. This just reports the status of the overall test run,
        # which should be passing.
        return None, None

    def check_unsupported(self):
        return None

    def is_negative_test(self):
        return False
    # pylint: enable=no-self-use


class XunitResult(Test):
    """Fake tests so we can show a result for each libc++ test.

    We create these by parsing the xunit XML output from the libc++ test
    runner. For each result, we create an XunitResult "test" that simply
    returns a result for the xunit status.

    We don't have an ExpectedFailure form of the XunitResult because that is
    already handled for us by the libc++ test runner.
    """
    def __init__(self, name, test_base_dir, test_dir, config, ndk_path):
        super(XunitResult, self).__init__(name, test_dir, config, ndk_path)
        self.test_base_dir = test_base_dir

    def run(self, _out_dir, _dist_dir, _test_filters):
        raise NotImplementedError

    def get_test_config(self):
        test_config_dir = os.path.join(self.test_base_dir, self.test_dir)
        return ndk.test.config.LibcxxTestConfig.from_test_dir(test_config_dir)

    def check_broken(self):
        name = os.path.splitext(os.path.basename(self.name))[0]
        config, bug = self.get_test_config().build_broken(
            self.config.abi, self.config.api, name)
        if config is not None:
            return config, bug
        return None, None

    # pylint: disable=no-self-use
    def check_unsupported(self):
        return None

    def is_negative_test(self):
        return False
    # pylint: enable=no-self-use


class XunitSuccess(XunitResult):
    def run(self, _out_dir, _dist_dir, _test_filters):
        return ndk.test.result.Success(self), []


class XunitFailure(XunitResult):
    def __init__(self, name, test_base_dir, test_dir, text, config, ndk_path):
        super(XunitFailure, self).__init__(
            name, test_base_dir, test_dir, config, ndk_path)
        self.text = text

    def run(self, _out_dir, _dist_dir, _test_filters):
        return ndk.test.result.Failure(self, self.text), []
