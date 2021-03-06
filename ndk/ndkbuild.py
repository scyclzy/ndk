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
"""APIs for interacting with ndk-build."""
from __future__ import absolute_import

import os

import ndk.ext.subprocess


def build(ndk_path, build_flags):
    ndk_build_path = os.path.join(ndk_path, 'ndk-build')
    if os.name == 'nt':
        return ndk.ext.subprocess.call_output(
            ['cmd', '/c', ndk_build_path] + build_flags)
    return ndk.ext.subprocess.call_output([ndk_build_path] + build_flags)
