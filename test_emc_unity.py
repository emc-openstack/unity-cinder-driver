# Copyright (c) 2016 EMC Corporation, Inc.
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

import mock

import urllib2

from cinder import exception
from cinder import test
from cinder.tests.unit import fake_consistencygroup
from cinder.tests.unit import fake_snapshot
from cinder.volume import configuration as conf
from cinder.volume.drivers.emc import emc_unity
from cinder.volume.drivers.emc.emc_unity import EMCUnityDriver
from cinder.volume.drivers.emc.emc_unity import EMCUnityRESTClient
from cinder.volume import volume_types

GiB = 1024 * 1024 * 1024
VERSION = emc_unity.VERSION


class EMCUnityDriverTestData(object):
    storage_pool_name_default = 'StoragePool00'

    storage_pool_id_default = 'pool_1'

    resp_get_pool_by_name = {
        'entries': [
            {'content': {'id': storage_pool_id_default,
                         'name': storage_pool_name_default,
                         'sizeTotal': 28185722880,
                         'sizeFree': 17985175552}}]}

    @staticmethod
    def req_get_pool_by_name(name, fields=None):
        url = '/api/types/pool/instances?filter=%s' % \
              urllib2.quote('name eq "%s"' % name)
        url += (('&fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    @staticmethod
    def req_get_pool_by_id(id, fields=None):
        url = '/api/instances/pool/%(obj_id)s' % \
              {'obj_id': id}
        if fields:
            url += '?fields=%s' % (','.join(fields))
        return mock.call(url)

    resp_get_pool_by_id = {
        'content': {'id': storage_pool_id_default,
                    'name': storage_pool_name_default,
                    'sizeTotal': 28185722880,
                    'sizeFree': 17985175552}}

    new_resp_get_pool_by_id = {
        'content': {'id': storage_pool_id_default,
                    'name': storage_pool_name_default,
                    'sizeTotal': 2147483678,
                    'sizeFree': 1073741824}}

    storage_serial_number_default = 'FCNCH0972C7F2A'

    resp_get_basic_system_info = {
        'entries': [
            {'content': {'id': '0',
                         'name': storage_serial_number_default,
                         'softwareVersion': '4.0.0'}}]}

    @staticmethod
    def req_get_basic_system_info(fields=None):
        url = '/api/types/basicSystemInfo/instances'
        url += (('?fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    resp_get_get_iscsi_portals = {
        'entries': [
            {'content':
                {'id': 'if_4',
                 'ipAddress': '10.108.127.43',
                 'ethernetPort': {'id': 'spa_iom_0_eth0'},
                 'iscsiNode': {'id': 'iscsinode_spa_iom_0_eth0'}}},
            {'content':
                {'id': 'if_5',
                 'ipAddress': '10.108.127.44',
                 'ethernetPort': {'id': 'spb_iom_0_eth0'},
                 'iscsiNode': {'id': 'iscsinode_spb_iom_0_eth0'}}}]}

    new_resp_get_get_iscsi_portals = {
        'entries': [
            {'content':
                {'id': 'if_4',
                 'ipAddress': '10.108.127.45',
                 'ethernetPort': {'id': 'spa_iom_0_eth0'},
                 'iscsiNode': {'id': 'iscsinode_spa_iom_0_eth0'}}},
            {'content':
                {'id': 'if_5',
                 'ipAddress': '10.108.127.46',
                 'ethernetPort': {'id': 'spb_iom_0_eth0'},
                 'iscsiNode': {'id': 'iscsinode_spb_iom_0_eth0'}}}]}

    @staticmethod
    def req_get_get_iscsi_portals(fields=None):
        url = '/api/types/iscsiPortal/instances'
        url += (('?fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    resp_get_iscsi_nodes = {
        'entries': [
            {'content':
                {'id': 'iscsinode_spa_iom_0_eth0',
                 'name': 'iqn.1992-04.com.emc:cx.fcnch0972c7f2a.a4'}},
            {'content':
                {'id': 'iscsinode_spb_iom_0_eth0',
                 'name': 'iqn.1992-04.com.emc:cx.fcnch0972c7f2a.b4'}}]}

    @staticmethod
    def req_get_get_iscsi_nodes(fields=None):
        url = '/api/types/iscsiNode/instances'
        url += (('?fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    iscsi_targets = {'a': [('iqn.1992-04.com.emc:cx.fcnch0972c7f2a.a4',
                            '10.108.127.43', 'if_4')],
                     'b': [('iqn.1992-04.com.emc:cx.fcnch0972c7f2a.b4',
                            '10.108.127.44', 'if_5')]}

    n_iscsi_targets = {'a': [('iqn.1992-04.com.emc:cx.fcnch0972c7f2a.a4',
                              '10.108.127.45', 'if_4')],
                       'b': [('iqn.1992-04.com.emc:cx.fcnch0972c7f2a.b4',
                              '10.108.127.46', 'if_5')]}

    @staticmethod
    def get_iscsi_iqns(td, sp=None):
        iqns = []
        if sp is not None:
            iqns.extend([tgt[0] for tgt in td.iscsi_targets[sp]])
        else:
            for r in ('a', 'b'):
                iqns.extend([tgt[0] for tgt in td.iscsi_targets[r]])
        return iqns

    @staticmethod
    def get_iscsi_portals(td, sp=None):
        portals = []
        if sp is not None:
            portals.extend(
                ['{}:3260'.format(tgt[1]) for tgt in td.iscsi_targets[sp]])
        else:
            for r in ('a', 'b'):
                portals.extend(
                    ['{}:3260'.format(tgt[1]) for tgt in td.iscsi_targets[r]])
        return portals

    lun_id_default = 'sv_1'
    lun_data_default = {'id': lun_id_default,
                        'name': 'volume-xxx',
                        'type': 2,
                        'pool': {'id': storage_pool_id_default},
                        'currentNode': 0,
                        'hostAccess': []}
    resp_create_lun = {'content': {'storageResource': {'id': lun_id_default}}}
    resp_create_lun_err = {'errorCode': 131149836, 'httpStatusCode': 405,
                           'messages': {'en-US': 'The action associated with \
                            the provided URL is not supported. \
                           (Error Code:0x7d1300c)'}}

    @staticmethod
    def req_create_lun(pool_id, name, size, is_thin):
        url = '/api/types/storageResource/action/createLun'
        body = {'lunParameters': {'isThinEnabled': is_thin,
                                  'pool': {'id': pool_id},
                                  'size': size},
                'name': name,
                'description': name}
        return mock.call(url, body)

    resp_delete_lun_ok = {}
    resp_resource_nonexistent = {
        'errorCode': 131149829, 'httpStatusCode': 404,
        'messages': [{'en-US':
                      'The requested resource does not exist.'
                      ' (Error Code:0x7d13005)'}],
    }
    resp_delete_lun_has_snap = {'errorCode': 100666391, 'httpStatusCode': 409,
                                'messages': {'en-US': 'The resource cannot be \
                                deleted because it has one or more snapshots. \
                                To delete the resource anyway, \
                                specify the force delete option. \
                                (Error Code:0x6000c17)'}}

    @staticmethod
    def req_delete_lun(lun_id, force_snap_deletion=False):
        url = '/api/instances/storageResource/' + lun_id
        body = {'forceSnapDeletion': force_snap_deletion}
        return mock.call(url, body, 'DELETE')

    @staticmethod
    def req_expose_lun(lun_id, host_ids, accesses):
        url = '/api/instances/storageResource/sv_1/action/modifyLun'
        body = {'lunParameters':
                {'hostAccess': [{'host': {'id': host_id},
                                 'accessMask': access}
                                for host_id, access in
                                zip(host_ids, accesses)]}}
        return mock.call(url, body)

    resp_get_lun_by_id_default = {
        'content': {'id': lun_id_default,
                    'currentNode': 0,
                    'defaultNode': 1,
                    'name': 'volume-x',
                    'pool': {'id': storage_pool_id_default},
                    'hostAccess': [],
                    'type': 2}}

    resp_get_lun_by_id_for_manage_exist = {
        'content': {'id': lun_id_default,
                    'currentNode': 0,
                    'defaultNode': 1,
                    'name': 'volume-x',
                    'pool': {'id': storage_pool_id_default},
                    'sizeTotal': 1073741824}}

    resp_get_lun_by_name_for_manage_exist = {
        'entries': [{
            'content':
                {'id': lun_id_default,
                 'currentNode': 0,
                 'defaultNode': 1,
                 'name': 'volume-x',
                 'pool': {'id': storage_pool_id_default},
                 'sizeTotal': 1073741824}}]}

    resp_get_lun_not_in_manage_pool = {
        'content': {'id': lun_id_default,
                    'currentNode': 0,
                    'defaultNode': 1,
                    'name': 'volume-x',
                    'pool': {'id': 'fakepoolid'},
                    'sizeTotal': 1073741824}}

    resp_get_lun_by_id_err = {
        "error": {"errorCode": 131149829,
                  "httpStatusCode": 404,
                  "messages": [{"en-US": "The requested resource \
                  does not exist. (Error Code:0x7d13005)"}],
                  "created": "2014-04-11T06:08:19.102Z"}}

    resp_hide_lun_error = {'errorCode': 100666391, 'httpStatusCode': 409,
                           'messages': {'en-US': 'Failed to hide volume \
                            from host. (Error Code:)'}}

    resp_modify_name_exist_error = {
        'errorCode': 108007456,
        'httpStatusCode': 422,
        'messages':
            [{'en-US': 'The user requested modification of '
                       'the storage resource but the system found that there '
                       'is nothing to modify. (Error Code:0x6701020)'}]}

    resp_modify_name_error = {'errorCode': 108007746,
                              'httpStatusCode': 422,
                              'messages':
                                  [{'en-US': 'fakeerror '}]}

    @staticmethod
    def req_get_lun_by_id(lun_id, fields=('id', 'type', 'name', 'currentNode',
                                          'hostAccess', 'pool')):
        url = '/api/instances/lun/%s' % lun_id
        if fields:
            url += (('?fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    @staticmethod
    def req_get_lun_by_name(name, fields=None):
        url = '/api/types/lun/instances?filter=%s' % \
              urllib2.quote('name eq "%s"' % name)
        url += (('&fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    @staticmethod
    def req_modify_lun_name(lun_id, new_name, fields=None):
        url = '/api/instances/storageResource/%s/action/modifyLun' % lun_id
        body = {'name': new_name}
        return mock.call(url, body)

    resp_get_fc_ports = {
        'entries': [
            {'content':
                {'id': 'spa_iom_0_fc0',
                 'wwn': '50:06:01:60:88:E0:00:1E:50:06:01:64:08:E0:00:1E',
                 'storageProcessor': {'id': 'spa'}}},
            {'content':
                {'id': 'spa_iom_0_fc1',
                 'wwn': '50:06:01:60:88:E0:00:1E:50:06:01:65:08:E0:00:1E',
                 'storageProcessor': {'id': 'spa'}}},
            {'content':
                {'id': 'spb_iom_0_fc0',
                 'wwn': '50:06:01:60:88:E0:00:1E:50:06:01:6C:08:E0:00:1E',
                 'storageProcessor': {'id': 'spb'}}},
            {'content':
                {'id': 'spb_iom_0_fc1',
                 'wwn': '50:06:01:60:88:E0:00:1E:50:06:01:6D:08:E0:00:1E',
                 'storageProcessor': {'id': 'spb'}}}]}

    n_resp_get_fc_ports = {
        'entries': [
            {'content':
                {'id': 'spa_iom_0_fc0',
                 'wwn': '50:06:01:60:88:E0:00:1E:50:06:01:64:08:E0:00:1F',
                 'storageProcessor': {'id': 'spa'}}},
            {'content':
                {'id': 'spa_iom_0_fc1',
                 'wwn': '50:06:01:60:88:E0:00:1E:50:06:01:65:08:E0:00:1F',
                 'storageProcessor': {'id': 'spa'}}},
            {'content':
                {'id': 'spb_iom_0_fc0',
                 'wwn': '50:06:01:60:88:E0:00:1E:50:06:01:6C:08:E0:00:1F',
                 'storageProcessor': {'id': 'spb'}}},
            {'content':
                {'id': 'spb_iom_0_fc1',
                 'wwn': '50:06:01:60:88:E0:00:1E:50:06:01:6D:08:E0:00:1F',
                 'storageProcessor': {'id': 'spb'}}}]}

    @staticmethod
    def req_get_fc_ports(fields):
        url = '/api/types/fcPort/instances'
        url += (('?fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    spa_iom_0_fc0 = ('5006016088E0001E', '5006016408E0001E',
                     'spa_iom_0_fc0')

    spa_iom_0_fc1 = ('5006016088E0001E', '5006016508E0001E',
                     'spa_iom_0_fc1')

    spb_iom_0_fc0 = ('5006016088E0001E', '5006016C08E0001E',
                     'spb_iom_0_fc0')

    spb_iom_0_fc1 = ('5006016088E0001E', '5006016D08E0001E',
                     'spb_iom_0_fc1')

    fc_targets = {'a': [spa_iom_0_fc0,
                        spa_iom_0_fc1],
                  'b': [spb_iom_0_fc0,
                        spb_iom_0_fc1]}

    n_spa_iom_0_fc0 = ('5006016088E0001E', '5006016408E0001F',
                       'spa_iom_0_fc0')

    n_spa_iom_0_fc1 = ('5006016088E0001E', '5006016508E0001F',
                       'spa_iom_0_fc1')

    n_spb_iom_0_fc0 = ('5006016088E0001E', '5006016C08E0001F',
                       'spb_iom_0_fc0')

    n_spb_iom_0_fc1 = ('5006016088E0001E', '5006016D08E0001F',
                       'spb_iom_0_fc1')

    n_fc_targets = {'a': [n_spa_iom_0_fc0,
                          n_spa_iom_0_fc1],
                    'b': [n_spb_iom_0_fc0,
                          n_spb_iom_0_fc1]}

    test_existing_ref = {'source-id': lun_id_default}
    os_vol_default = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': lun_id_default,
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'host': 'fakehost@fackbe#%s' % storage_pool_name_default,
        'provider_location': 'system^%(sys)s|type^%(type)s|id^%(id)s' %
                             {'sys': storage_serial_number_default,
                              'type': 'lun',
                              'id': lun_id_default}}

    os_vol_for_manage_existing = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'host': 'fakehost@fackbe#%s' % storage_pool_name_default,
        'provider_location': 'system^%(sys)s|type^%(type)s|id^%(id)s' %
                             {'sys': storage_serial_number_default,
                              'type': 'lun',
                              'id': lun_id_default}}

    os_vol_rw = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'host': 'fakehost@fackbe#%s' % storage_pool_name_default,
        'volume_admin_metadata': [{'key': 'attached_mode', 'value': 'rw'},
                                  {'key': 'readonly', 'value': 'False'}],
        'provider_location': 'system^%(sys)s|type^%(type)s|id^%(id)s' %
                             {'sys': storage_serial_number_default,
                              'type': 'lun',
                              'id': lun_id_default}}

    os_vol_ro = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'host': 'fakehost@fackbe#%s' % storage_pool_name_default,
        'volume_admin_metadata': [{'key': 'readonly', 'value': 'True'}],
        'provider_location': 'system^%(sys)s|type^%(type)s|id^%(id)s' %
                             {'sys': storage_serial_number_default,
                              'type': 'lun',
                              'id': lun_id_default}}

    os_vol_with_type = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': 'volume_type_id_xxx',
        'host': 'fakehost@fackbe#%s' % storage_pool_name_default,
        'provider_location': 'system^%(sys)s|type^%(type)s|id^%(id)s' %
                             {'sys': storage_serial_number_default,
                              'type': 'lun',
                              'id': lun_id_default}}

    iscsi_initiator_iqn_default = 'iqn.1993-08.org.debian:01:ee4a92e19d0'
    fc_initator_node_wwn1 = '12:34:56:78:90:AB:CD:E1'
    fc_initator_node_wwn2 = '12:34:56:78:90:AB:CD:E2'
    fc_initator_port_wwn1 = '12:34:56:78:90:AB:CD:E1'
    fc_initator_port_wwn2 = '12:34:56:78:90:AB:CD:E2'
    fc_initator_wwn1 = ':'.join((fc_initator_node_wwn1,
                                 fc_initator_port_wwn1))
    fc_initator_wwn2 = ':'.join((fc_initator_node_wwn2,
                                 fc_initator_port_wwn2))
    os_connector_default = {
        'initiator': iscsi_initiator_iqn_default,
        'ip': '10.0.0.161',
        'host': 'openstack-161',
        'wwnns': [fc_initator_node_wwn1.lower().replace(':', ''),
                  fc_initator_node_wwn2.lower().replace(':', '')],
        'wwpns': [fc_initator_port_wwn1.lower().replace(':', ''),
                  fc_initator_port_wwn2.lower().replace(':', '')]}
    os_connector_missing_host = {
        'initiator': iscsi_initiator_iqn_default,
        'ip': '10.0.0.161',
        'host': '',
        'wwnns': [fc_initator_node_wwn1.lower().replace(':', ''),
                  fc_initator_node_wwn2.lower().replace(':', '')],
        'wwpns': [fc_initator_port_wwn1.lower().replace(':', ''),
                  fc_initator_port_wwn2.lower().replace(':', '')]}
    mapping = {
        "test": {
            'initiator_port_wwn_list':
                os_connector_default['wwpns'],
            'target_port_wwn_list':
                [spa_iom_0_fc0[1], spb_iom_0_fc0[1],
                 spa_iom_0_fc1[1], spb_iom_0_fc1[1]]}}

    host_name_default = "openstack-161"
    host_id_default = 'Host_1'
    resp_get_initiator_by_uid_empty = {
        'entries': []}

    resp_get_initiator_by_uid_iscsi_default = {
        'entries': [
            {'content':
                {'id': 'HostInitiator_11',
                 'initiatorId': iscsi_initiator_iqn_default,
                 'parentHost': {'id': host_id_default}}}]}

    resp_get_initiator_by_uid_fc_default = {
        'entries': [
            {'content':
                {'id': 'HostInitiator_21',
                 'initiatorId': fc_initator_wwn1,
                 'parentHost': {'id': host_id_default}}},
            {'content':
                {'id': 'HostInitiator_22',
                 'initiatorId': fc_initator_wwn2,
                 'parentHost': {'id': host_id_default}}}]}

    resp_get_initiator_by_uid_iscsi_orphan = {
        'entries': [
            {'content':
                {'id': 'HostInitiator_11',
                 'initiatorId': iscsi_initiator_iqn_default}}]}

    @staticmethod
    def req_get_host_by_name(hostname, fields=None):
        url = '/api/types/host/instances?filter=%s' % \
              urllib2.quote('name eq "%s"' % hostname)
        url += (('&fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    resp_get_host_by_name_default = {
        'entries': [
            {'content':
                {'id': 'Host_1'}}]}

    @staticmethod
    def resp_get_host_by_name(host_id):
        return {
            "entries": [{
                "content": {
                    "address": "test",
                    "name": "test",
                    "id": host_id,
                    "type": 1,
                    "storageResources": [],
                    "vms": [],
                    "hostIPPorts": [],
                    "hostLUNs": []
                }
            }]
        }

    resq_get_host_unexist = {"entryCount": 0,
                             "entries": []}

    @staticmethod
    def req_create_host(hostname):
        url = '/api/types/host/instances'
        body = {'type': EMCUnityRESTClient.HostTypeEnum_HostManual,
                'name': hostname}
        return mock.call(url, body)

    resp_create_host_default = {
        'content': {'id': host_id_default}}

    @staticmethod
    def resp_create_host(hostid):
        return {"content": {
            "id": hostid}}

    @staticmethod
    def req_register_initiators(initiator_id, host_id):
        url = '/api/instances/hostInitiator/%s/action/modify' % initiator_id
        body = {'host': {'id': host_id}}
        return mock.call(url, body)

    @staticmethod
    def req_create_initiators(initiator_uid, host_id):
        url = '/api/types/hostInitiator/instances'
        body = {'host': {'id': host_id},
                'initiatorType': 2 if initiator_uid.lower().find('iqn') == 0
                else 1,
                'initiatorWWNorIqn': initiator_uid}
        return mock.call(url, body)

    resp_create_initiators = {
        'content': {'id': 'HostInitiator_21'}}

    @staticmethod
    def req_get_initiator_by_uid(uid, fields=None):
        url = '/api/types/hostInitiator/instances?filter=%s' % \
              urllib2.quote('initiatorId eq "%s"' % uid)
        url += (('&fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    resp_get_initiator_by_uid_fc_wwn1 = {
        'entries': [{
            'content': {
                'id': 'HostInitiator_21',
                'initiatorId': fc_initator_wwn1,
                'parentHost': {'id': host_id_default}}}]}

    resp_get_initiator_by_uid_fc_wwn2 = {
        'entries': [
            {'content': {
                'id': 'HostInitiator_22',
                'initiatorId': fc_initator_wwn2,
                'parentHost': {'id': host_id_default}}}]}

    hlu_default = 1
    resp_get_host_lun_by_ends_default = {
        'entries': [
            {'content':
                {'id': '_'.join((host_id_default, lun_id_default, 'prod')),
                 'hlu': hlu_default}}]}
    resp_get_host_lun_by_ends_none = {
        'entries': []}

    @staticmethod
    def req_get_host_lun_by_ends(host_id, lun_id, use_type, fields):
        url = '/api/types/hostLUN/instances?filter=%s' % \
              urllib2.quote('id lk "%%%(host)s_%(lun)s%%" and '
                            'type eq "%(type)s"'
                            % {'host': host_id,
                               'lun': lun_id,
                               'type': use_type})
        url += (('&fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    @staticmethod
    def req_get_host_by_id(hostid, fields=None):
        url = '/api/instances/host/%s' % hostid
        url += (('?fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    resp_get_host_by_id = {
        "content": {
            "address": "fake.addr.com",
            "name": host_name_default,
            "id": host_id_default,
            "type": 5,
            "storageResources": [],
            "vms": [],
            "hostIPPorts": [],
            "hostLUNs": [],
            "fcHostInitiators": [{"id": "HostInitiator_21"},
                                 {"id": "HostInitiator_22"}],
            "iscsiHostInitiators": []}}

    @staticmethod
    def req_create_initiator_fc(initiator_uid, host_id):
        url = '/api/types/hostInitiator/instances'
        body = {'host': {'id': host_id},
                'initiatorType': 1,
                'initiatorWWNorIqn': initiator_uid}
        return mock.call(url, body)

    @staticmethod
    def resp_create_initiator_fc(initiator_id):
        return {"content": {"id": initiator_id}}

    @staticmethod
    def req_get_initiator_paths_by_initiator_id(initiator_id, fields):
        url = '/api/types/hostInitiatorPath/instances?filter=%s' % \
              urllib2.quote('id lk "%s%%"' % initiator_id)
        url += (('&fields=%s' % ','.join(fields)) if fields else "")
        return mock.call(url)

    @staticmethod
    def resp_get_initiator_paths_by_initiator_id_fc(
            initiator_id, isLoggedin=True, port=spa_iom_0_fc1):
        return {'entries': [{"content": {
            "id": initiator_id + "_02%3A00%3A00%3A05",
            "fcPort": {"id": port[2]},
            "hostUUID": "5188d80b-f71b-d2f4-9396-0025b5500001",
            "registrationType": 1,
            "isLoggedIn": isLoggedin,
            "hostPushName": "nc9083201.drm.lab.emc.com",
            "sessionIds": ["128585"],
            "initiator": {"id": initiator_id}}}]}

    resp_get_initiator_paths_by_initiator_id_no_path_fc = \
        {'entries': []}

    @staticmethod
    def req_register_initiator(initiator_id, host_id):
        url = '/api/instances/hostInitiator/%s/action/modify' % initiator_id
        body = {'host': {'id': host_id}}
        return mock.call(url, body)

    resp_register_initiator = {"entryCount": 0,
                               "entries": []}

    @staticmethod
    def req_hide_lun(lun_id, host_access_list):
        url = '/api/instances/storageResource/%s/action/modifyLun' % \
              lun_id
        body = {'lunParameters': {'hostAccess': host_access_list}}
        return mock.call(url, body)

    connection_info_fc_default = {
        'driver_volume_type': 'fibre_channel',
        'data': {
            'target_discovered': True,
            'target_lun': hlu_default,
            'volume_id': os_vol_default['id'],
            'target_wwn': ['5006016508E0001E']}
    }

    @staticmethod
    def connection_info_fc(accessible_targets):
        return {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_discovered': True,
                'target_lun': TD.hlu_default,
                'volume_id': TD.os_vol_default['id'],
                'target_wwn': map(lambda entry: entry[1],
                                  accessible_targets)
            }
        }

    @staticmethod
    def connection_info_fc_auto_zoning(target_wwn, init_map):
        return {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_discovered': True,
                'target_lun': TD.hlu_default,
                'volume_id': TD.os_vol_default['id'],
                'target_wwn': target_wwn,
                'initiator_target_map': init_map
            }
        }

    @staticmethod
    def req_extend_lun(lun_id, size):
        url = '/api/instances/storageResource/%s/action/modifyLun' % lun_id
        body = {'lunParameters': {'size': size}}
        return mock.call(url, body)

    HostLUNAccessEnum_Production = \
        EMCUnityRESTClient.HostLUNAccessEnum_Production
    HostLUNAccessEnum_NoAccess = \
        EMCUnityRESTClient.HostLUNAccessEnum_NoAccess
    HostLUNTypeEnum_LUN = EMCUnityRESTClient.HostLUNTypeEnum_LUN

    ###############################################
    # Test data to run the cg related unit test
    ###############################################
    test_cgsnapshot = {
        'consistencygroup_id': 'consistencygroup_id',
        'id': 'cgsnapshot_id',
        'status': 'available',
        'description': 'test_cgsnapshot'}

    test_cg = {
        'availability_zone': 'nova',
        'cgsnapshot_id': None,
        'created_at': None,
        'deleted': False,
        'deleted_at': None,
        'description': None,
        'host': "FakeHost",
        'id': '1',
        'name': None,
        'project_id': '3',
        'source_cgid': None,
        'status': "deleting",
        'updated_at': None,
        'user_id': '2',
        'volume_type_id': None}

    @staticmethod
    def volumes_in_group(count=1):
        volumes = []
        for i in range(count):
            volumes.append(TD.os_vol_default)
        return volumes

    ###############################################
    # Test data to run the snap related unit test
    ###############################################
    test_vol_for_snapshot = {
        'name': 'snapshot1',
        'size': 1,
        'id': '4444',
        'volume_name': 'vol1',
        'volume_size': 1,
        'project_id': 'project',
        'display_description': 'snapshot test',
        'volume': {'provider_location': 'type^lun|system^BC-H1166-spb|id^sv_1',
                   'name': 'volume-name'}}

    test_snapshot_data = {
        'name': 'snapshot1',
        'size': 1,
        'id': '4444',
        'volume_name': 'vol1',
        'volume_size': 1,
        'project_id': 'project',
        'display_description': 'snapshot test',
        'provider_location': 'type^lun|system^BC-H1166-spb|id^12345678'}

    test_snapshot_with_invalid_id = {
        'name': 'snapshot1',
        'size': 1,
        'id': '4444',
        'volume_name': 'vol1',
        'volume_size': 1,
        'project_id': 'project',
        'display_description': 'snapshot test',
        'volume': {'provider_location': 'type^lun|system^BC-H1166-spb|id^',
                   'name': 'volume-name'}}

    resp_create_snap = {'content': {'id': '12345678'}}
    fake_error_return = \
        {"errorCode": 131149825,
         "httpStatusCode": 500,
         "messages":
             [{"en-US": "The system encountered an unexpected error. Record "
                        "the error and go to 'Support > Need more help? > "
                        "Live Chat to chat with EMC support personnel. "
                        "If this option is not available, contact your service"
                        " provider. (Error Code:0x7d13001)"}],
         "created": "2014-05-19T06:18:04.525Z"}

    @staticmethod
    def req_create_consistencygroup(group_id, group_desc=None):
        url = '/api/types/storageResource/action/createLunGroup'
        resp_create_group = {'name': group_id}
        if group_desc:
            resp_create_group['description'] = group_desc
        return mock.call(url, resp_create_group)

    @staticmethod
    def req_delete_consistencygroup(group_id, force_snap_deletion=False):
        cg_delete_url = '/api/instances/storageResource/%s' % group_id
        data = {'forceSnapDeletion': force_snap_deletion}
        return mock.call(cg_delete_url, data, 'DELETE')

    @staticmethod
    def req_get_group_by_name(group_name, fields=None):
        url = '/api/types/storageResource/instances?filter=name%20eq%20%22' \
              + group_name + '%22&fields=id'
        return mock.call(url)

    @staticmethod
    def req_get_snap_by_name(snap_name, fields=None):
        url = '/api/types/snap/instances?filter=name%20eq%20%22' \
              + snap_name + '%22&fields=id'
        return mock.call(url)

    @staticmethod
    def req_update_consistencygroup(group_id, add_luns, remove_luns):
        url = '/api/instances/storageResource/%s/action/modifyLunGroup' \
              % group_id
        add_data = [{"lun": {"id": add_id}}
                    for add_id in add_luns] if add_luns else []
        remove_data = [{"lun": {"id": remove_id}}
                       for remove_id in remove_luns] if remove_luns else []
        req_data = {'lunAdd': add_data,
                    'lunRemove': remove_data}
        return mock.call(url, req_data)

    resp_create_consistencygroup = {
        'content': {'storageResource': {'id': 'res_1'}}}
    resp_get_group_by_name = {'entries': [{'content': {'id': 'res_1'}}]}
    resp_update_consistencygroup = {}

    @staticmethod
    def req_create_snap(lun_id, snap_name, snap_desc=None):
        url = '/api/types/snap/instances'
        resp_create_snap = {'storageResource': {'id': lun_id},
                            'name': snap_name}
        if snap_desc:
            resp_create_snap['description'] = snap_desc
        return mock.call(url, resp_create_snap)

    @staticmethod
    def req_delete_snap(snap_id):
        delete_snap_url = '/api/instances/snap/%s' % snap_id
        return mock.call(delete_snap_url, None, 'DELETE')

    @staticmethod
    def req_get_pools(fields):
        get_pools_url = ('/api/types/pool/instances?'
                         'fields=%s' % ','.join(fields))
        return mock.call(get_pools_url)

    resp_get_pools = {
        'entries': [
            {'content': {'id': storage_pool_id_default,
                         'name': storage_pool_name_default,
                         'sizeTotal': 28185722880,
                         'sizeFree': 17985175552,
                         'sizeSubscribed': 10185722880}},
            {'content': {'id': 'pool_2',
                         'name': 'StoragePool01',
                         'sizeTotal': 28185722880,
                         'sizeFree': 17985175552,
                         'sizeSubscribed': 10185722880}}]}

    new_resp_get_pools = {
        'entries': [
            {'content': {'id': storage_pool_id_default,
                         'name': storage_pool_name_default,
                         'sizeTotal': 2147483678,
                         'sizeFree': 1073741824,
                         'sizeSubscribed': 10185722880}},
            {'content': {'id': 'pool_2',
                         'name': 'StoragePool01',
                         'sizeTotal': 28185722880,
                         'sizeFree': 17985175552,
                         'sizeSubscribed': 10185722880}}]}

    @staticmethod
    def req_get_licenses(fields):
        get_licenses_url = ('/api/types/license/instances?'
                            'fields=%s' % ','.join(fields))
        return mock.call(get_licenses_url)

    resp_get_licenses = {
        'entries': [
            {'content': {'id': 'VNXE_PROVISION',
                         'isValid': True}},
            {'content': {'id': 'SNAP',
                         'isValid': True}}]}


TD = EMCUnityDriverTestData


class RequestSideEffect(object):
    def __init__(self):
        self.actions = []
        self.started = False

    def append(self, err=None, resp=None, ex=None):
        if not self.started:
            self.actions.append((err, resp, ex))

    def __call__(self, rel_url, req_data=None, method=None,
                 *args, **kwargs):
        if not self.started:
            self.started = True
            self.actions.reverse()
        item = self.actions.pop()
        if item[2]:
            raise item[2]
        else:
            return item[0:2]


class EMCUnityDriverTestCase(test.TestCase):
    def setUp(self):
        super(EMCUnityDriverTestCase, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.san_ip = '10.0.0.1'
        conf_safe_get_map = {
            'storage_pool_names': TD.storage_pool_name_default,
            'zoning_mode': None}
        self.configuration.safe_get = mock.Mock(
            side_effect=lambda a: conf_safe_get_map[a]
            if a in conf_safe_get_map else None)
        self.configuration.san_login = 'sysadmin'
        self.configuration.san_password = 'sysadmin'
        self.driver = None

    @staticmethod
    def load_provider_location(provider_location):
        pl_dict = {}
        for item in provider_location.split('|'):
            k_v = item.split('^')
            if len(k_v) == 2 and k_v[0]:
                pl_dict[k_v[0]] = k_v[1]
        return pl_dict


class EMCUnityiSCSIDriverTestCase(EMCUnityDriverTestCase):
    def setUp(self):
        super(EMCUnityiSCSIDriverTestCase, self).setUp()
        self.configuration.storage_protocol = 'iSCSI'
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_basic_system_info)
        hook.append(None, TD.resp_get_pools)
        hook.append(None, TD.resp_get_iscsi_nodes)
        hook.append(None, TD.resp_get_get_iscsi_portals)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver = EMCUnityDriver(configuration=self.configuration)
        expected_calls = [
            TD.req_get_basic_system_info(('name', 'softwareVersion')),
            TD.req_get_pools(('name', 'id')),
            TD.req_get_get_iscsi_nodes(('id', 'name')),
            TD.req_get_get_iscsi_portals(('id', 'ipAddress',
                                          'ethernetPort', 'iscsiNode'))]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_basic_info(self):
        self.assertEqual(self.driver.helper.storage_serial_number,
                         TD.storage_serial_number_default)
        self.assertEqual(False, self.driver.helper.is_managing_all_pools)
        self.assertEqual({
            TD.storage_pool_name_default: TD.storage_pool_id_default},
            self.driver.helper.storage_pools_map)

    def test_iscsi_targets(self):
        self.assertDictMatch(self.driver.helper.storage_targets,
                             TD.iscsi_targets)

    def test_create_consistencygroup_default(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_create_consistencygroup)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        cg_obj = fake_consistencygroup.fake_consistencyobject_obj(
            None, **TD.test_cg)
        model_update = self.driver.create_consistencygroup(None, cg_obj)
        expected_calls = [
            TD.req_create_consistencygroup(cg_obj.id)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)
        self.assertTrue(model_update['status'] is 'available')

    def test_create_consistencygroup_failed(self):
        hook = RequestSideEffect()
        hook.append(TD.fake_error_return)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        cg_obj = fake_consistencygroup.fake_consistencyobject_obj(
            None, **TD.test_cg)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*The system encountered an '
                                'unexpected error*',
                                self.driver.create_consistencygroup,
                                None, cg_obj)
        expected_calls = [
            TD.req_create_consistencygroup(cg_obj.id)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_delete_consistencygroup_default(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_group_by_name)
        hook.append()
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.db = mock.MagicMock()
        self.driver.db.volume_get_all_by_group.return_value = \
            TD.volumes_in_group(2)
        cg_obj = fake_consistencygroup.fake_consistencyobject_obj(
            None, **TD.test_cg)
        model_update, volumes = \
            self.driver.delete_consistencygroup(None, cg_obj)
        expected_calls = [TD.req_get_group_by_name(cg_obj.id),
                          TD.req_delete_consistencygroup('res_1')]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)
        for volume in volumes:
            self.assertTrue(volume['status'] is 'deleted')

    def test_delete_consistencygroup_failed(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_group_by_name)
        hook.append(TD.fake_error_return)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.db = mock.MagicMock()
        self.driver.db.volume_get_all_by_group.return_value = \
            TD.volumes_in_group(2)
        cg_obj = fake_consistencygroup.fake_consistencyobject_obj(
            None, **TD.test_cg)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*The system encountered '
                                'an unexpected error*',
                                self.driver.delete_consistencygroup,
                                None, cg_obj)
        expected_calls = [TD.req_get_group_by_name(cg_obj.id),
                          TD.req_delete_consistencygroup('res_1')]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_update_consistencygroup_default(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_group_by_name)
        hook.append(None, TD.resp_update_consistencygroup)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        cg_obj = fake_consistencygroup.fake_consistencyobject_obj(
            None, **TD.test_cg)
        model_update = \
            self.driver.update_consistencygroup(
                None, cg_obj, TD.volumes_in_group(2),
                TD.volumes_in_group(2))
        expected_calls = [TD.req_get_group_by_name(cg_obj.id),
                          TD.req_update_consistencygroup(
                              'res_1', ['sv_1', 'sv_1'], ['sv_1', 'sv_1'])]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)
        self.assertTrue(model_update[0]['status'] is 'available')

    def test_update_consistencygroup_failed(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_group_by_name)
        hook.append(TD.fake_error_return)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        cg_obj = fake_consistencygroup.fake_consistencyobject_obj(
            None, **TD.test_cg)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*The system encountered '
                                'an unexpected error*',
                                self.driver.update_consistencygroup,
                                None, cg_obj, TD.volumes_in_group(2),
                                TD.volumes_in_group(2))
        expected_calls = [TD.req_get_group_by_name(TD.test_cg['id']),
                          TD.req_update_consistencygroup(
                              'res_1', ['sv_1', 'sv_1'], ['sv_1', 'sv_1'])]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    @mock.patch(
        'cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_create_cgsnapshot_default(self, get_all_for_cgsnapshot):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_group_by_name)
        hook.append(None, TD.resp_create_snap)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        snapshot_obj = fake_snapshot.fake_snapshot_obj([TD.test_cgsnapshot,
                                                        TD.test_cgsnapshot])
        snapshot_obj.consistencygroup_id = \
            TD.test_cgsnapshot['consistencygroup_id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]
        model_update, snapshots = \
            self.driver.create_cgsnapshot(None, TD.test_cgsnapshot)
        expected_calls = [TD.req_get_group_by_name('consistencygroup_id'),
                          TD.req_create_snap('res_1', 'cgsnapshot_id',
                                             'test_cgsnapshot')]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    @mock.patch(
        'cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_create_cgsnapshot_failed(self, get_all_for_cgsnapshot):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_group_by_name)
        hook.append(TD.fake_error_return)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        snapshot_obj = fake_snapshot.fake_snapshot_obj([TD.test_cgsnapshot,
                                                        TD.test_cgsnapshot])
        snapshot_obj.consistencygroup_id = \
            TD.test_cgsnapshot['consistencygroup_id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*The system encountered '
                                'an unexpected error*',
                                self.driver.create_cgsnapshot,
                                None, TD.test_cgsnapshot)
        expected_calls = [TD.req_get_group_by_name('consistencygroup_id'),
                          TD.req_create_snap('res_1', 'cgsnapshot_id',
                                             'test_cgsnapshot')]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    @mock.patch(
        'cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_delete_cgsnapshot_default(self, get_all_for_cgsnapshot):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_group_by_name)
        hook.append(None, {})
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        snapshot_obj = fake_snapshot.fake_snapshot_obj([TD.test_cgsnapshot,
                                                        TD.test_cgsnapshot])
        snapshot_obj.consistencygroup_id = \
            TD.test_cgsnapshot['consistencygroup_id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]
        model_update, snapshots = \
            self.driver.delete_cgsnapshot(None, TD.test_cgsnapshot)
        expected_calls = [TD.req_get_snap_by_name('cgsnapshot_id'),
                          TD.req_delete_snap('res_1')]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    @mock.patch(
        'cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_delete_cgsnapshot_failed(self, get_all_for_cgsnapshot):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_group_by_name)
        hook.append(TD.fake_error_return)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        snapshot_obj = fake_snapshot.fake_snapshot_obj([TD.test_cgsnapshot,
                                                        TD.test_cgsnapshot])
        snapshot_obj.consistencygroup_id = \
            TD.test_cgsnapshot['consistencygroup_id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*The system encountered '
                                'an unexpected error*',
                                self.driver.delete_cgsnapshot,
                                None, TD.test_cgsnapshot)
        expected_calls = [TD.req_get_snap_by_name('cgsnapshot_id'),
                          TD.req_delete_snap('res_1')]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_create_volume_default(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_create_lun)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        model_update = self.driver.create_volume(TD.os_vol_default)
        expected_calls = [
            TD.req_create_lun(TD.storage_pool_id_default,
                              TD.os_vol_default['name'],
                              TD.os_vol_default['size'] * GiB,
                              False)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)
        self.assertTrue('provider_location' in model_update)
        pl_dict = self.load_provider_location(
            model_update['provider_location'])
        self.assertDictMatch(pl_dict,
                             {'system': TD.storage_serial_number_default,
                              'type': 'lun',
                              'id': TD.lun_id_default})

    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs',
                mock.Mock(return_value={'storagetype:provisioning': 'Thin'}))
    def test_create_volume_explicit_thin(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_create_lun)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.create_volume(TD.os_vol_with_type)
        volume_types.get_volume_type_extra_specs.assert_has_calls(
            [mock.call(TD.os_vol_with_type['volume_type_id'])])
        expected_calls = [
            TD.req_create_lun(TD.storage_pool_id_default,
                              TD.os_vol_default['name'],
                              TD.os_vol_default['size'] * GiB,
                              True)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs',
                mock.Mock(return_value={'storagetype:provisioning': 'Thick'}))
    def test_create_volume_explicit_thick(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_create_lun)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.create_volume(TD.os_vol_with_type)
        volume_types.get_volume_type_extra_specs.assert_has_calls(
            [mock.call(TD.os_vol_with_type['volume_type_id'])])
        expected_calls = [
            TD.req_create_lun(TD.storage_pool_id_default,
                              TD.os_vol_default['name'],
                              TD.os_vol_default['size'] * GiB,
                              False)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_create_volume_into_cg(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_create_lun)
        hook.append(None, TD.resp_get_group_by_name)
        hook.append(None, TD.resp_update_consistencygroup)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.create_volume(TD.os_vol_default)
        expected_calls = [
            TD.req_create_lun(TD.storage_pool_id_default,
                              TD.os_vol_default['name'],
                              TD.os_vol_default['size'] * GiB,
                              False)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs',
                mock.Mock(return_value={
                    'storagetype:provisioning': 'Invalid'}))
    def test_create_volume_explicit_invalid(self):
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*storagetype:provisioning.*invalid.*',
                                self.driver.create_volume,
                                TD.os_vol_with_type)

    def test_create_volume_failed(self):
        hook = RequestSideEffect()
        hook.append(TD.resp_create_lun_err, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        error_except = None
        model_update = None
        try:
            model_update = self.driver.create_volume(TD.os_vol_default)
        except exception.VolumeBackendAPIException as ex:
            error_except = ex
            expected_calls = [
                TD.req_create_lun(TD.storage_pool_id_default,
                                  TD.os_vol_default['name'],
                                  TD.os_vol_default['size'] * GiB,
                                  False)]
            EMCUnityRESTClient._request.assert_has_calls(expected_calls)
            self.assertTrue(model_update is None)
            self.assertTrue('0x7d1300c' not in
                            TD.resp_create_lun_err['messages'])

        self.assertTrue(error_except is not None)

    def test_delete_volume_default(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_delete_lun_ok)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.delete_volume(TD.os_vol_default)
        expected_calls = [
            TD.req_delete_lun(TD.lun_id_default,
                              False)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_delete_volume_missing(self):
        hook = RequestSideEffect()
        hook.append(TD.resp_resource_nonexistent)
        hook.append(TD.resp_get_lun_by_id_err)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.delete_volume(TD.os_vol_default)
        expected_calls = [
            TD.req_delete_lun(TD.lun_id_default),
            TD.req_get_lun_by_id(TD.lun_id_default, None)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_delete_volume_failed(self):
        hook = RequestSideEffect()
        hook.append(TD.resp_delete_lun_has_snap, None)
        hook.append(None, TD.resp_get_lun_by_id_default)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*Error Code:0x6000c17.*',
                                self.driver.delete_volume,
                                TD.os_vol_default)

        expected_calls = [
            TD.req_delete_lun(TD.lun_id_default, False),
            TD.req_get_lun_by_id(TD.lun_id_default, None)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_create_snapshot(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_create_snap)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.create_snapshot(TD.test_vol_for_snapshot)
        expected_calls = [
            TD.req_create_snap('sv_1', 'snapshot1', 'snapshot test')]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_create_snapshot_with_invalid_volume(self):
        """Test case for create a snapshot with an invalid volume."""
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*Fail to find LUN ID of volume-name*',
                                self.driver.create_snapshot,
                                TD.test_snapshot_with_invalid_id)

    def test_create_snapshot_failed(self):
        """Test case for create a snapshot failed."""
        hook = RequestSideEffect()
        hook.append(TD.fake_error_return)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*The system encountered an '
                                'unexpected error*',
                                self.driver.create_snapshot,
                                TD.test_vol_for_snapshot)
        expected_calls = [
            TD.req_create_snap('sv_1', 'snapshot1', 'snapshot test')]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_delete_snapshot_default(self):
        """Test case for delete a unity snapshot."""
        hook = RequestSideEffect()
        hook.append(None, {})
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.delete_snapshot(TD.test_snapshot_data)
        expected_calls = [TD.req_delete_snap('12345678')]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_delele_snapshot_failed(self):
        """Test case for delete a snapshot with failure."""
        hook = RequestSideEffect()
        hook.append(TD.fake_error_return)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*The system encountered '
                                'an unexpected error*',
                                self.driver.delete_snapshot,
                                TD.test_snapshot_data)
        expected_calls = [
            TD.req_delete_snap('12345678')]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_extend_volume(self):
        hook = RequestSideEffect()
        hook.append(None, None)

        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.extend_volume(TD.os_vol_default,
                                  2)
        expected_calls = [
            TD.req_extend_lun(TD.lun_id_default, 2 * GiB)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_extend_volume_unchanged(self):
        err = {'errorCode': 108007456,
               'httpStatusCode': 422,
               'messages': {'en-US': "The user \
                            requested modification of the storage \
                            resource but the system found that \
                            there is nothing to modify."}}
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(err, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.extend_volume(TD.os_vol_default, 1)
        expected_calls = [
            TD.req_extend_lun(TD.lun_id_default, 1 * GiB)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_extend_volume_failed(self):
        err = {'errorCode': 108007728,
               'httpStatusCode': 405,
               'messages': "The system does not support shrink operation"}
        hook = RequestSideEffect()
        hook.append(err, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*does not support shrink operation',
                                self.driver.extend_volume,
                                TD.os_vol_default,
                                2)
        expected_calls = [
            TD.req_extend_lun(TD.lun_id_default, 2 * GiB)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_initialize_connection_default(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_default)
        hook.append(None, None)
        hook.append(None, TD.resp_get_host_lun_by_ends_default)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        conn_info = self.driver.initialize_connection(
            TD.os_vol_default, TD.os_connector_default)
        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_get_initiator_by_uid(TD.iscsi_initiator_iqn_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_Production,)),
            TD.req_get_host_lun_by_ends(TD.host_id_default,
                                        TD.lun_id_default,
                                        TD.HostLUNTypeEnum_LUN, ('hlu',))]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)
        self.assertDictMatch(conn_info['data'],
                             {'target_luns': [TD.hlu_default, TD.hlu_default],
                              'target_iqns': TD.get_iscsi_iqns(TD),
                              'target_portals': TD.get_iscsi_portals(TD),
                              'target_discovered': True,
                              'target_iqn': TD.get_iscsi_iqns(TD, 'a')[0],
                              'target_portal':
                                  TD.get_iscsi_portals(TD, 'a')[0],
                              'volume_id': TD.lun_id_default,
                              'target_lun': TD.hlu_default})

    def test_initialize_connection_missing_host_with_orphan(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_orphan)
        hook.append(1, None)
        hook.append(None, TD.resp_create_host_default)
        hook.append(None, None)
        hook.append(None, None)
        hook.append(None, TD.resp_get_host_lun_by_ends_default)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.initialize_connection(TD.os_vol_default,
                                          TD.os_connector_default)
        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_get_initiator_by_uid(TD.iscsi_initiator_iqn_default),
            TD.req_get_host_by_name(TD.os_connector_default['host'], ('id',)),
            TD.req_create_host(TD.os_connector_default['host']),
            TD.req_register_initiators('HostInitiator_11',
                                       TD.host_id_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_Production,)),
            TD.req_get_host_lun_by_ends(TD.host_id_default,
                                        TD.lun_id_default,
                                        TD.HostLUNTypeEnum_LUN, ('hlu',))]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_initialize_connection_unchanged(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_default)
        hook.append({'errorCode': 0x6701020}, None)
        hook.append(None, TD.resp_get_host_lun_by_ends_default)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.initialize_connection(TD.os_vol_default,
                                          TD.os_connector_default)
        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_get_initiator_by_uid(TD.iscsi_initiator_iqn_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_Production,)),
            TD.req_get_host_lun_by_ends(TD.host_id_default,
                                        TD.lun_id_default,
                                        TD.HostLUNTypeEnum_LUN, ('hlu',))]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_initialize_connection_failed_exposing(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_default)
        hook.append({'errorCode': 1}, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'Failed to expose.*to.*',
                                self.driver.initialize_connection,
                                TD.os_vol_default,
                                TD.os_connector_default)

    def test_initialize_connection_failed_conn_info(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_default)
        hook.append(None, None)
        hook.append(1, None)
        hook.append(None, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'Can not get the hlu information of host',
                                self.driver.initialize_connection,
                                TD.os_vol_default,
                                TD.os_connector_default)

    def test_initialize_connection_failed_get_host_lun(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_default)
        hook.append(None, None)
        hook.append(None, TD.resp_get_host_lun_by_ends_none)
        hook.append(None, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'Can not get the hlu information of host',
                                self.driver.initialize_connection,
                                TD.os_vol_default,
                                TD.os_connector_default)

    def test_initiatilze_connection_with_new(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(1, None)
        hook.append(None, TD.resp_get_host_by_name_default)
        hook.append(None, TD.resp_create_initiators)
        hook.append(None, None)
        hook.append(None, TD.resp_get_host_lun_by_ends_default)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.initialize_connection(TD.os_vol_default,
                                          TD.os_connector_default)
        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_get_initiator_by_uid(TD.iscsi_initiator_iqn_default),
            TD.req_get_host_by_name(TD.os_connector_default['host'], ('id',)),
            TD.req_create_initiators(TD.iscsi_initiator_iqn_default,
                                     TD.host_id_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_Production,)),
            TD.req_get_host_lun_by_ends(TD.host_id_default,
                                        TD.lun_id_default,
                                        TD.HostLUNTypeEnum_LUN, ('hlu',))]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_terminate_connection_default_registered_initiator(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_default)
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None, None)

        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.terminate_connection(TD.os_vol_default,
                                         TD.os_connector_default)
        expected_calls = [
            TD.req_get_initiator_by_uid(TD.iscsi_initiator_iqn_default),
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_NoAccess,)),  # hide
        ]

        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_terminate_connection_default_orphan_initiator(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_orphan)
        hook.append(None, TD.resp_get_host_by_name_default)
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None, None)

        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.terminate_connection(TD.os_vol_default,
                                         TD.os_connector_default)
        expected_calls = [
            TD.req_get_initiator_by_uid(TD.iscsi_initiator_iqn_default),
            TD.req_get_host_by_name(TD.os_connector_default['host'], ('id',)),
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_NoAccess,)),
        ]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_terminate_connection_missing_host(self):
        hook = RequestSideEffect()

        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_orphan)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.terminate_connection(TD.os_vol_default,
                                         TD.os_connector_missing_host)
        expected_calls = [
            TD.req_get_initiator_by_uid(TD.iscsi_initiator_iqn_default),
        ]

        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_terminate_connection_missing_lun(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_default)
        hook.append(TD.resp_get_lun_by_id_err, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                ('Cannot find lun with id : %s' %
                                 TD.lun_id_default),
                                self.driver.terminate_connection,
                                TD.os_vol_default,
                                TD.os_connector_default)
        expected_calls = [
            TD.req_get_initiator_by_uid(TD.iscsi_initiator_iqn_default),
            TD.req_get_lun_by_id(TD.lun_id_default),
        ]

        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_terminate_connection_failed(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_initiator_by_uid_iscsi_default)
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(TD.resp_hide_lun_error, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)

        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*Failed.*to.*hide.*volume.*from.*host.*',
                                self.driver.terminate_connection,
                                TD.os_vol_default,
                                TD.os_connector_default)

        expected_calls = [
            TD.req_get_initiator_by_uid(TD.iscsi_initiator_iqn_default),
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_NoAccess,)),  # hide
        ]

        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_update_volume_stats(self):
        hook = RequestSideEffect()

        hook.append(None, TD.resp_get_licenses)
        hook.append(None, TD.resp_get_pools)
        hook.append(None, TD.resp_get_iscsi_nodes)
        hook.append(None, TD.resp_get_get_iscsi_portals)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)

        expect_stats = {
            'volume_backend_name': "iSCSI_BACKEND",
            'storage_protocol': 'iSCSI',
            'driver_version': VERSION,
            'pools': [{'pool_name': TD.storage_pool_name_default,
                       'reserved_percentage': 0,
                       'free_capacity_gb': 16,
                       'total_capacity_gb': 26,
                       'thin_provisioning_support': True,
                       'thick_provisioning_support': True,
                       'provisioned_capacity_gb': 9,
                       'max_over_subscription_ratio': 20.0,
                       'consistencygroup_support': True}],
            'vendor_name': "EMC"
        }

        with mock.patch.object(self.configuration, 'safe_get',
                               mock.Mock(return_value='iSCSI_BACKEND')):
            stats = self.driver.update_volume_stats()
        self.assertEqual(expect_stats, stats)
        self.assertDictMatch(stats, expect_stats)
        self.assertDictMatch(self.driver.helper.storage_targets,
                             TD.iscsi_targets)
        expected_calls = [
            TD.req_get_licenses(('id', 'isValid')),
            TD.req_get_pools(('name', 'sizeTotal', 'sizeFree', 'id',
                              'sizeSubscribed')),
            TD.req_get_get_iscsi_nodes(('id', 'name')),
            TD.req_get_get_iscsi_portals(('id', 'ipAddress',
                                          'ethernetPort', 'iscsiNode'))
        ]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_get_volume_stats_no_refresh(self):
        hook = RequestSideEffect()
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.get_volume_stats(False)
        self.assertFalse(EMCUnityRESTClient._request.called)

    def test_get_volume_stats_refresh(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_licenses)
        hook.append(None, TD.resp_get_pools)
        hook.append(None, TD.resp_get_iscsi_nodes)
        hook.append(None, TD.resp_get_get_iscsi_portals)
        hook.append(None, TD.resp_get_licenses)
        hook.append(None, TD.new_resp_get_pools)
        hook.append(None, TD.resp_get_iscsi_nodes)
        hook.append(None, TD.new_resp_get_get_iscsi_portals)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)

        expect_stats = {
            'volume_backend_name': "iSCSI_BACKEND",
            'storage_protocol': 'iSCSI',
            'driver_version': VERSION,
            'vendor_name': "EMC",
            'pools': [{
                'pool_name': TD.storage_pool_name_default,
                'reserved_percentage': 0,
                'free_capacity_gb': 16,
                'total_capacity_gb': 26,
                'thin_provisioning_support': True,
                'thick_provisioning_support': True,
                'provisioned_capacity_gb': 9,
                'max_over_subscription_ratio': 20.0,
                'consistencygroup_support': True}]
        }

        expect_new_stats = {
            'volume_backend_name': "iSCSI_BACKEND",
            'storage_protocol': 'iSCSI',
            'driver_version': VERSION,
            'vendor_name': "EMC",
            'pools': [{
                'pool_name': TD.storage_pool_name_default,
                'reserved_percentage': 0,
                'free_capacity_gb': 1,
                'total_capacity_gb': 2,
                'thin_provisioning_support': True,
                'thick_provisioning_support': True,
                'provisioned_capacity_gb': 9,
                'max_over_subscription_ratio': 20.0,
                'consistencygroup_support': True}]
        }

        with mock.patch.object(self.configuration, 'safe_get',
                               mock.Mock(return_value='iSCSI_BACKEND')):
            stats = self.driver.update_volume_stats()
            newstats = self.driver.get_volume_stats(True)
        self.assertDictMatch(stats, expect_stats)
        self.assertDictMatch(newstats, expect_new_stats)
        self.assertDictMatch(self.driver.helper.storage_targets,
                             TD.n_iscsi_targets)

    def test_manage_existing(self):
        hook = RequestSideEffect()
        lun_new_name = TD.os_vol_for_manage_existing['name']
        hook.append(None, None)
        hook.append(None, TD.resp_get_lun_by_name_for_manage_exist)
        hook.append(None, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        existing_ref1 = TD.test_existing_ref
        model_update = self.driver.manage_existing(
            TD.os_vol_for_manage_existing, existing_ref1)
        self.assertTrue('provider_location' in model_update)
        pl_dict = self.load_provider_location(
            model_update['provider_location'])
        self.assertDictMatch(pl_dict,
                             {'system': TD.storage_serial_number_default,
                              'type': 'lun',
                              'id': TD.lun_id_default})
        existing_ref2 = {'source-name': 'LUN01'}
        model_update = self.driver.manage_existing(
            TD.os_vol_for_manage_existing, existing_ref2)
        self.assertTrue('provider_location' in model_update)
        pl_dict = self.load_provider_location(
            model_update['provider_location'])
        self.assertDictMatch(pl_dict,
                             {'system': TD.storage_serial_number_default,
                              'type': 'lun',
                              'id': TD.lun_id_default})
        expected_calls = [
            TD.req_modify_lun_name(TD.lun_id_default, lun_new_name),
            TD.req_get_lun_by_name(existing_ref2['source-name'], None),
            TD.req_modify_lun_name(TD.lun_id_default, lun_new_name)]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_manage_existing_get_size(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_lun_by_id_for_manage_exist)
        hook.append(None, TD.resp_get_lun_by_name_for_manage_exist)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)

        existing_ref1 = TD.test_existing_ref
        size = self.driver.manage_existing_get_size(
            TD.os_vol_for_manage_existing, existing_ref1)
        self.assertEqual(size, 1)

        existing_ref2 = {'source-name': 'LUN01'}
        size = self.driver.manage_existing_get_size(
            TD.os_vol_for_manage_existing, existing_ref2)
        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default, None),
            TD.req_get_lun_by_name(existing_ref2['source-name'], None)]
        self.assertEqual(size, 1)
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_manage_existing_lun_name_exist(self):
        hook = RequestSideEffect()
        lun_new_name = TD.os_vol_for_manage_existing['name']
        hook.append(TD.resp_modify_name_exist_error, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        model_update = self.driver.manage_existing(
            TD.os_vol_for_manage_existing, TD.test_existing_ref)
        self.assertTrue('provider_location' in model_update)
        pl_dict = self.load_provider_location(
            model_update['provider_location'])
        self.assertDictMatch(pl_dict,
                             {'system': TD.storage_serial_number_default,
                              'type': 'lun',
                              'id': TD.lun_id_default})
        expected_calls = [
            TD.req_modify_lun_name(TD.lun_id_default, lun_new_name)]

        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_manage_existing_exception(self):
        hook = RequestSideEffect()
        lun_new_name = TD.os_vol_for_manage_existing['name']
        hook.append(TD.resp_modify_name_error, None)
        hook.append(None, TD.resp_get_lun_by_id_for_manage_exist)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r'.*Manage existing lun failed.*',
                                self.driver.manage_existing,
                                TD.os_vol_for_manage_existing,
                                TD.test_existing_ref)
        expected_calls = [
            TD.req_modify_lun_name(TD.lun_id_default, lun_new_name)]

        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_import_volume_not_in_manage_pool(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_lun_not_in_manage_pool)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.ManageExistingInvalidReference,
                                r'.*manageable pool backend.*',
                                self.driver.manage_existing_get_size,
                                TD.os_vol_for_manage_existing,
                                TD.test_existing_ref)

        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default, ())]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_get_managed_storage_pools_map(self):
        conf_pools = "StoragePool01, StoragePool02"
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_pools)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        pools_map = self.driver.helper._get_managed_storage_pools_map(
            conf_pools)
        expected_pools_map = {'StoragePool01': 'pool_2'}
        self.assertEqual(expected_pools_map, pools_map)

        conf_pools = "StoragePool02, "
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_pools)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.helper._get_managed_storage_pools_map,
            conf_pools)

        conf_pools = None
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_pools)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        pools_map = self.driver.helper._get_managed_storage_pools_map(
            conf_pools)
        expected_pools_map = {
            TD.storage_pool_name_default: TD.storage_pool_id_default,
            'StoragePool01': 'pool_2'}
        self.assertEqual(pools_map, expected_pools_map)


class EMCUnityFCDriverTestCase(EMCUnityDriverTestCase):
    def setUp(self):
        super(EMCUnityFCDriverTestCase, self).setUp()
        self.configuration.storage_protocol = 'FC'
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_basic_system_info)
        hook.append(None, TD.resp_get_pools)
        hook.append(None, TD.resp_get_fc_ports)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver = EMCUnityDriver(configuration=self.configuration)
        expected_calls = [
            TD.req_get_basic_system_info(('name', 'softwareVersion')),
            TD.req_get_pools(('name', 'id')),
            TD.req_get_fc_ports(('id', 'wwn', 'storageProcessor'))]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)
        self.driver.helper.client.UNITY = False

    def test_fc_targets(self):
        self.assertDictMatch(self.driver.helper.storage_targets,
                             TD.fc_targets)

    def test_initialize_connection_missing_host_with_orphan(self):
        hook = RequestSideEffect()

        resp_get_initiator_by_uid_fc_missing_host_wwn1 = {
            'entries': [
                {'content':
                    {'id': 'HostInitiator_21',
                     'initiatorId': TD.fc_initator_wwn1}}]}
        resp_get_initiator_by_uid_fc_missing_host_wwn2 = {
            'entries': [
                {'content':
                    {'id': 'HostInitiator_22',
                     'initiatorId': TD.fc_initator_wwn2,
                     'parentHost': None}}]}
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None,
                    resp_get_initiator_by_uid_fc_missing_host_wwn1)
        hook.append(None,
                    resp_get_initiator_by_uid_fc_missing_host_wwn2)
        hook.append(None, TD.resq_get_host_unexist)
        hook.append(None, TD.resp_create_host(TD.host_id_default))
        hook.append(None, None)
        hook.append(None, None)
        hook.append(None, None)
        hook.append(None, TD.resp_get_host_lun_by_ends_default)
        hook.append(None, TD.resp_get_host_by_id)
        hook.append(None,
                    TD.resp_get_initiator_paths_by_initiator_id_fc(
                        'HostInitiator_21'))
        hook.append(None,
                    TD.resp_get_initiator_paths_by_initiator_id_fc(
                        'HostInitiator_22'))
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        connection_info = self.driver.initialize_connection(
            TD.os_vol_default, TD.os_connector_default)
        self.assertDictMatch(connection_info, TD.connection_info_fc_default)
        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default),
            # _categorize_initiators
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn1),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn2),
            # _extract_host_id
            TD.req_get_host_by_name(TD.host_name_default, ('id',)),
            TD.req_create_host(TD.host_name_default),
            TD.req_register_initiator('HostInitiator_21', TD.host_id_default),
            TD.req_register_initiator('HostInitiator_22', TD.host_id_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_Production,)),
            TD.req_get_host_lun_by_ends(TD.host_id_default,
                                        TD.lun_id_default,
                                        TD.HostLUNTypeEnum_LUN, ('hlu',)),
            TD.req_get_host_by_id(TD.host_id_default, ('fcHostInitiators',)),
            TD.req_get_initiator_paths_by_initiator_id('HostInitiator_21',
                                                       ('fcPort', 'isLoggedIn')
                                                       ),
            TD.req_get_initiator_paths_by_initiator_id('HostInitiator_22',
                                                       ('fcPort', 'isLoggedIn')
                                                       )]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_initialize_connection_failed_hlu(self):
        hook = RequestSideEffect()

        resp_expose_lun_error = {
            "errorCode": 123434,
            "httpStatusCode": 404,
            "messages": [{"en-US": "The requested resource"
                                   "does not exist. (Error Code:0x7d13123)"}],
            "created": "2014-04-11T06:08:19.102Z"}
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None,
                    TD.resp_get_initiator_by_uid_fc_wwn1)
        hook.append(None,
                    TD.resp_get_initiator_by_uid_fc_wwn2)
        hook.append(resp_expose_lun_error, None)

        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r".*Failed to expose.*",
                                self.driver.initialize_connection,
                                TD.os_vol_default,
                                TD.os_connector_default)
        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn1),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn2),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_Production,)),
        ]

        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_initialize_connection_failed_no_login_session(self):
        hook = RequestSideEffect()

        resp_get_lun_by_id_has_host_access = {
            'content': {'id': TD.lun_id_default,
                        'currentNode': 0,
                        'defaultNode': 1,
                        'name': 'volume-x',
                        'hostAccess': [{'host': {'id': TD.host_id_default},
                                        'accessMask': 1},
                                       {'host': {'id': "fake_host"},
                                        'accessMask': 1}]}}
        hook.append(None, resp_get_lun_by_id_has_host_access)
        hook.append(None,
                    TD.resp_get_initiator_by_uid_fc_wwn1)
        hook.append(None,
                    TD.resp_get_initiator_by_uid_fc_wwn2)
        hook.append(None, None)
        hook.append(None, TD.resp_get_host_lun_by_ends_default)
        hook.append(None, TD.resp_get_host_by_id)
        hook.append(None, TD.resp_get_initiator_paths_by_initiator_id_fc(
            'HostInitiator_21', False))
        hook.append(None,
                    TD.resp_get_initiator_paths_by_initiator_id_fc(
                        'HostInitiator_22', False))
        # Expose lun revert
        hook.append(None, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r".*no FC initiator.*has paths.*",
                                self.driver.initialize_connection,
                                TD.os_vol_default,
                                TD.os_connector_default)
        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn1),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn2),
            TD.req_expose_lun(TD.lun_id_default,
                              ('fake_host', TD.host_id_default),
                              (TD.HostLUNAccessEnum_Production,
                               TD.HostLUNAccessEnum_Production)),
            TD.req_get_host_lun_by_ends(TD.host_id_default,
                                        TD.lun_id_default,
                                        TD.HostLUNTypeEnum_LUN, ('hlu',)),
            TD.req_get_host_by_id(TD.host_id_default, ('fcHostInitiators',)),
            TD.req_get_initiator_paths_by_initiator_id('HostInitiator_21',
                                                       ('fcPort', 'isLoggedIn')
                                                       ),
            TD.req_get_initiator_paths_by_initiator_id('HostInitiator_22',
                                                       ('fcPort', 'isLoggedIn')
                                                       ),
            TD.req_hide_lun(TD.lun_id_default,
                            [{'host': {'id': "fake_host"},
                              'accessMask': 1},
                             {'host': {'id': TD.host_id_default},
                              'accessMask': 0}])]

        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_initiatilze_connection_with_new(self):
        hook = RequestSideEffect()

        resp_get_initiator_by_uid_unexist = {
            'entries': []}
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None,
                    resp_get_initiator_by_uid_unexist)
        hook.append(None,
                    resp_get_initiator_by_uid_unexist)
        hook.append(None, TD.resq_get_host_unexist)
        hook.append(None, TD.resp_create_host(TD.host_id_default))
        hook.append(None, TD.resp_create_initiator_fc("HostInitiator_21"))
        hook.append(None, TD.resp_create_initiator_fc("HostInitiator_22"))
        hook.append(None, None)
        hook.append(None, TD.resp_get_host_lun_by_ends_default)
        hook.append(None, TD.resp_get_host_by_id)
        hook.append(None,
                    TD.resp_get_initiator_paths_by_initiator_id_fc(
                        'HostInitiator_21', port=TD.spa_iom_0_fc0))
        hook.append(None,
                    TD.resp_get_initiator_paths_by_initiator_id_fc(
                        'HostInitiator_22', port=TD.spb_iom_0_fc0))
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        connection_info = self.driver.initialize_connection(
            TD.os_vol_default, TD.os_connector_default)
        self.assertDictMatch(connection_info,
                             TD.connection_info_fc(
                                 [TD.spa_iom_0_fc0,
                                  TD.spb_iom_0_fc0])
                             )
        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn1),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn2),
            TD.req_get_host_by_name(TD.host_name_default, ('id',)),
            TD.req_create_host(TD.host_name_default),
            TD.req_create_initiator_fc(TD.fc_initator_wwn1,
                                       TD.host_id_default),
            TD.req_create_initiator_fc(TD.fc_initator_wwn2,
                                       TD.host_id_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_Production,)),
            TD.req_get_host_lun_by_ends(TD.host_id_default,
                                        TD.lun_id_default,
                                        TD.HostLUNTypeEnum_LUN, ('hlu',)),
            TD.req_get_host_by_id(TD.host_id_default, ('fcHostInitiators',)),
            TD.req_get_initiator_paths_by_initiator_id('HostInitiator_21',
                                                       ('fcPort', 'isLoggedIn')
                                                       ),
            TD.req_get_initiator_paths_by_initiator_id('HostInitiator_22',
                                                       ('fcPort', 'isLoggedIn')
                                                       )]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_initiatilze_connection_without_path(self):
        hook = RequestSideEffect()

        resp_get_lun_by_id_has_host_access = {
            'content': {'id': TD.lun_id_default,
                        'currentNode': 0,
                        'defaultNode': 1,
                        'name': 'volume-x',
                        'hostAccess': [{'host': {'id': TD.host_id_default},
                                        'accessMask': 1},
                                       {'host': {'id': "fake_host"},
                                        'accessMask': 1}]}}
        hook.append(None, resp_get_lun_by_id_has_host_access)
        hook.append(None,
                    TD.resp_get_initiator_by_uid_fc_wwn1)
        hook.append(None,
                    TD.resp_get_initiator_by_uid_fc_wwn2)
        hook.append(None, None)
        hook.append(None, TD.resp_get_host_lun_by_ends_default)
        hook.append(None, TD.resp_get_host_by_id)
        hook.append(None,
                    TD.resp_get_initiator_paths_by_initiator_id_no_path_fc)
        hook.append(None,
                    TD.resp_get_initiator_paths_by_initiator_id_no_path_fc)

        # Expose lun revert
        hook.append(None, resp_get_lun_by_id_has_host_access)
        hook.append(None, None)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                r".*no FC initiator.*has paths.*",
                                self.driver.initialize_connection,
                                TD.os_vol_default,
                                TD.os_connector_default)
        expected_calls = [
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn1),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn2),
            TD.req_expose_lun(TD.lun_id_default,
                              ('fake_host', TD.host_id_default,),
                              (TD.HostLUNAccessEnum_Production,
                               TD.HostLUNAccessEnum_Production)),
            TD.req_get_host_lun_by_ends(TD.host_id_default,
                                        TD.lun_id_default,
                                        TD.HostLUNTypeEnum_LUN, ('hlu',)),
            TD.req_get_host_by_id(TD.host_id_default, ('fcHostInitiators',)),
            TD.req_get_initiator_paths_by_initiator_id('HostInitiator_21',
                                                       ('fcPort', 'isLoggedIn')
                                                       ),
            TD.req_get_initiator_paths_by_initiator_id('HostInitiator_22',
                                                       ('fcPort', 'isLoggedIn')
                                                       ),
            TD.req_hide_lun(TD.lun_id_default,
                            [{'host': {'id': "fake_host"},
                              'accessMask': 1},
                             {'host': {'id': TD.host_id_default},
                              'accessMask': 0}])]

        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    @mock.patch("cinder.zonemanager.utils.create_zone_manager",
                mock.Mock(return_value=None))
    @mock.patch("cinder.volume.configuration.Configuration.safe_get",
                mock.Mock(return_value='fabric'))
    @mock.patch(
        "cinder.zonemanager.fc_san_lookup_service.FCSanLookupService." +
        "get_device_mapping_from_network", mock.Mock(return_value=TD.mapping))
    def test_initialize_connection_auto_zone_fabric(self):
        """Test auto-zoning zone not done by admin."""
        hook = RequestSideEffect()
        resp_get_initiator_by_uid_unexist = {
            'entries': []}
        hook.append(None, TD.resp_get_basic_system_info)
        hook.append(None, TD.resp_get_pools)
        hook.append(None, TD.resp_get_fc_ports)
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None,
                    resp_get_initiator_by_uid_unexist)
        hook.append(None,
                    resp_get_initiator_by_uid_unexist)
        hook.append(None, TD.resq_get_host_unexist)
        hook.append(None, TD.resp_create_host(TD.host_id_default))
        hook.append(None, TD.resp_create_initiator_fc("HostInitiator_21"))
        hook.append(None, TD.resp_create_initiator_fc("HostInitiator_22"))
        hook.append(None, None)
        hook.append(None, TD.resp_get_host_lun_by_ends_default)
        hook.append(None, TD.resp_get_host_by_id)
        hook.append(None,
                    TD.resp_get_initiator_paths_by_initiator_id_no_path_fc)
        hook.append(None,
                    TD.resp_get_initiator_paths_by_initiator_id_no_path_fc)
        # Set zoning mode to fabric
        self.configuration.zoning_mode = "fabric"
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver = EMCUnityDriver(configuration=self.configuration)
        conn_info = self.driver.initialize_connection(
            TD.os_vol_default, TD.os_connector_default)
        self.assertEqual(conn_info['driver_volume_type'], 'fibre_channel')
        self.assertEqual(conn_info['data']['initiator_target_map'],
                         {'1234567890abcde1': ['5006016408E0001E',
                                               '5006016C08E0001E',
                                               '5006016508E0001E',
                                               '5006016D08E0001E'],
                          '1234567890abcde2': ['5006016408E0001E',
                                               '5006016C08E0001E',
                                               '5006016508E0001E',
                                               '5006016D08E0001E']})
        expected_calls = [
            TD.req_get_basic_system_info(('name', 'softwareVersion')),
            TD.req_get_pools(('name', 'id')),
            TD.req_get_fc_ports(('id', 'wwn', 'storageProcessor')),
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn1),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn2),
            TD.req_get_host_by_name(TD.host_name_default, ('id',)),
            # create host
            TD.req_create_host(TD.host_name_default),
            TD.req_create_initiator_fc(TD.fc_initator_wwn1,
                                       TD.host_id_default),
            TD.req_create_initiator_fc(TD.fc_initator_wwn2,
                                       TD.host_id_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_Production,)),
            TD.req_get_host_lun_by_ends(TD.host_id_default,
                                        TD.lun_id_default,
                                        TD.HostLUNTypeEnum_LUN, ('hlu',)),
            TD.req_get_host_by_id(TD.host_id_default, ('fcHostInitiators',)),
            TD.req_get_initiator_paths_by_initiator_id('HostInitiator_21',
                                                       ('fcPort', 'isLoggedIn')
                                                       ),
            TD.req_get_initiator_paths_by_initiator_id('HostInitiator_22',
                                                       ('fcPort', 'isLoggedIn')
                                                       )]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    @mock.patch("cinder.zonemanager.utils.create_zone_manager",
                mock.Mock(return_value=None))
    @mock.patch("cinder.volume.configuration.Configuration.safe_get",
                mock.Mock(return_value='fabric'))
    @mock.patch(
        "cinder.zonemanager.fc_san_lookup_service.FCSanLookupService." +
        "get_device_mapping_from_network", mock.Mock(return_value=TD.mapping))
    def test_terminate_connection_auto_zone_fabric(self):
        """Test auto-zoning zone not done by admin."""

        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_basic_system_info)
        hook.append(None, TD.resp_get_pools)
        hook.append(None, TD.resp_get_fc_ports)
        hook.append(None, TD.resp_get_initiator_by_uid_fc_default)
        hook.append(None, TD.resp_get_initiator_by_uid_fc_default)
        hook.append(None, TD.resp_get_lun_by_id_default)
        hook.append(None, None)
        hook.append(None, TD.resp_get_host_by_id)

        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver = EMCUnityDriver(configuration=self.configuration)
        conn_info = self.driver.terminate_connection(TD.os_vol_default,
                                                     TD.os_connector_default)
        self.assertEqual(conn_info['driver_volume_type'], 'fibre_channel')
        self.assertEqual(conn_info['data']['initiator_target_map'],
                         {'1234567890abcde1': ['5006016408E0001E',
                                               '5006016C08E0001E',
                                               '5006016508E0001E',
                                               '5006016D08E0001E'],
                          '1234567890abcde2': ['5006016408E0001E',
                                               '5006016C08E0001E',
                                               '5006016508E0001E',
                                               '5006016D08E0001E']})
        expected_calls = [
            TD.req_get_basic_system_info(('name', 'softwareVersion')),
            TD.req_get_pools(('name', 'id')),
            TD.req_get_fc_ports(('id', 'wwn', 'storageProcessor')),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn1),
            TD.req_get_initiator_by_uid(TD.fc_initator_wwn2),
            TD.req_get_lun_by_id(TD.lun_id_default),
            TD.req_expose_lun(TD.lun_id_default,
                              (TD.host_id_default,),
                              (TD.HostLUNAccessEnum_NoAccess,)),  # hide
        ]

        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_update_volume_stats(self):
        hook = RequestSideEffect()

        hook.append(None, TD.resp_get_licenses)
        hook.append(None, TD.resp_get_pools)
        hook.append(None, TD.resp_get_fc_ports)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)

        expect_stats = {
            'volume_backend_name': "FC_BACKEND",
            'storage_protocol': 'FC',
            'driver_version': VERSION,
            'vendor_name': "EMC",
            'pools': [{'pool_name': TD.storage_pool_name_default,
                       'reserved_percentage': 0,
                       'free_capacity_gb': 16,
                       'total_capacity_gb': 26,
                       'thin_provisioning_support': True,
                       'thick_provisioning_support': True,
                       'provisioned_capacity_gb': 9,
                       'consistencygroup_support': True,
                       'max_over_subscription_ratio': 20.0}]
        }

        with mock.patch.object(self.configuration, 'safe_get',
                               mock.Mock(return_value='FC_BACKEND')):
            stats = self.driver.update_volume_stats()
        self.assertDictMatch(stats, expect_stats)
        self.assertDictMatch(self.driver.helper.storage_targets, TD.fc_targets)
        expected_calls = [
            TD.req_get_licenses(('id', 'isValid')),
            TD.req_get_pools(('name', 'sizeTotal', 'sizeFree', 'id',
                              'sizeSubscribed')),
            TD.req_get_fc_ports(('id', 'wwn', 'storageProcessor'))
        ]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)

    def test_get_volume_stats_no_refresh(self):
        hook = RequestSideEffect()
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)
        self.driver.get_volume_stats(False)
        self.assertFalse(EMCUnityRESTClient._request.called)

    def test_get_volume_stats_refresh(self):
        hook = RequestSideEffect()
        hook.append(None, TD.resp_get_licenses)
        hook.append(None, TD.resp_get_pools)
        hook.append(None, TD.resp_get_fc_ports)
        hook.append(None, TD.resp_get_licenses)
        hook.append(None, TD.new_resp_get_pools)
        hook.append(None, TD.n_resp_get_fc_ports)
        EMCUnityRESTClient._request = mock.Mock(side_effect=hook)

        expect_stats = {
            'volume_backend_name': "FC_BACKEND",
            'storage_protocol': 'FC',
            'driver_version': VERSION,
            'vendor_name': "EMC",
            'pools': [{
                'pool_name': TD.storage_pool_name_default,
                'reserved_percentage': 0,
                'free_capacity_gb': 16,
                'total_capacity_gb': 26,
                'thin_provisioning_support': True,
                'thick_provisioning_support': True,
                'provisioned_capacity_gb': 9,
                'consistencygroup_support': True,
                'max_over_subscription_ratio': 20.0}]
        }

        expect_new_stats = {
            'volume_backend_name': "FC_BACKEND",
            'storage_protocol': 'FC',
            'driver_version': VERSION,
            'vendor_name': "EMC",
            'pools': [{
                'pool_name': TD.storage_pool_name_default,
                'reserved_percentage': 0,
                'free_capacity_gb': 1,
                'total_capacity_gb': 2,
                'thin_provisioning_support': True,
                'thick_provisioning_support': True,
                'provisioned_capacity_gb': 9,
                'consistencygroup_support': True,
                'max_over_subscription_ratio': 20.0}]
        }

        with mock.patch.object(self.configuration, 'safe_get',
                               mock.Mock(return_value='FC_BACKEND')):
            stats = self.driver.update_volume_stats()
            newstats = self.driver.get_volume_stats(True)
        self.assertDictMatch(stats, expect_stats)
        self.assertDictMatch(newstats, expect_new_stats)
        self.assertDictMatch(self.driver.helper.storage_targets,
                             TD.n_fc_targets)
        expected_calls = [
            TD.req_get_licenses(('id', 'isValid')),
            TD.req_get_pools(('name', 'sizeTotal', 'sizeFree', 'id',
                              'sizeSubscribed')),
            TD.req_get_fc_ports(('id', 'wwn', 'storageProcessor')),
            TD.req_get_licenses(('id', 'isValid')),
            TD.req_get_pools(('name', 'sizeTotal', 'sizeFree', 'id',
                              'sizeSubscribed')),
            TD.req_get_fc_ports(('id', 'wwn', 'storageProcessor'))
        ]
        EMCUnityRESTClient._request.assert_has_calls(expected_calls)
