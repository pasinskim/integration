#!/usr/bin/python
# Copyright 2017 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from fabric.api import *
import pytest
import time
from ..common import *
from ..common_docker import *
from ..common_setup import *
from ..helpers import Helpers
from ..MenderAPI import auth, auth_v2, deploy, image, logger
from .common_update import common_update_procedure
from .mendertesting import MenderTesting



class TestBootstrapping(MenderTesting):
    slow = pytest.mark.skipif(not pytest.config.getoption("--runslow"),
                              reason="need --runslow option to run")

    @MenderTesting.fast
    @pytest.mark.usefixtures("standard_setup_one_client")
    def test_bootstrap(self):
        """Simply make sure we are able to bootstrap a device"""

        execute(self.accept_devices, hosts=get_mender_clients())


    def accept_devices(self):
        auth_v2.check_expected_status("pending", len(get_mender_clients()))

        # iterate over devices and accept them
        for d in auth_v2.get_devices():
            auth_v2.set_device_auth_set_status(d["id"], d["auth_sets"][0]["id"], "accepted")
            logging.info("Accepting DeviceID: %s" % d["id"])

        # make sure all devices are accepted
        auth_v2.check_expected_status("accepted", len(get_mender_clients()))

        # make sure mender-store contains authtoken
        have_token()

        # print all device ids
        for device in auth_v2.get_devices_status("accepted"):
            logging.info("Accepted DeviceID: %s" % device["id"])

    @MenderTesting.slow
    @pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
    def test_reject_bootstrap(self):
        """Make sure a rejected device does not perform an upgrade, and that it gets it's auth token removed"""
        if not env.host_string:
            execute(self.test_reject_bootstrap, hosts=get_mender_clients())
            return

        # iterate over devices and reject them
        for device in auth_v2.get_devices():
            auth_v2.set_device_auth_set_status(device["id"], device["auth_sets"][0]["id"], "rejected")
            logging.info("Rejecting DeviceID: %s" % device["id"])

        auth_v2.check_expected_status("rejected", len(get_mender_clients()))

        with Helpers.RebootDetector() as reboot:
            try:
                deployment_id, _ = common_update_procedure(install_image=conftest.get_valid_image())
            except AssertionError:
                logging.info("Failed to deploy upgrade to rejected device.")
                reboot.verify_reboot_not_performed()

            else:
                # use assert to fail, so we can get backend logs
                pytest.fail("no error while trying to deploy to rejected device")
                return

        finished = False
        # wait until auththoken is removed from file
        for _ in range(10):
            with settings(abort_exception=Exception):
                try:
                    run("journalctl -u mender -l -n 3 | grep -q 'authentication request rejected'")
                except:
                    time.sleep(30)
                else:
                    finished = True
                    break

        auth_v2.accept_devices(1)

        if not finished:
            pytest.fail("failed to remove authtoken from mender-store file")
