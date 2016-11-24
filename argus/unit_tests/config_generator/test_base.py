from argus.config_generator import base

import mock
import unittest


class FakeBaseConfig(base.BaseConfig):

    def __init__(self):
        super(FakeBaseConfig, self).__init__(mock.sentinel)

    def set_conf_value(self, name, value, section):
        return mock.sentinel

    def apply_config(self, path):
        return mock.sentinel


class TestBaseConfig(unittest.TestCase):
    def setUp(self):
        self._baseconfig = FakeBaseConfig()

    def test_set_conf_value(self):
        result = (super(FakeBaseConfig, self._baseconfig).
                  set_conf_value(mock.sentinel, mock.sentinel,
                                 mock.sentinel))
        self.assertEqual(result, None)

    def test_apply_config(self):
        result = (super(FakeBaseConfig, self._baseconfig).
                  apply_config(mock.sentinel))
        self.assertEqual(result, None)
