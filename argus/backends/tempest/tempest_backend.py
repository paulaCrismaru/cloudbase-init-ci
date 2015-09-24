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


import abc
import contextlib
import os
import tempfile

import six

from argus.backends import base as base_backend
from argus.backends.tempest import manager as api_manager
from argus import util

with util.restore_excepthook():
    from tempest.common import waiters


LOG = util.get_logger()

# Starting size as number of lines and tolerance.
OUTPUT_SIZE = 128
OUTPUT_EPSILON = int(OUTPUT_SIZE / 10)
OUTPUT_STATUS_OK = [200]


@contextlib.contextmanager
def _create_tempfile(content):
    fd, path = tempfile.mkstemp()
    os.write(fd, content.encode())
    os.close(fd)
    try:
        yield path
    finally:
        os.remove(path)


@six.add_metaclass(abc.ABCMeta)
class BaseTempestBackend(base_backend.CloudBackend):
    """Base class for backends built on top of Tempest."""

    def __init__(self, conf, name, userdata, metadata, availability_zone):
        super(BaseTempestBackend, self).__init__(conf, name, userdata,
                                                 metadata, availability_zone)
        self._server = None
        self._keypair = None
        self._security_group = None
        self._security_groups_rules = []
        self._subnets = []
        self._routers = []
        self._floating_ip = None
        self._networks = None    # list with UUIDs for future attached NICs

        # set some members from the configuration file needed by recipes
        self.image_ref = self._conf.openstack.image_ref
        self.flavor_ref = self._conf.openstack.flavor_ref
        self.image_username = self._conf.openstack.image_username
        self.image_password = self._conf.openstack.image_password
        self.image_os_type = self._conf.openstack.image_os_type
        self._manager = api_manager.APIManager()

    def _configure_networking(self):
        subnet_id = self._manager.primary_credentials().subnet["id"]
        self._manager.network_client.update_subnet(
            subnet_id,
            dns_nameservers=self._conf.argus.dns_nameservers)

    def _create_server(self, wait_until='ACTIVE', **kwargs):
        server = self._manager.servers_client.create_server(
            util.rand_name(self._name) + "-instance",
            self.image_ref,
            self.flavor_ref,
            **kwargs)
        waiters.wait_for_server_status(
            self._manager.servers_client, server['id'], wait_until)
        return server

    def _assign_floating_ip(self):
        floating_ip = self._manager.floating_ips_client.create_floating_ip()
        floating_ip = floating_ip['floating_ip']

        self._manager.floating_ips_client.associate_floating_ip_to_server(
            floating_ip['ip'], self.internal_instance_id())
        return floating_ip

    def _add_security_group_exceptions(self, secgroup_id):
        _client = self._manager.security_group_rules_client
        rulesets = [
            {
                # http RDP
                'ip_protocol': 'tcp',
                'from_port': 3389,
                'to_port': 3389,
                'cidr': '0.0.0.0/0',
            },
            {
                # http winrm
                'ip_protocol': 'tcp',
                'from_port': 5985,
                'to_port': 5985,
                'cidr': '0.0.0.0/0',
            },
            {
                # https winrm
                'ip_protocol': 'tcp',
                'from_port': 5986,
                'to_port': 5986,
                'cidr': '0.0.0.0/0',
            },
            {
                # ssh
                'ip_protocol': 'tcp',
                'from_port': 22,
                'to_port': 22,
                'cidr': '0.0.0.0/0',
            },
            {
                # ping
                'ip_protocol': 'icmp',
                'from_port': -1,
                'to_port': -1,
                'cidr': '0.0.0.0/0',
            },
        ]
        for ruleset in rulesets:
            sg_rule = _client.create_security_group_rule(
                parent_group_id=secgroup_id, **ruleset)['security_group_rule']
            yield sg_rule

    def _create_security_groups(self):
        sg_name = util.rand_name(self.__class__.__name__)
        sg_desc = sg_name + " description"
        secgroup = self._manager.security_groups_client.create_security_group(
            name=sg_name, description=sg_desc)['security_group']

        # Add rules to the security group.
        for rule in self._add_security_group_exceptions(secgroup['id']):
            self._security_groups_rules.append(rule['id'])
        self._manager.servers_client.add_security_group(
            self.internal_instance_id(),
            secgroup['name'])
        return secgroup

    def cleanup(self):
        LOG.info("Cleaning up...")

        if self._security_groups_rules:
            for rule in self._security_groups_rules:
                self._manager.security_group_rules_client.delete_security_group_rule(rule)

        if self._security_group:
            self._manager.servers_client.remove_security_group(
                self.internal_instance_id(),
                self._security_group['name'])

        if self._server:
            self._manager.servers_client.delete_server(
                self.internal_instance_id())
            waiters.wait_for_server_termination(
                self._manager.servers_client,
                self.internal_instance_id())

        if self._floating_ip:
            self._manager.floating_ips_client.delete_floating_ip(
                self._floating_ip['id'])

        if self._keypair:
            self._keypair.destroy()

        self._manager.cleanup_credentials()

    def setup_instance(self):
        # pylint: disable=attribute-defined-outside-init
        LOG.info("Creating server...")

        self._configure_networking()
        self._keypair = self._manager.create_keypair(
            name=self.__class__.__name__)
        self._server = self._create_server(
            wait_until='ACTIVE',
            key_name=self._keypair.name,
            disk_config='AUTO',
            user_data=self.userdata,
            meta=self.metadata,
            networks=self._networks,
            availability_zone=self._availability_zone)
        self._floating_ip = self._assign_floating_ip()
        self._security_group = self._create_security_groups()

    def reboot_instance(self):
        self._manager.servers_client.reboot_server(
            server_id=self.internal_instance_id(),
            reboot_type='soft')
        waiters.wait_for_server_status(
            self._manager.servers_client,
            self.internal_instance_id(), 'ACTIVE')

    def instance_password(self):
        """Get the password posted by the instance."""
        encoded_password = self._manager.servers_client.get_password(
            self.internal_instance_id())
        with _create_tempfile(self._keypair.private_key) as tmp:
            return util.decrypt_password(
                private_key=tmp,
                password=encoded_password['password'])

    def _instance_output(self, limit):
        ret = self._manager.servers_client.get_console_output(
            self.internal_instance_id(),
            limit)
        return ret.response, ret.data

    def internal_instance_id(self):
        return self._server["id"]

    def instance_output(self, limit=OUTPUT_SIZE):
        """Get the console output, sent from the instance."""
        content = None
        while True:
            resp, content = self._instance_output(limit)
            if resp.status not in OUTPUT_STATUS_OK:
                LOG.error("Couldn't get console output <%d>.", resp.status)
                return

            if len(content.splitlines()) >= (limit - OUTPUT_EPSILON):
                limit *= 2
            else:
                break
        return content

    def instance_server(self):
        """Get the instance server object."""
        return self._manager.servers_client.show_server(self.internal_instance_id())

    def public_key(self):
        return self._keypair.public_key

    def private_key(self):
        return self._keypair.private_key

    def get_image_by_ref(self):
        return self._manager.images_client.show_image(self._conf.openstack.image_ref)

    @abc.abstractmethod
    def get_remote_client(self, username=None, password=None, **kwargs):
        """Get a remote client to the underlying instance.

        This is different than :attr:`remote_client`, because that
        will always return a client with predefined credentials,
        while this method allows for a fine-grained control
        over this aspect.
        `password` can be omitted if authentication by
        SSH key is used.
        The **kwargs parameter can be used for additional options
        (currently none).
        """

    @abc.abstractproperty
    def remote_client(self):
        """An astract property which should return the default client."""


class BaseWindowsTempestBackend(BaseTempestBackend):
    """Base Tempest backend for testing Windows."""

    def _get_log_template(self, suffix):
        template = super(BaseWindowsTempestBackend, self)._get_log_template(suffix)
        if self._conf.argus.build and self._conf.argus.arch:
            # Prepend the log with the installer information (cloud).
            template = "{}-{}-{}".format(self._conf.argus.build,
                                         self._conf.argus.arch,
                                         template)
        return template

    def get_remote_client(self, username=None, password=None,
                          protocol='http', **kwargs):
        if username is None:
            username = self.image_username
        if password is None:
            password = self.image_password
        return util.WinRemoteClient(self._floating_ip['ip'],
                                    username, password,
                                    transport_protocol=protocol)

    remote_client = util.cached_property(get_remote_client, 'remote_client')
