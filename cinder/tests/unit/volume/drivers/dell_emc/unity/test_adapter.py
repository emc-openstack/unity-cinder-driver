# Copyright (c) 2016 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import contextlib
import functools
import unittest

import mock
from oslo_utils import units

from cinder import exception
from cinder.tests.unit.volume.drivers.dell_emc.unity \
    import fake_exception as ex
from cinder.tests.unit.volume.drivers.dell_emc.unity import test_client
from cinder.volume.drivers.dell_emc.unity import adapter


########################
#
#   Start of Mocks
#
########################
class MockConfig(object):
    def __init__(self):
        self.config_group = 'test_backend'
        self.unity_storage_pool_names = ['pool1', 'pool2']
        self.unity_io_ports = None
        self.reserved_percentage = 5
        self.max_over_subscription_ratio = 300
        self.volume_backend_name = 'backend'
        self.san_ip = '1.2.3.4'
        self.san_login = 'user'
        self.san_password = 'pass'
        self.driver_ssl_cert_verify = True
        self.driver_ssl_cert_path = None
        self.remove_empty_host = False

    def safe_get(self, name):
        return getattr(self, name)


class MockConnector(object):
    @staticmethod
    def disconnect_volume(data, device):
        pass


class MockDriver(object):
    def __init__(self):
        self.configuration = mock.Mock(volume_dd_blocksize='1M')

    @staticmethod
    def _connect_device(conn):
        return {'connector': MockConnector(),
                'device': {'path': 'dev'},
                'conn': {'data': {}}}


class MockClient(object):
    def __init__(self):
        self._system = test_client.MockSystem()
        self.host = '10.10.10.10'  # fake unity IP

    @staticmethod
    def get_pools():
        return test_client.MockResourceList(['pool0', 'pool1'])

    @staticmethod
    def create_lun(name, size, pool, description=None, io_limit_policy=None):
        return test_client.MockResource(_id=name, name=name)

    @staticmethod
    def get_lun(name=None, lun_id=None):
        if lun_id is None:
            lun_id = 'lun_4'
        if lun_id in ('lun_43',):  # for thin clone cases
            return test_client.MockResource(_id=lun_id, name=name)
        if name == 'not_exists':
            ret = test_client.MockResource(name=lun_id)
            ret.existed = False
        else:
            if name is None:
                name = lun_id
            ret = test_client.MockResource(_id=lun_id, name=name)
        return ret

    @staticmethod
    def delete_lun(lun_id):
        if lun_id != 'lun_4':
            raise ex.UnexpectedLunDeletion()

    @staticmethod
    def get_serial():
        return 'CLIENT_SERIAL'

    @staticmethod
    def create_snap(src_lun_id, name=None):
        if src_lun_id in ('lun_53', 'lun_55'):  # for thin clone cases
            return test_client.MockResource(
                _id='snap_clone_{}'.format(src_lun_id))
        return test_client.MockResource(name=name, _id=src_lun_id)

    @staticmethod
    def get_snap(name=None):
        if name in ('snap_50',):  # for thin clone cases
            return name
        snap = test_client.MockResource(name=name, _id=name)
        if name is not None:
            ret = snap
        else:
            ret = [snap]
        return ret

    @staticmethod
    def delete_snap(snap):
        if snap.name in ('abc-def_snap',):
            raise ex.SnapDeleteIsCalled()

    @staticmethod
    def create_host(name):
        return test_client.MockResource(name=name)

    @staticmethod
    def create_host_wo_lock(name):
        return test_client.MockResource(name=name)

    @staticmethod
    def delete_host_wo_lock(host):
        if host.name == 'empty-host':
            raise ex.HostDeleteIsCalled()

    @staticmethod
    def attach(host, lun_or_snap):
        return 10

    @staticmethod
    def detach(host, lun_or_snap):
        error_ids = ['lun_43', 'snap_0']
        if host.name == 'host1' and lun_or_snap.get_id() in error_ids:
            raise ex.DetachIsCalled()

    @staticmethod
    def detach_all(lun):
        error_ids = ['lun_44']
        if lun.get_id() in error_ids:
            raise ex.DetachAllIsCalled()

    @staticmethod
    def get_iscsi_target_info(allowed_ports=None):
        return [{'portal': '1.2.3.4:1234', 'iqn': 'iqn.1-1.com.e:c.a.a0'},
                {'portal': '1.2.3.5:1234', 'iqn': 'iqn.1-1.com.e:c.a.a1'}]

    @staticmethod
    def get_fc_target_info(host=None, logged_in_only=False,
                           allowed_ports=None):
        if host and host.name == 'no_target':
            ret = []
        else:
            ret = ['8899AABBCCDDEEFF', '8899AABBCCDDFFEE']
        return ret

    @staticmethod
    def create_lookup_service():
        return {}

    @staticmethod
    def get_io_limit_policy(specs):
        return None

    @staticmethod
    def extend_lun(lun_id, size_gib):
        if size_gib <= 0:
            raise ex.ExtendLunError

    @staticmethod
    def get_fc_ports():
        return test_client.MockResourceList(ids=['spa_iom_0_fc0',
                                                 'spa_iom_0_fc1'])

    @staticmethod
    def get_ethernet_ports():
        return test_client.MockResourceList(ids=['spa_eth0', 'spb_eth0'])

    @staticmethod
    def thin_clone(obj, name, io_limit_policy, description, new_size_gb):
        if (obj.name, name) in (
                ('snap_61', 'lun_60'), ('lun_63', 'lun_60')):
            return test_client.MockResource(_id=name)
        else:
            raise ex.UnityThinCloneLimitExceededError

    @staticmethod
    def update_host_initiators(host, wwns):
        return None

    @property
    def system(self):
        return self._system


class MockLookupService(object):
    @staticmethod
    def get_device_mapping_from_network(initiator_wwns, target_wwns):
        return {
            'san_1': {
                'initiator_port_wwn_list':
                    ('200000051e55a100', '200000051e55a121'),
                'target_port_wwn_list':
                    ('100000051e55a100', '100000051e55a121')
            }
        }


class MockOSResource(mock.Mock):
    def __init__(self, *args, **kwargs):
        super(MockOSResource, self).__init__(*args, **kwargs)
        if 'name' in kwargs:
            self.name = kwargs['name']


def mock_adapter(driver_clz):
    ret = driver_clz()
    ret._client = MockClient()
    with mock.patch('cinder.volume.drivers.dell_emc.unity.adapter.'
                    'CommonAdapter.validate_ports'), \
            patch_storops():
        ret.do_setup(MockDriver(), MockConfig())
    ret.lookup_service = MockLookupService()
    return ret


def get_backend_qos_specs(volume):
    return None


def get_connector_properties():
    return {'host': 'host1', 'wwpns': 'abcdefg'}


def get_lun_pl(name):
    return 'id^%s|system^CLIENT_SERIAL|type^lun|version^None' % name


def get_snap_lun_pl(name):
    return 'id^%s|system^CLIENT_SERIAL|type^snap_lun|version^None' % name


def get_snap_pl(name):
    return 'id^%s|system^CLIENT_SERIAL|type^snapshot|version^None' % name


def get_connector_uids(adapter, connector):
    return []


def get_connection_info(adapter, hlu, host, connector):
    return {}


def get_volume_type_qos_specs(qos_id):
    if qos_id == 'qos':
        return {'qos_specs': {'id': u'qos_type_id_1',
                              'consumer': u'back-end',
                              u'qos_bws': u'102400',
                              u'qos_iops': u'500'}}
    if qos_id == 'qos_2':
        return {'qos_specs': {'id': u'qos_type_id_2',
                              'consumer': u'back-end',
                              u'qos_bws': u'102402',
                              u'qos_iops': u'502'}}
    return {'qos_specs': {}}


def patch_for_unity_adapter(func):
    @functools.wraps(func)
    @mock.patch('cinder.volume.drivers.dell_emc.unity.utils.'
                'get_backend_qos_specs',
                new=get_backend_qos_specs)
    @mock.patch('cinder.utils.brick_get_connector_properties',
                new=get_connector_properties)
    def func_wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return func_wrapper


def patch_for_concrete_adapter(clz_str):
    def inner_decorator(func):
        @functools.wraps(func)
        @mock.patch('%s.get_connector_uids' % clz_str,
                    new=get_connector_uids)
        @mock.patch('%s.get_connection_info' % clz_str,
                    new=get_connection_info)
        def func_wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return func_wrapper

    return inner_decorator


patch_for_iscsi_adapter = patch_for_concrete_adapter(
    'cinder.volume.drivers.dell_emc.unity.adapter.ISCSIAdapter')


patch_for_fc_adapter = patch_for_concrete_adapter(
    'cinder.volume.drivers.dell_emc.unity.adapter.FCAdapter')


@contextlib.contextmanager
def patch_thin_clone(cloned_lun):
    with mock.patch.object(adapter.CommonAdapter, '_thin_clone') as tc:
        tc.return_value = cloned_lun
        yield tc


@contextlib.contextmanager
def patch_dd_copy(copied_lun):
    with mock.patch.object(adapter.CommonAdapter, '_dd_copy') as dd:
        dd.return_value = copied_lun
        yield dd


@contextlib.contextmanager
def patch_copy_volume():
    with mock.patch('cinder.volume.utils.copy_volume') as mocked:
        yield mocked


@contextlib.contextmanager
def patch_storops():
    with mock.patch.object(adapter, 'storops') as storops:
        storops.ThinCloneActionEnum = mock.Mock(DD_COPY='DD_COPY')
        yield storops


class IdMatcher(object):
    def __init__(self, obj):
        self._obj = obj

    def __eq__(self, other):
        return self._obj._id == other._id


########################
#
#   Start of Tests
#
########################

@mock.patch.object(adapter, 'storops_ex', new=ex)
class CommonAdapterTest(unittest.TestCase):
    def setUp(self):
        self.adapter = mock_adapter(adapter.CommonAdapter)

    def test_get_managed_pools(self):
        ret = self.adapter.get_managed_pools()
        self.assertIn('pool1', ret)
        self.assertNotIn('pool0', ret)
        self.assertNotIn('pool2', ret)

    @patch_for_unity_adapter
    def test_create_volume(self):
        volume = MockOSResource(name='lun_3', size=5, host='unity#pool1')
        ret = self.adapter.create_volume(volume)
        expected = get_lun_pl('lun_3')
        self.assertEqual(expected, ret['provider_location'])

    def test_create_snapshot(self):
        volume = MockOSResource(provider_location='id^lun_43')
        snap = MockOSResource(volume=volume, name='abc-def_snap')
        result = self.adapter.create_snapshot(snap)
        self.assertEqual(get_snap_pl('lun_43'), result['provider_location'])
        self.assertEqual('lun_43', result['provider_id'])

    def test_delete_snap(self):
        def f():
            snap = MockOSResource(name='abc-def_snap')
            self.adapter.delete_snapshot(snap)

        self.assertRaises(ex.SnapDeleteIsCalled, f)

    def test_get_lun_id_has_location(self):
        volume = MockOSResource(provider_location='id^lun_43')
        self.assertEqual('lun_43', self.adapter.get_lun_id(volume))

    def test_get_lun_id_no_location(self):
        volume = MockOSResource(provider_location=None)
        self.assertEqual('lun_4', self.adapter.get_lun_id(volume))

    def test_delete_volume(self):
        volume = MockOSResource(provider_location='id^lun_4')
        self.adapter.delete_volume(volume)

    def test_get_pool_stats(self):
        stats_list = self.adapter.get_pools_stats()
        self.assertEqual(1, len(stats_list))

        stats = stats_list[0]
        self.assertEqual('pool1', stats['pool_name'])
        self.assertEqual(5, stats['total_capacity_gb'])
        self.assertEqual('pool1|CLIENT_SERIAL', stats['location_info'])
        self.assertEqual(6, stats['provisioned_capacity_gb'])
        self.assertEqual(2, stats['free_capacity_gb'])
        self.assertEqual(300, stats['max_over_subscription_ratio'])
        self.assertEqual(5, stats['reserved_percentage'])
        self.assertFalse(stats['thick_provisioning_support'])
        self.assertTrue(stats['thin_provisioning_support'])

    def test_update_volume_stats(self):
        stats = self.adapter.update_volume_stats()
        self.assertEqual('backend', stats['volume_backend_name'])
        self.assertEqual('unknown', stats['storage_protocol'])
        self.assertTrue(stats['thin_provisioning_support'])
        self.assertFalse(stats['thick_provisioning_support'])
        self.assertEqual(1, len(stats['pools']))

    def test_serial_number(self):
        self.assertEqual('CLIENT_SERIAL', self.adapter.serial_number)

    def test_do_setup(self):
        self.assertEqual('1.2.3.4', self.adapter.ip)
        self.assertEqual('user', self.adapter.username)
        self.assertEqual('pass', self.adapter.password)
        self.assertTrue(self.adapter.array_cert_verify)
        self.assertIsNone(self.adapter.array_ca_cert_path)

    def test_do_setup_version_before_4_1(self):
        def f():
            with mock.patch('cinder.volume.drivers.dell_emc.unity.adapter.'
                            'CommonAdapter.validate_ports'):
                self.adapter._client.system.system_version = '4.0.0'
                self.adapter.do_setup(self.adapter.driver, MockConfig())
        self.assertRaises(exception.VolumeBackendAPIException, f)

    def test_verify_cert_false_path_none(self):
        self.adapter.array_cert_verify = False
        self.adapter.array_ca_cert_path = None
        self.assertFalse(self.adapter.verify_cert)

    def test_verify_cert_false_path_not_none(self):
        self.adapter.array_cert_verify = False
        self.adapter.array_ca_cert_path = '/tmp/array_ca.crt'
        self.assertFalse(self.adapter.verify_cert)

    def test_verify_cert_true_path_none(self):
        self.adapter.array_cert_verify = True
        self.adapter.array_ca_cert_path = None
        self.assertTrue(self.adapter.verify_cert)

    def test_verify_cert_true_path_valide(self):
        self.adapter.array_cert_verify = True
        self.adapter.array_ca_cert_path = '/tmp/array_ca.crt'
        self.assertEqual(self.adapter.array_ca_cert_path,
                         self.adapter.verify_cert)

    def test_terminate_connection_volume(self):
        def f():
            volume = MockOSResource(provider_location='id^lun_43', id='id_43',
                                    volume_attachment=None)
            connector = {'host': 'host1'}
            self.adapter.terminate_connection(volume, connector)

        self.assertRaises(ex.DetachIsCalled, f)

    def test_terminate_connection_force_detach(self):
        def f():
            volume = MockOSResource(provider_location='id^lun_44', id='id_44',
                                    volume_attachment=None)
            self.adapter.terminate_connection(volume, None)

        self.assertRaises(ex.DetachAllIsCalled, f)

    def test_terminate_connection_snapshot(self):
        def f():
            connector = {'host': 'host1'}
            snap = MockOSResource(name='snap_0', id='snap_0',
                                  volume_attachment=None)
            self.adapter.terminate_connection_snapshot(snap, connector)

        self.assertRaises(ex.DetachIsCalled, f)

    def test_terminate_connection_remove_empty_host(self):
        self.adapter.remove_empty_host = True

        def f():
            connector = {'host': 'empty-host'}
            vol = MockOSResource(provider_location='id^lun_45', id='id_45',
                                 volume_attachment=None)
            self.adapter.terminate_connection(vol, connector)

        self.assertRaises(ex.HostDeleteIsCalled, f)

    def test_terminate_connection_multiattached_volume(self):
        def f():
            connector = {'host': 'host1'}
            attachments = [MockOSResource(id='id-1',
                                          attach_status='attached',
                                          attached_host='host1'),
                           MockOSResource(id='id-2',
                                          attach_status='attached',
                                          attached_host='host1')]
            vol = MockOSResource(provider_location='id^lun_45', id='id_45',
                                 volume_attachment=attachments)
            self.adapter.terminate_connection(vol, connector)

        self.assertIsNone(f())

    def test_manage_existing_by_name(self):
        ref = {'source-id': 12}
        volume = MockOSResource(name='lun1')
        ret = self.adapter.manage_existing(volume, ref)
        expected = get_lun_pl('12')
        self.assertEqual(expected, ret['provider_location'])

    def test_manage_existing_by_id(self):
        ref = {'source-name': 'lunx'}
        volume = MockOSResource(name='lun1')
        ret = self.adapter.manage_existing(volume, ref)
        expected = get_lun_pl('lun_4')
        self.assertEqual(expected, ret['provider_location'])

    def test_manage_existing_invalid_ref(self):
        def f():
            ref = {}
            volume = MockOSResource(name='lun1')
            self.adapter.manage_existing(volume, ref)

        self.assertRaises(exception.ManageExistingInvalidReference, f)

    def test_manage_existing_lun_not_found(self):
        def f():
            ref = {'source-name': 'not_exists'}
            volume = MockOSResource(name='lun1')
            self.adapter.manage_existing(volume, ref)

        self.assertRaises(exception.ManageExistingInvalidReference, f)

    @patch_for_unity_adapter
    def test_manage_existing_get_size_invalid_backend(self):
        def f():
            volume = MockOSResource(volume_type_id='thin',
                                    host='host@backend#pool1')
            ref = {'source-id': 12}
            self.adapter.manage_existing_get_size(volume, ref)

        self.assertRaises(exception.ManageExistingInvalidReference, f)

    @patch_for_unity_adapter
    def test_manage_existing_get_size_success(self):
        volume = MockOSResource(volume_type_id='thin',
                                host='host@backend#pool0')
        ref = {'source-id': 12}
        volume_size = self.adapter.manage_existing_get_size(volume, ref)
        self.assertEqual(5, volume_size)

    @patch_for_unity_adapter
    def test_create_volume_from_snapshot(self):
        lun_id = 'lun_50'
        volume = MockOSResource(name=lun_id, id=lun_id, host='unity#pool1')
        snap_id = 'snap_50'
        snap = MockOSResource(name=snap_id)
        with patch_thin_clone(test_client.MockResource(_id=lun_id)) as tc:
            ret = self.adapter.create_volume_from_snapshot(volume, snap)
            self.assertEqual(get_snap_lun_pl(lun_id),
                             ret['provider_location'])
            tc.assert_called_with(adapter.VolumeParams(self.adapter, volume),
                                  snap_id)

    @patch_for_unity_adapter
    def test_create_cloned_volume_attached(self):
        lun_id = 'lun_51'
        src_lun_id = 'lun_53'
        volume = MockOSResource(name=lun_id, id=lun_id, host='unity#pool1')
        src_vref = MockOSResource(id=src_lun_id, name=src_lun_id,
                                  provider_location=get_lun_pl(src_lun_id),
                                  volume_attachment=['not_care'])
        with patch_dd_copy(test_client.MockResource(_id=lun_id)) as dd:
            ret = self.adapter.create_cloned_volume(volume, src_vref)
            dd.assert_called_with(
                adapter.VolumeParams(self.adapter, volume),
                IdMatcher(test_client.MockResource(
                    _id='snap_clone_{}'.format(src_lun_id))),
                src_lun=IdMatcher(test_client.MockResource(_id=src_lun_id)))
            self.assertEqual(get_lun_pl(lun_id), ret['provider_location'])

    @patch_for_unity_adapter
    def test_create_cloned_volume_available(self):
        lun_id = 'lun_54'
        src_lun_id = 'lun_55'
        volume = MockOSResource(id=lun_id, host='unity#pool1', size=3,
                                provider_location=get_lun_pl(lun_id))
        src_vref = MockOSResource(id=src_lun_id, name=src_lun_id,
                                  provider_location=get_lun_pl(src_lun_id),
                                  volume_attachment=None)
        with patch_thin_clone(test_client.MockResource(_id=lun_id)) as tc:
            ret = self.adapter.create_cloned_volume(volume, src_vref)
            tc.assert_called_with(
                adapter.VolumeParams(self.adapter, volume),
                IdMatcher(test_client.MockResource(
                    _id='snap_clone_{}'.format(src_lun_id))),
                src_lun=IdMatcher(test_client.MockResource(_id=src_lun_id)))
            self.assertEqual(get_snap_lun_pl(lun_id), ret['provider_location'])

    @patch_for_unity_adapter
    def test_dd_copy_with_src_lun(self):
        lun_id = 'lun_56'
        src_lun_id = 'lun_57'
        src_snap_id = 'snap_57'
        volume = MockOSResource(name=lun_id, id=lun_id, host='unity#pool1',
                                provider_location=get_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        src_lun = test_client.MockResource(name=src_lun_id, _id=src_lun_id)
        src_lun.size_total = 6 * units.Gi
        with patch_copy_volume() as copy_volume:
            ret = self.adapter._dd_copy(
                adapter.VolumeParams(self.adapter, volume), src_snap,
                src_lun=src_lun)
            copy_volume.assert_called_with('dev', 'dev', 6144, '1M',
                                           sparse=True)
            self.assertEqual(IdMatcher(test_client.MockResource(_id=lun_id)),
                             ret)

    @patch_for_unity_adapter
    def test_dd_copy_wo_src_lun(self):
        lun_id = 'lun_58'
        src_lun_id = 'lun_59'
        src_snap_id = 'snap_59'
        volume = MockOSResource(name=lun_id, id=lun_id, host='unity#pool1',
                                provider_location=get_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        src_snap.storage_resource = test_client.MockResource(name=src_lun_id,
                                                             _id=src_lun_id)
        with patch_copy_volume() as copy_volume:
            ret = self.adapter._dd_copy(
                adapter.VolumeParams(self.adapter, volume), src_snap)
            copy_volume.assert_called_with('dev', 'dev', 5120, '1M',
                                           sparse=True)
            self.assertEqual(IdMatcher(test_client.MockResource(_id=lun_id)),
                             ret)

    @patch_for_unity_adapter
    def test_dd_copy_raise(self):
        lun_id = 'lun_58'
        src_snap_id = 'snap_59'
        volume = MockOSResource(name=lun_id, id=lun_id, host='unity#pool1',
                                provider_location=get_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        with patch_copy_volume() as copy_volume:
            copy_volume.side_effect = AttributeError
            self.assertRaises(AttributeError,
                              self.adapter._dd_copy, volume, src_snap)

    @patch_for_unity_adapter
    def test_thin_clone(self):
        lun_id = 'lun_60'
        src_snap_id = 'snap_61'
        volume = MockOSResource(name=lun_id, id=lun_id, size=1,
                                provider_location=get_snap_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        ret = self.adapter._thin_clone(volume, src_snap)
        self.assertEqual(IdMatcher(test_client.MockResource(_id=lun_id)), ret)

    @patch_for_unity_adapter
    def test_thin_clone_downgraded_with_src_lun(self):
        lun_id = 'lun_60'
        src_snap_id = 'snap_62'
        src_lun_id = 'lun_62'
        volume = MockOSResource(name=lun_id, id=lun_id, size=1,
                                provider_location=get_snap_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        src_lun = test_client.MockResource(name=src_lun_id, _id=src_lun_id)
        new_dd_lun = test_client.MockResource(name='lun_63')
        with patch_storops() as mocked_storops, \
                patch_dd_copy(new_dd_lun) as dd:
            ret = self.adapter._thin_clone(
                adapter.VolumeParams(self.adapter, volume),
                src_snap, src_lun=src_lun)
            vol_params = adapter.VolumeParams(self.adapter, volume)
            vol_params.name = 'hidden-{}'.format(volume.name)
            vol_params.description = 'hidden-{}'.format(volume.description)
            dd.assert_called_with(vol_params, src_snap, src_lun=src_lun)
            mocked_storops.TCHelper.notify.assert_called_with(src_lun,
                                                              'DD_COPY',
                                                              new_dd_lun)
        self.assertEqual(IdMatcher(test_client.MockResource(_id=lun_id)), ret)

    @patch_for_unity_adapter
    def test_thin_clone_downgraded_wo_src_lun(self):
        lun_id = 'lun_60'
        src_snap_id = 'snap_62'
        volume = MockOSResource(name=lun_id, id=lun_id, size=1,
                                provider_location=get_snap_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        new_dd_lun = test_client.MockResource(name='lun_63')
        with patch_storops() as mocked_storops, \
                patch_dd_copy(new_dd_lun) as dd:
            ret = self.adapter._thin_clone(
                adapter.VolumeParams(self.adapter, volume), src_snap)
            vol_params = adapter.VolumeParams(self.adapter, volume)
            vol_params.name = 'hidden-{}'.format(volume.name)
            vol_params.description = 'hidden-{}'.format(volume.description)
            dd.assert_called_with(vol_params, src_snap, src_lun=None)
            mocked_storops.TCHelper.notify.assert_called_with(src_snap,
                                                              'DD_COPY',
                                                              new_dd_lun)
        self.assertEqual(IdMatcher(test_client.MockResource(_id=lun_id)), ret)

    def test_extend_volume_error(self):
        def f():
            volume = MockOSResource(id='l56',
                                    provider_location=get_lun_pl('lun56'))
            self.adapter.extend_volume(volume, -1)

        self.assertRaises(ex.ExtendLunError, f)

    def test_extend_volume_no_id(self):
        def f():
            volume = MockOSResource(provider_location='type^lun')
            self.adapter.extend_volume(volume, 5)

        self.assertRaises(exception.VolumeBackendAPIException, f)

    def test_normalize_config(self):
        config = MockConfig()
        config.unity_storage_pool_names = ['  pool_1  ', '', '    ']
        config.unity_io_ports = ['  spa_eth2  ', '', '   ']
        normalized = self.adapter.normalize_config(config)
        self.assertEqual(['pool_1'], normalized.unity_storage_pool_names)
        self.assertEqual(['spa_eth2'], normalized.unity_io_ports)

    def test_normalize_config_raise(self):
        with self.assertRaisesRegexp(exception.InvalidConfigurationValue,
                                     'unity_storage_pool_names'):
            config = MockConfig()
            config.unity_storage_pool_names = ['', '    ']
            self.adapter.normalize_config(config)
        with self.assertRaisesRegexp(exception.InvalidConfigurationValue,
                                     'unity_io_ports'):
            config = MockConfig()
            config.unity_io_ports = ['', '   ']
            self.adapter.normalize_config(config)


class FCAdapterTest(unittest.TestCase):
    def setUp(self):
        self.adapter = mock_adapter(adapter.FCAdapter)

    def test_setup(self):
        self.assertIsNotNone(self.adapter.lookup_service)

    def test_auto_zone_enabled(self):
        self.assertTrue(self.adapter.auto_zone_enabled)

    def test_fc_protocol(self):
        stats = mock_adapter(adapter.FCAdapter).update_volume_stats()
        self.assertEqual('FC', stats['storage_protocol'])

    def test_get_connector_uids(self):
        connector = {'host': 'fake_host',
                     'wwnns': ['1111111111111111',
                               '2222222222222222'],
                     'wwpns': ['3333333333333333',
                               '4444444444444444']
                     }
        expected = ['11:11:11:11:11:11:11:11:33:33:33:33:33:33:33:33',
                    '22:22:22:22:22:22:22:22:44:44:44:44:44:44:44:44']
        ret = self.adapter.get_connector_uids(connector)
        self.assertListEqual(expected, ret)

    def test_get_connection_info_no_targets(self):
        def f():
            host = test_client.MockResource('no_target')
            self.adapter.get_connection_info(12, host, {})

        self.assertRaises(exception.VolumeBackendAPIException, f)

    def test_get_connection_info_auto_zone_enabled(self):
        host = test_client.MockResource('host1')
        connector = {'wwpns': 'abcdefg'}
        ret = self.adapter.get_connection_info(10, host, connector)
        target_wwns = ['100000051e55a100', '100000051e55a121']
        self.assertListEqual(target_wwns, ret['target_wwn'])
        init_target_map = {
            '200000051e55a100': ('100000051e55a100', '100000051e55a121'),
            '200000051e55a121': ('100000051e55a100', '100000051e55a121')}
        self.assertDictEqual(init_target_map, ret['initiator_target_map'])
        self.assertEqual(10, ret['target_lun'])

    def test_get_connection_info_auto_zone_disabled(self):
        self.adapter.lookup_service = None
        host = test_client.MockResource('host1')
        connector = {'wwpns': 'abcdefg'}
        ret = self.adapter.get_connection_info(10, host, connector)
        self.assertEqual(10, ret['target_lun'])
        wwns = ['8899AABBCCDDEEFF', '8899AABBCCDDFFEE']
        self.assertListEqual(wwns, ret['target_wwn'])

    @patch_for_fc_adapter
    def test_initialize_connection_volume(self):
        volume = MockOSResource(provider_location='id^lun_43', id='id_43')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection(volume, connector)
        self.assertEqual('fibre_channel', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('id_43', conn_info['data']['volume_id'])

    @patch_for_fc_adapter
    def test_initialize_connection_snapshot(self):
        snap = MockOSResource(id='snap_1', name='snap_1')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection_snapshot(
            snap, connector)
        self.assertEqual('fibre_channel', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('snap_1', conn_info['data']['volume_id'])

    def test_terminate_connection_auto_zone_enabled(self):
        connector = {'host': 'host1', 'wwpns': 'abcdefg'}
        volume = MockOSResource(provider_location='id^lun_41', id='id_41',
                                volume_attachment=None)
        ret = self.adapter.terminate_connection(volume, connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        data = ret['data']
        target_map = {
            '200000051e55a100': ('100000051e55a100', '100000051e55a121'),
            '200000051e55a121': ('100000051e55a100', '100000051e55a121')}
        self.assertDictEqual(target_map, data['initiator_target_map'])
        target_wwn = ['100000051e55a100', '100000051e55a121']
        self.assertListEqual(target_wwn, data['target_wwn'])

    def test_terminate_connection_auto_zone_enabled_none_host_luns(self):
        connector = {'host': 'host-no-host_luns', 'wwpns': 'abcdefg'}
        volume = MockOSResource(provider_location='id^lun_41', id='id_41',
                                volume_attachment=None)
        ret = self.adapter.terminate_connection(volume, connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        data = ret['data']
        target_map = {
            '200000051e55a100': ('100000051e55a100', '100000051e55a121'),
            '200000051e55a121': ('100000051e55a100', '100000051e55a121')}
        self.assertDictEqual(target_map, data['initiator_target_map'])
        target_wwn = ['100000051e55a100', '100000051e55a121']
        self.assertListEqual(target_wwn, data['target_wwn'])

    def test_terminate_connection_remove_empty_host_return_data(self):
        self.adapter.remove_empty_host = True
        connector = {'host': 'empty-host-return-data', 'wwpns': 'abcdefg'}
        volume = MockOSResource(provider_location='id^lun_41', id='id_41',
                                volume_attachment=None)
        ret = self.adapter.terminate_connection(volume, connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        data = ret['data']
        target_map = {
            '200000051e55a100': ('100000051e55a100', '100000051e55a121'),
            '200000051e55a121': ('100000051e55a100', '100000051e55a121')}
        self.assertDictEqual(target_map, data['initiator_target_map'])
        target_wwn = ['100000051e55a100', '100000051e55a121']
        self.assertListEqual(target_wwn, data['target_wwn'])

    def test_validate_ports_whitelist_none(self):
        ports = self.adapter.validate_ports(None)
        self.assertEqual(set(('spa_iom_0_fc0', 'spa_iom_0_fc1')), set(ports))

    def test_validate_ports(self):
        ports = self.adapter.validate_ports(['spa_iom_0_fc0'])
        self.assertEqual(set(('spa_iom_0_fc0',)), set(ports))

    def test_validate_ports_asterisk(self):
        ports = self.adapter.validate_ports(['spa*'])
        self.assertEqual(set(('spa_iom_0_fc0', 'spa_iom_0_fc1')), set(ports))

    def test_validate_ports_question_mark(self):
        ports = self.adapter.validate_ports(['spa_iom_0_fc?'])
        self.assertEqual(set(('spa_iom_0_fc0', 'spa_iom_0_fc1')), set(ports))

    def test_validate_ports_no_matched(self):
        with self.assertRaisesRegexp(exception.InvalidConfigurationValue,
                                     'unity_io_ports'):
            self.adapter.validate_ports(['spc_invalid'])

    def test_validate_ports_unmatched_whitelist(self):
        with self.assertRaisesRegexp(exception.InvalidConfigurationValue,
                                     'unity_io_ports'):
            self.adapter.validate_ports(['spa_iom*', 'spc_invalid'])


class ISCSIAdapterTest(unittest.TestCase):
    def setUp(self):
        self.adapter = mock_adapter(adapter.ISCSIAdapter)

    def test_iscsi_protocol(self):
        stats = self.adapter.update_volume_stats()
        self.assertEqual('iSCSI', stats['storage_protocol'])

    def test_get_connector_uids(self):
        connector = {'host': 'fake_host', 'initiator': 'fake_iqn'}
        ret = self.adapter.get_connector_uids(connector)
        self.assertListEqual(['fake_iqn'], ret)

    def test_get_connection_info(self):
        connector = {'host': 'fake_host', 'initiator': 'fake_iqn'}
        hlu = 10
        info = self.adapter.get_connection_info(hlu, None, connector)
        target_iqns = ['iqn.1-1.com.e:c.a.a0', 'iqn.1-1.com.e:c.a.a1']
        target_portals = ['1.2.3.4:1234', '1.2.3.5:1234']
        self.assertListEqual(target_iqns, info['target_iqns'])
        self.assertListEqual([hlu, hlu], info['target_luns'])
        self.assertListEqual(target_portals, info['target_portals'])
        self.assertEqual(hlu, info['target_lun'])
        self.assertTrue(info['target_portal'] in target_portals)
        self.assertTrue(info['target_iqn'] in target_iqns)

    @patch_for_iscsi_adapter
    def test_initialize_connection_volume(self):
        volume = MockOSResource(provider_location='id^lun_43', id='id_43')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection(volume, connector)
        self.assertEqual('iscsi', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('id_43', conn_info['data']['volume_id'])

    @patch_for_iscsi_adapter
    def test_initialize_connection_snapshot(self):
        snap = MockOSResource(id='snap_1', name='snap_1')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection_snapshot(
            snap, connector)
        self.assertEqual('iscsi', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('snap_1', conn_info['data']['volume_id'])
