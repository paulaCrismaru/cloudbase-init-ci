# Copyright 2015 Cloudbase Solutions Srl
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import binascii
import operator
import os
import time
import unittest

# pylint: disable=import-error
from six.moves import urllib

from argus import config as argus_config
from argus import exceptions
from argus import log as argus_log
from argus.tests import base
from argus.tests.cloud import util as test_util
from argus import util

DNSMASQ_NEUTRON = '/etc/neutron/dnsmasq-neutron.conf'

CONFIG = argus_config.CONFIG
LOG = argus_log.LOG


def _get_dhcp_value(key):
    """Get the value of an override from the dnsmasq-config file.

    An override will be have the format 'dhcp-option-force=key,value'.
    """
    lookup = "dhcp-option-force={}".format(key)
    with open(DNSMASQ_NEUTRON) as stream:
        for line in stream:
            if not line.startswith(lookup):
                continue
            _, _, option_value = line.strip().partition("=")
            _, _, value = option_value.partition(",")
            return value.strip()


def _parse_ssh_public_keys(file_content):
    """Parses ssh-keys, so that the returned output has the right format."""
    file_content = file_content.replace("\r\n", "")
    ssh_keys = file_content.replace("ssh-rsa", "\nssh-rsa").strip()
    return ssh_keys.splitlines()


class BaseTestPassword(base.BaseTestCase):
    """Base test class for testing that passwords were set properly."""

    def _run_remote_command(self, cmd, password):
        # Test that the proper password was set.
        remote_client = self._backend.get_remote_client(
            CONFIG.cloudbaseinit.created_user, password)

        stdout = remote_client.run_command_verbose(
            cmd, command_type=util.CMD)
        return stdout

    def is_password_set(self, password):
        stdout = self._run_remote_command("echo 1", password)
        self.assertEqual('1', stdout.strip())


class TestPasswordMetadataSmoke(BaseTestPassword):
    """Password test with a provided metadata password.

    This should be used when the underlying metadata service does
    not support password posting.
    """

    def test_password_set_from_metadata(self):
        metadata = self._backend.metadata
        if metadata and metadata.get('admin_pass'):
            password = metadata['admin_pass']
            self.is_password_set(password)
        else:
            raise unittest.SkipTest("No metadata password")


class TestPasswordPostedSmoke(BaseTestPassword):
    """Test that the password was set and posted to the metadata service

    This will attempt a WinRM login on the instance, which will use the
    password which was correctly set by the underlying cloud
    initialization software.
    """

    @property
    def password(self):
        return self._backend.instance_password()

    @test_util.requires_service('http')
    def test_password_set_posted(self):
        self.is_password_set(password=self.password)


class TestPasswordPostedRescueSmoke(TestPasswordPostedSmoke):
    """Test that the password can be used in case of rescued instances."""

    @test_util.requires_service('http')
    def test_password_set_on_rescue(self):
        password = self.password

        stdout = self._run_remote_command("echo 1", password=password)
        self.assertEqual('1', stdout.strip())

        self._backend.rescue_server()
        self._recipe.prepare()
        self._backend.save_instance_output(suffix='rescue-1')
        stdout = self._run_remote_command("echo 2", password=password)
        self.assertEqual('2', stdout.strip())

        self._backend.unrescue_server()
        stdout = self._run_remote_command("echo 3", password=password)
        self.assertEqual('3', stdout.strip())


class TestCloudstackUpdatePasswordSmoke(base.BaseTestCase):
    """Tests that the service can update passwords.

    Test that the cloud initialization service can update passwords when
    using the Cloudstack metadata service.
    """

    @property
    def service_url(self):
        port = CONFIG.cloudstack_mock.password_server_port
        return "http://%(host)s:%(port)s/" % {"host": "0.0.0.0",
                                              "port": port}

    @property
    def password(self):
        generated = binascii.hexlify(os.urandom(14)).decode()
        return generated + "!*"

    def _update_password(self, password):
        url = urllib.parse.urljoin(self.service_url, 'password')
        if password:
            params = {'password': password}
        else:
            params = {}
        data = urllib.parse.urlencode(params)
        request = urllib.request.Request(url, data=data)
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc:
            return exc.code
        return response.getcode()

    def _wait_for_service_status(self, status, retry_count=3,
                                 retry_interval=1):
        def do_request():
            response_status = None
            try:
                response = urllib.request.urlopen(self.service_url)
                response_status = response.getcode()
            except urllib.error.HTTPError as error:
                response_status = error.code
            except urllib.error.URLError:
                pass
            if response_status == status:
                return True
            raise Exception()

        try:
            util.exec_with_retry(do_request, retry_count, retry_interval)
        except exceptions.ArgusTimeoutError:
            return False
        else:
            return True

    def _wait_for_completion(self, password):
        remote_client = self._backend.get_remote_client(
            CONFIG.cloudbaseinit.created_user, password)
        remote_client.manager.wait_cbinit_service()

    def _test_password(self, password, expected):
        # Set the password in the Password Server.
        response = self._update_password(password)
        self.assertEqual(200, response)

        # Reboot the instance.
        self._backend.reboot_instance()

        # Check if the password was set properly.
        self._wait_for_completion(expected)

    def test_update_password(self):
        # Get the password from the metadata.
        password = self._backend.metadata['admin_pass']

        # Wait until the web service starts serving requests.
        self.assertTrue(self._wait_for_service_status(status=400))

        # Set a new password in Password Server and test if the
        # plugin updates the password.
        new_password = self.password
        self._test_password(password=new_password, expected=new_password)
        self._backend.save_instance_output(suffix="password-1")

        # Remove the password from Password Server in order to check
        # if the plugin keeps the last password.
        self._test_password(password=None, expected=new_password)
        self._backend.save_instance_output(suffix="password-2")

        # Change the password again and check if the plugin updates it.
        self._test_password(password=password, expected=password)
        self._backend.save_instance_output(suffix="password-3")


class TestCreatedUser(base.BaseTestCase):
    """Test that the user was created.

    Test that the user created by the cloud initialization service
    was actually created.
    """

    def test_username_created(self):
        # Verify that the expected created user exists.
        exists = self._introspection.username_exists(
            CONFIG.cloudbaseinit.created_user)
        self.assertTrue(exists)


class TestSetTimezone(base.BaseTestCase):
    """Test that the expected timezone was set in the instance."""

    def test_set_timezone(self):
        # Verify that the instance timezone matches what we are
        # expecting from it.
        timezone = self._introspection.get_timezone()
        self.assertEqual("Georgian Standard Time", timezone.strip())


class TestSetHostname(base.BaseTestCase):
    """Test that the expected hostname was set in the instance."""

    def test_set_hostname(self):
        # Verify that the instance hostname matches what we are
        # expecting from it.

        hostname = self._introspection.get_instance_hostname()
        self.assertEqual("newhostname", hostname.strip())


class TestLongHostname(base.BaseTestCase):

    def test_hostname_compatibility(self):
        # Verify that the hostname is set accordingly
        # when the netbios option is set to False

        hostname = self._introspection.get_instance_hostname()
        self.assertEqual("someverylonghostnametosetonthemachine-00", hostname)


class TestSwapEnabled(base.BaseTestCase):
    """Tests whether the instance has swap enabled."""

    def test_swap_enabled(self):
        """Tests the swap status on the underlying instance."""
        swap_status = self._introspection.get_swap_status()
        self.assertTrue(swap_status)


class TestNoError(base.BaseTestCase):
    """Test class which verifies that no traceback occurs."""

    def test_any_exception_occurred(self):
        # Verify that any exception occurred in the instance
        # for Cloudbase-Init.
        instance_traceback = self._introspection.get_cloudbaseinit_traceback()
        self.assertEqual('', instance_traceback)


class TestPowershellMultipartX86TxtExists(base.BaseTestCase):
    """Tests that the file powershell_multipart_x86.txt exists on 'C:'."""

    def test_file_exists(self):
        names = self._introspection.list_location("C:\\")
        self.assertIn("powershell_multipart_x86.txt", names)


# pylint: disable=abstract-method
class TestsBaseSmoke(TestCreatedUser,
                     TestPasswordPostedSmoke,
                     TestPasswordMetadataSmoke,
                     TestNoError,
                     base.BaseTestCase):
    """Various smoke tests for testing Cloudbase-Init."""

    def test_disk_expanded(self):
        # Test the disk expanded properly.
        image = self._backend.get_image_by_ref()
        if isinstance(image, dict) and 'image' in image:
            image = image['image']

        datastore_size = image['OS-EXT-IMG-SIZE:size']
        disk_size = self._introspection.get_disk_size()
        self.assertGreater(disk_size, datastore_size)

    def test_hostname_set(self):
        # Test that the hostname was properly set.
        instance_hostname = self._introspection.get_instance_hostname()
        server = self._backend.instance_server()

        self.assertEqual(instance_hostname,
                         str(server['name'][:15]).lower())

    @test_util.skip_unless_dnsmasq_configured
    def test_ntp_properly_configured(self):
        # Verify that the expected NTP peers are active.
        peers = self._introspection.get_instance_ntp_peers()
        expected_peers = _get_dhcp_value('42').split(",")
        if expected_peers is None:
            self.fail('DHCP NTP option was not configured.')

        self.assertEqual(expected_peers, peers)

    def test_sshpublickeys_set(self):
        # Verify that we set the expected ssh keys.
        authorized_keys = self._introspection.get_instance_keys_path()
        public_keys = self._introspection.get_instance_file_content(
            authorized_keys)
        self.assertEqual(set(self._backend.public_key().splitlines()),
                         set(_parse_ssh_public_keys(public_keys)))

    def test_mtu(self):
        # Verify that we have the expected MTU in the instance.
        mtu = self._introspection.get_instance_mtu().mtu
        expected_mtu = str(self._backend.get_mtu())
        self.assertEqual(expected_mtu, mtu)

    def test_user_belongs_to_group(self):
        # Check that the created user belongs to the specified local groups
        members = self._introspection.get_group_members(
            CONFIG.cloudbaseinit.group)
        self.assertIn(CONFIG.cloudbaseinit.created_user, members)

    # pylint: disable=protected-access
    def _is_serial_port_set(self):
        """Check if the option for serial port is set.

        We look in both config objects to see if `logging_serial_port_settings`
        is set.
        :rtype: bool
        """
        args = ("DEFAULT", "logging_serial_port_settings")
        return (self._recipe._cbinit_conf.conf.has_option(*args) or
                self._recipe._cbinit_unattend_conf.conf.has_option(*args))

    def test_get_console_output(self):
        # Verify that the product emits messages to the console output.
        if not self._is_serial_port_set():
            raise unittest.SkipTest(
                "No `logging_serial_port_settings` was set for this Recipe.")
        output = self._backend.instance_output()
        self.assertTrue(output, "Console output was empty.")


class TestStaticNetwork(base.BaseTestCase):
    """Test that the static network was configured properly in instance."""

    def test_static_network(self):
        """Check if the attached NICs were properly configured."""
        # Get network adapter details within the guest compute node.
        guest_nics = self._backend.get_network_interfaces()

        # Get network adapter details within the instance.
        instance_nics = self._introspection.get_network_interfaces()

        guest_nics = [nic for nic in guest_nics if not nic["dhcp"]]
        instance_nics = [nic for nic in instance_nics if not nic["dhcp"]]

        # Sort by hardware address and compare results.
        guest_nics.sort(key=operator.itemgetter('mac'))
        instance_nics.sort(key=operator.itemgetter('mac'))
        # Do not take into account v6 DNSes, because
        # they aren't retrieved even when they are set.
        for nics in (guest_nics, instance_nics):
            for nic in nics:
                nic["dns6"] = None

        # If OS version < 6.2 then IPv6 configuration is not available
        # so we need to remove all IPv6 related keys from the dictionaries
        version = self._introspection.get_instance_os_version()
        if version < (6, 2):
            for nic in guest_nics:
                for key in list(nic.keys()):
                    if key.endswith('6'):
                        del nic[key]
            for nic in instance_nics:
                for key in list(nic.keys()):
                    if key.endswith('6'):
                        del nic[key]

        self.assertEqual(guest_nics, instance_nics)


class TestPublicKeys(base.BaseTestCase):

    def test_public_keys(self):
        # Check multiple ssh keys case.
        authorized_keys = self._introspection.get_instance_keys_path()
        public_keys = self._introspection.get_instance_file_content(
            authorized_keys)
        self.assertEqual(set(util.get_public_keys()),
                         set(_parse_ssh_public_keys(public_keys)))
