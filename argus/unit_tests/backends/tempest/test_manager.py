from argus.backends.tempest import manager
from argus import exceptions

import mock
import unittest


class TestAPIManager(unittest.TestCase):

    @mock.patch('tempest.clients.Manager')
    @mock.patch('tempest.common.waiters')
    @mock.patch('tempest.common.credentials_factory.get_credentials_provider')
    def setUp(self, mock_credentials, mock_waiters, mock_clients):
        self._api_manager = manager.APIManager()

    def test_cleanup_credentials(self):
        mock_isolated_creds = mock.Mock()
        mock_isolated_creds.return_value = True
        self._api_manager.isolated_creds = mock_isolated_creds
        self._api_manager.cleanup_credentials()
        mock_isolated_creds.clear_creds.assert_called_once()

    @mock.patch('argus.backends.tempest.manager.Keypair')
    def test_create_key_pair(self, mock_keypair):
        fake_keypair = {
            "public_key": "fake public key",
            "private_key": "fake private key",
            "name": "fake name"
        }
        mock_keypairs_client = mock.Mock()
        mock_keypairs_client.create_keypair.return_value = {
            'keypair': fake_keypair
        }
        self._api_manager.keypairs_client = mock_keypairs_client
        self._api_manager.create_keypair("fake name")
        mock_keypair.assert_called_once()

    @mock.patch('tempest.common.waiters.wait_for_server_status')
    def test_reboot_instance(self, mock_waiters):
        mock_servers_client = mock.Mock()
        mock_servers_client.reboot_server.return_value = None

        self._api_manager.servers_client = mock.Mock()

        self._api_manager.reboot_instance(instance_id="fake id")
        self._api_manager.servers_client.reboot_server.assert_called_once()
        mock_waiters.assert_called_once()

    @mock.patch('argus.backends.tempest.manager._create_tempfile')
    @mock.patch('argus.util.decrypt_password')
    def test_instance_password(self, mock_decrypt_password,
                               mock_create_temp_file):
        mock_servers_client = mock.Mock()
        mock_servers_client.show_password.return_value = {
            "password": "fake password"
        }

        self._api_manager.servers_client = mock_servers_client
        mock_decrypt_password.return_value = "fake return"
        mock_keypair = mock.Mock()
        mock_keypair.private_key = "fake private key"
        result = self._api_manager.instance_password(instance_id="fake id",
                                                     keypair=mock_keypair)

        self.assertEquals(result, "fake return")
        (self._api_manager.servers_client.show_password.
            assert_called_once_with("fake id"))
        mock_create_temp_file.assert_called_once_with("fake private key")

    def test__instance_output(self):
        mock_servers_client = mock.Mock()
        mock_servers_client.get_console_output.return_value = {
            "output": "fake output"
        }
        self._api_manager.servers_client = mock_servers_client

        result = self._api_manager._instance_output(instance_id="fake id",
                                                    limit="fake limit")
        self.assertEquals(result, "fake output")

    def test_instance_output(self):
        fake_content = "fake content 1\nfake content 2"
        mock__instance_output = mock.Mock()
        mock__instance_output.return_value = fake_content

        self._api_manager._instance_output = mock__instance_output

        self._api_manager.instance_output(instance_id="fake id", limit=10)

        self.assertEquals(2, mock__instance_output.call_count)

    def test_instance_server(self):
        mock_servers_client = mock.Mock()
        mock_servers_client.show_server.return_value = {
            'server': "fake server"
        }
        self._api_manager.servers_client = mock_servers_client

        result = self._api_manager.instance_server(instance_id="fake id")

        self.assertEquals(result, "fake server")
        (self._api_manager.servers_client.show_server.
            assert_called_once_with("fake id"))

    def test_get_mtu(self):
        mock_network = mock.Mock()
        mock_network.network = {"mtu": "fake mtu"}
        mock_primary_credentials = mock.Mock()
        mock_primary_credentials.return_value = mock_network
        self._api_manager.primary_credentials = mock_primary_credentials

        result = self._api_manager.get_mtu()
        self.assertEquals(result, "fake mtu")

    @mock.patch('argus.backends.tempest.manager.APIManager.'
                'primary_credentials')
    def test_get_mtu_fails(self, mock_primary_credentials):
        mock_primary_credentials.side_effect = exceptions.ArgusError(
            "fake exception")
        with self.assertRaises(exceptions.ArgusError):
            result = self._api_manager.get_mtu()
            self.assertEquals('Could not get the MTU from the '
                              'tempest backend: fake exception', result)
            mock_primary_credentials.assert_called_once()


class TestKeypair(unittest.TestCase):

    def setUp(self):
        self._key_pair = manager.Keypair(name="fake name",
                                         public_key="fake public key",
                                         private_key="fake private key",
                                         manager="fake manager")

    def test_destroy(self):
        self._key_pair._manager = mock.Mock()
        (self._key_pair._manager.keypairs_client.delete_keypair.
            return_value) = True
        self._key_pair.destroy()
        (self._key_pair._manager.keypairs_client.delete_keypair.
            assert_called_once_with("fake name"))


class TestCreateTempFile(unittest.TestCase):

    @mock.patch('os.remove')
    @mock.patch('os.write')
    @mock.patch('os.close')
    @mock.patch('tempfile.mkstemp')
    def test_create_temp_file(self, mock_mkstemp,
                              mock_close, mock_write, mock_remove):
        content = mock.Mock()
        content.encode.return_value = mock.sentinel
        mock_mkstemp.return_value = "fd", "path"
        with manager._create_tempfile(content) as result:
            self.assertEqual(result, "path")
        mock_mkstemp.assert_called_once_with()
        mock_write.assert_called_once_with(
            "fd", content.encode.return_value)
        mock_close.assert_called_once_with("fd")
        mock_remove.assert_called_once_with("path")
