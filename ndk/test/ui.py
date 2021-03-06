#
# Copyright (C) 2017 The Android Open Source Project
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
"""UI classes for test output."""
from __future__ import absolute_import
from __future__ import print_function

import os

import ndk.ui


def get_test_progress_ui(console, workqueue):
    if console.smart_console:
        ui_renderer = ndk.ui.AnsiUiRenderer(console)
        show_worker_status = True
        show_device_groups = True
    elif os.name == 'nt':
        ui_renderer = ndk.ui.DumbUiRenderer(console)
        show_worker_status = False
        show_device_groups = False
    else:
        ui_renderer = ndk.ui.DumbUiRenderer(console)
        show_worker_status = False
        show_device_groups = True
    return TestProgressUi(
        ui_renderer, show_worker_status, show_device_groups, workqueue)


class TestProgressUi(ndk.ui.Ui):
    NUM_TESTS_DIGITS = 6

    def __init__(self, ui_renderer, show_worker_status, show_device_groups,
                 workqueue):
        super(TestProgressUi, self).__init__(ui_renderer)
        self.show_worker_status = show_worker_status
        self.show_device_groups = show_device_groups
        self.workqueue = workqueue

    def get_ui_lines(self):
        lines = []

        if self.show_worker_status:
            for work_queue in self.workqueue.work_queues:
                for worker in work_queue.workers:
                    lines.append(worker.status)

        lines.append('{: >{width}} tests remaining'.format(
            self.workqueue.num_tasks, width=self.NUM_TESTS_DIGITS))

        if self.show_device_groups:
            for group in sorted(self.workqueue.task_queues.keys()):
                group_id = '{} devices android-{} {}'.format(
                    len(group.devices), group.devices[0].version,
                    ', '.join(group.abis))
                lines.append('{: >{width}} {}'.format(
                    self.workqueue.task_queues[group].qsize(), group_id,
                    width=self.NUM_TESTS_DIGITS))

        return lines


def get_test_build_progress_ui(console, workqueue):
    if console.smart_console:
        ui_renderer = ndk.ui.AnsiUiRenderer(console)
        show_worker_status = True
    else:
        ui_renderer = ndk.ui.DumbUiRenderer(console)
        show_worker_status = False
    return TestBuildProgressUi(
        ui_renderer, show_worker_status, workqueue)


class TestBuildProgressUi(ndk.ui.Ui):
    NUM_TESTS_DIGITS = 6

    def __init__(self, ui_renderer, show_worker_status, workqueue):
        super(TestBuildProgressUi, self).__init__(ui_renderer)
        self.show_worker_status = show_worker_status
        self.workqueue = workqueue

    def get_ui_lines(self):
        lines = []

        if self.show_worker_status:
            for worker in self.workqueue.main_work_queue.workers:
                lines.append(worker.status)
            for worker in self.workqueue.restricted_work_queue.workers:
                lines.append(worker.status)

        if self.ui_renderer.console.smart_console:
            # Keep some space at the top of the UI so we can see messages.
            ui_height = self.ui_renderer.console.height - 10
            if ui_height > 0:
                lines = ndk.ui.columnate(lines, self.ui_renderer.console.width,
                                         ui_height)

        lines.append('{: >{width}} tests remaining'.format(
            self.workqueue.num_tasks, width=self.NUM_TESTS_DIGITS))
        return lines
