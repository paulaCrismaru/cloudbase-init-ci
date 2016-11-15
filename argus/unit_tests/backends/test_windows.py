from argus import config as argus_config
from argus.backends import windows as windows_backend

import mock
import unittest

CONFIG = argus_config.CONFIG


class TestWindowsBackendMixin(unittest.TestCase):

    def setUp(self):
        self._windows_backend_mixin = windows_backend.WindowsBackendMixin()

    @mock.patch('argus.client.windows.WinRemoteClient.__init__')
    def _test_get_remote_client(self, mock_win_remote_client,
                                username=None, password=None):
        expected_username, expected_password = username, password
        if username is None:
            expected_username = CONFIG.openstack.image_username
        if password is None:
            expected_password = CONFIG.openstack.image_password

        self._windows_backend_mixin.floating_ip = mock.Mock()
        self._windows_backend_mixin.floating_ip.return_value = "fake ip"
        mock_win_remote_client.return_value = None
        self._windows_backend_mixin.get_remote_client(username=username,
                                                      password=password,
                                                      protocol="fake protocol")
        mock_win_remote_client.assert_called_once_with(
            "fake ip", expected_username, expected_password,
            transport_protocol="fake protocol")

    def test_get_remote_client_with_username_password(self):
        self._test_get_remote_client(username="fake username",
                                     password="fake password")

    def test_get_remote_client_with_username(self):
            self._test_get_remote_client(username="fake username",
                                         password=None)

    def test_get_remote_client_with_password(self):
        self._test_get_remote_client(username=None,
                                     password="fake password")

    def test_get_remote_client_no_username_password(self):
        self._test_get_remote_client(username=None,
                                     password=None)
