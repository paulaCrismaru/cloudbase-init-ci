# Copyright 2016 Cloudbase Solutions Srl
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

import six


@six.add_metaclass(abc.ABCMeta)
class BaseConfig(object):
    """Class that abstract the config files."""

    def __init__(self, client):
        """Every Config Object needs a client.

        :param client:
            A client connected to the instance.
        """
        self._client = client

    @abc.abstractmethod
    def set_conf_value(self, name, value, section):
        """Set a config value in the specified section."""
        pass

    @abc.abstractmethod
    def apply_config(self, path):
        """Write the configuration values in the right place."""
        pass
