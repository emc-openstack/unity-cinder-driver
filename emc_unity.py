# Copyright (c) 2016 EMC Corporation.
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

"""
Drivers for EMC Unity array based on RESTful API.
"""

import contextlib
import cookielib
import json
import random
import re
import types
import urllib2

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import units
import six
import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow import task
from taskflow.types import failure

from cinder import exception
from cinder.i18n import _, _LW, _LI, _LE
from cinder import utils
from cinder.volume.configuration import Configuration
from cinder.volume.drivers.san import san
from cinder.volume import manager
from cinder.volume import utils as vol_utils
from cinder.volume import volume_types
from cinder.zonemanager import utils as zm_utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
VERSION = '00.02.03'

GiB = 1024 * 1024 * 1024
ENABLE_TRACE = False
EMC_OPENSTACK_DUMMY_LUN = 'openstack_dummy_lun'

QOS_MAX_IOPS = 'maxIOPS'
QOS_MAX_BWS = 'maxBWS'
QOS_CONSUMER_BACKEND = 'back-end'
QOS_CONSUMER_FRONTEND = 'front-end'

loc_opts = [
    cfg.StrOpt('storage_pool_names',
               default=None,
               deprecated_name='storage_pool_name',
               help='Comma-separated list of storage pool names to be used.'),
    cfg.StrOpt('storage_protocol',
               default='iSCSI',
               help='Protocol to access the storage '
                    'allocated from this Cinder backend')]

CONF.register_opts(loc_opts)


def decorate_all_methods(method_decorator):
    """Applies decorator on the methods of a class.

    This is a class decorator, which will apply method decorator referred
    by method_decorator to all the public methods (without underscore as
    the prefix) in a class.
    """
    if not ENABLE_TRACE:
        return lambda cls: cls

    def _decorate_all_methods(cls):
        for attr_name, attr_val in cls.__dict__.items():
            if (isinstance(attr_val, types.FunctionType) and
                    not attr_name.startswith("_")):
                setattr(cls, attr_name, method_decorator(attr_val))
        return cls

    return _decorate_all_methods


def log_enter_exit(func):
    if not CONF.debug:
        return func

    def inner(self, *args, **kwargs):
        LOG.debug("Entering %(cls)s.%(method)s",
                  {'cls': self.__class__.__name__,
                   'method': func.__name__})
        start = timeutils.utcnow()
        ret = func(self, *args, **kwargs)
        end = timeutils.utcnow()
        LOG.debug("Exiting %(cls)s.%(method)s. "
                  "Spent %(duration)s sec. "
                  "Return %(return)s",
                  {'cls': self.__class__.__name__,
                   'duration': timeutils.delta_seconds(start, end),
                   'method': func.__name__,
                   'return': ret})
        return ret

    return inner


@decorate_all_methods(log_enter_exit)
class EMCUnityRESTClient(object):
    """EMC Unity Client interface handing REST calls and responses."""

    HEADERS = {'Accept': 'application/json',
               'Content-Type': 'application/json',
               'Accept_Language': 'en_US',
               'Visibility': 'Enduser',
               'X-EMC-REST-CLIENT': 'true',
               'User-agent': 'EMC-OpenStack'}
    CSRF_HEADER = 'EMC-CSRF-TOKEN'
    HostTypeEnum_HostManual = 1
    HostLUNTypeEnum_LUN = 1
    HostLUNTypeEnum_LUN_Snap = 2
    HostLUNAccessEnum_NoAccess = 0
    HostLUNAccessEnum_Production = 1
    HostLUNAccessEnum_Snapshot = 2
    HostLUNAccessEnum_Both = 3
    HostLUNAccessEnum_Mixed = 0xffff
    HostSnapAccessEnum_ReadOnly = 0
    HostSnapAccessEnum_ReadWrite = 1
    HostSnapAccessAllowed = 1
    LUN_NAME_IN_USE = 108007744
    LUN_SNAP_ACCESS_ALLOWED = 108008704
    POLICY_NAME_IN_USE = 151032071

    def __init__(self, host, port=443, user='Local/admin',
                 password='', realm='Security Realm',
                 debug=False):
        self.mgmt_url = 'https://%(host)s:%(port)s' % {'host': host,
                                                       'port': port}
        self.debug = debug
        https_hander = urllib2.HTTPSHandler()
        cookie_jar = cookielib.CookieJar()
        cookie_hander = urllib2.HTTPCookieProcessor(cookie_jar)
        passwd_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
        passwd_mgr.add_password(realm,
                                self.mgmt_url,
                                user,
                                password)
        auth_handler = urllib2.HTTPBasicAuthHandler(passwd_mgr)
        self.url_opener = urllib2.build_opener(https_hander,
                                               cookie_hander,
                                               auth_handler)

    def _http_log_req(self, req):
        if not self.debug:
            return

        string_parts = ['curl -i']
        string_parts.append(' -X %s' % req.get_method())

        for k in req.headers:
            header = ' -H "%s: %s"' % (k, req.headers[k])
            string_parts.append(header)

        if req.data:
            string_parts.append(" -d '%s'" % (req.data))
        string_parts.append(' ' + req.get_full_url())
        LOG.debug("\nREQ: %s\n", "".join(string_parts))

    def _http_log_resp(self, resp, body, failed_req=None):
        if not self.debug and failed_req is None:
            return
        if failed_req:
            LOG.error(
                _LE('REQ: [%(method)s] %(url)s %(req_hdrs)s\n'
                    'REQ BODY: %(req_b)s\n'
                    'RESP: [%(code)s] %(resp_hdrs)s\n'
                    'RESP BODY: %(resp_b)s\n'),
                {'method': failed_req.get_method(),
                 'url': failed_req.get_full_url(),
                 'req_hdrs': failed_req.headers,
                 'req_b': failed_req.data,
                 'code': resp.getcode(),
                 'resp_hdrs': str(resp.headers).replace('\n', '\\n'),
                 'resp_b': body})
        else:
            LOG.debug(
                "RESP: [%s] %s\nRESP BODY: %s\n",
                resp.getcode(),
                str(resp.headers).replace('\n', '\\n'),
                body)

    def _http_log_err(self, err, req):
        LOG.error(
            _LE('REQ: [%(method)s] %(url)s %(req_hdrs)s\n'
                'REQ BODY: %(req_b)s\n'
                'ERROR CODE: [%(code)s] \n'
                'ERROR REASON: %(resp_e)s\n'),
            {'method': req.get_method(),
             'url': req.get_full_url(),
             'req_hdrs': req.headers,
             'req_b': req.data,
             'code': err.code,
             'resp_e': err.reason})

    def _request(self, rel_url, req_data=None, method=None):
        req_body = None if req_data is None else json.dumps(req_data)
        url = self.mgmt_url + rel_url
        req = urllib2.Request(url, req_body, EMCUnityRESTClient.HEADERS)
        if method is not None:
            req.get_method = lambda: method
        self._http_log_req(req)
        err, resp = self._send_request(req)
        if err and err.code == 401:
            token = self._update_csrf_token()
            req.headers.update(
                {EMCUnityRESTClient.CSRF_HEADER: token})
            EMCUnityRESTClient.HEADERS.update(
                {EMCUnityRESTClient.CSRF_HEADER: token})
            self._http_log_req(req)
            err, resp = self._send_request(req)
        if err:
            return self.parse_error(err, req)
        return None, resp

    def _send_request(self, req):
        try:
            resp = self.url_opener.open(req)
            resp_body = resp.read()
            resp_data = json.loads(resp_body) if resp_body else None
            self._http_log_resp(resp, resp_body)
        except urllib2.HTTPError as http_err:
            return http_err, None
        return None, resp_data

    def parse_error(self, http_err, req):
        if hasattr(http_err, 'read'):
            resp_body = http_err.read()
            self._http_log_resp(http_err, resp_body, req)
            if resp_body:
                err = json.loads(resp_body)['error']
            else:
                err = {'errorCode': -1,
                       'httpStatusCode': http_err.code,
                       'messages': six.text_type(http_err),
                       'request': req}
        else:
            self._http_log_err(http_err, req)
            err = {'errorCode': -1,
                   'httpStatusCode': http_err.code,
                   'messages': six.text_type(http_err),
                   'request': req}

            raise exception.VolumeBackendAPIException(data=err)
        return err, None

    def _update_csrf_token(self):
        LOG.info(_LI('Updating EMC CSRF TOKEN.'))
        path_user = '/api/types/user/instances'
        req = urllib2.Request(self.mgmt_url + path_user, None,
                              EMCUnityRESTClient.HEADERS)
        resp = self.url_opener.open(req)
        return resp.headers.get('EMC-CSRF-TOKEN')

    def _get_content_list(self, resp):
        return [entry['content'] for entry in resp['entries']]

    def _filter_by_fields(self, category, conditions, fields=None):
        filters = map(lambda entry: '%(f)s %(o)s "%(v)s"' %
                                    {'f': entry[0], 'o': entry[1],
                                     'v': entry[2]},
                      conditions)
        filter_str = ' and '.join(filters)
        filter_str = urllib2.quote(filter_str)
        get_by_fields_url = (
            '/api/types/%(category)s/instances?filter=%(filter)s' %
            {'category': category, 'filter': filter_str})
        if fields:
            get_by_fields_url += '&fields=%s' % \
                                 (','.join(map(urllib2.quote, fields)))
        err, resp = self._request(get_by_fields_url)
        return () if err else self._get_content_list(resp)

    def _filter_by_field(self, category,
                         field, value,
                         fields=None):
        return self._filter_by_fields(category,
                                      ((field, 'eq', value),),
                                      fields)

    def _get_all(self, category, fields=None):
        get_all_url = '/api/types/%s/instances' % category
        if fields:
            get_all_url += '?fields=%s' % (','.join(fields))
        err, resp = self._request(get_all_url)
        return self._get_content_list(resp)

    def _filter_by_id(self, category, obj_id, fields):
        get_by_id_url = '/api/instances/%(category)s/%(obj_id)s' % \
                        {'category': category, 'obj_id': obj_id}
        if fields:
            get_by_id_url += '?fields=%s' % (','.join(fields))
        err, resp = self._request(get_by_id_url)
        return () if err else (resp['content'],)

    def get_pools(self, fields=None):
        return self._get_all('pool', fields)

    def get_pool_by_name(self, pool_name, fields=None):
        return self._filter_by_field('pool', 'name', pool_name, fields)

    def get_pool_by_id(self, pool_id, fields=None):
        return self._filter_by_id('pool', pool_id, fields)

    def get_group_by_name(self, group_name, fields=None):
        return self._filter_by_field('storageResource', 'name',
                                     group_name, fields)

    def get_lun_by_name(self, lun_name, fields=None):
        return self._filter_by_field('lun', 'name', lun_name, fields)

    def get_lun_by_id(self, lun_id, fields=None):
        return self._filter_by_id('lun', lun_id, fields)

    def get_snap_by_id(self, snap_id,
                       fields=('id', 'name', 'storageResource', 'hostAccess')):
        data = self._filter_by_id('snap', snap_id, fields)
        if not data:
            raise exception.VolumeBackendAPIException(
                data=_('Cannot find snapshot with id : {}').format(snap_id))
        return data[0]

    def get_basic_system_info(self, fields=None):
        return self._get_all('basicSystemInfo', fields)

    def get_licenses(self, fields=None):
        return self._get_all('license', fields)

    def create_consistencygroup(self, group_id):
        cg_create_url = (
            '/api/types/storageResource/action/createConsistencyGroup')
        req_data = {'name': group_id}
        err, resp = self._request(cg_create_url, req_data)
        return (err, None) if err else (err,
                                        resp['content']['storageResource'])

    def delete_consistencygroup(self, group_id, force_snap_deletion=False):
        cg_delete_url = '/api/instances/storageResource/%s' % group_id
        data = {'forceSnapDeletion': force_snap_deletion}
        err, resp = self._request(cg_delete_url, data, 'DELETE')
        return err, resp

    def update_consistencygroup(self, group_id, add_luns=None,
                                remove_luns=None):
        cg_update_url = (
            '/api/instances/storageResource/%s/action/'
            'modifyConsistencyGroup' %
            group_id)
        add_data = [{"lun": {"id": add_id}}
                    for add_id in add_luns] if add_luns else []
        remove_data = [{"lun": {"id": remove_id}}
                       for remove_id in remove_luns] if remove_luns else []
        req_data = {'lunAdd': add_data,
                    'lunRemove': remove_data}
        err, resp = self._request(cg_update_url, req_data)
        return err, resp

    def create_lun(self, pool_id, name, size, is_thin=False,
                   display_name=None, limit_policy_id=None):
        lun_create_url = '/api/types/storageResource/action/createLun'
        lun_parameters = {'pool': {"id": pool_id},
                          'isThinEnabled': True,
                          'size': size}
        if is_thin:
            lun_parameters['isThinEnabled'] = is_thin
        if limit_policy_id:
            lun_parameters['ioLimitParameters'] = {
                'ioLimitPolicy': {'id': limit_policy_id}}
        description = name if display_name is None else display_name
        # More Advance Feature
        data = {'name': name,
                'description': description,
                'lunParameters': lun_parameters}
        err, resp = self._request(lun_create_url, data)
        if err and self.LUN_NAME_IN_USE == err['errorCode']:
            LOG.info(_LI('LUN %s was already created on array.'), name)
            return None, self.get_lun_by_name(name)[0]
        return (err, None) if err else \
            (err, resp['content']['storageResource'])

    def delete_lun(self, lun_id, force_snap_deletion=False):
        lun_delete_url = '/api/instances/storageResource/%s' % lun_id
        data = {'forceSnapDeletion': force_snap_deletion}
        err, resp = self._request(lun_delete_url, data, 'DELETE')
        return err, resp

    def get_hosts(self, fields=None):
        return self._get_all('host', fields)

    def get_host_by_name(self, hostname, fields=None):
        return self._filter_by_field('host', 'name', hostname, fields)

    def get_host_by_id(self, host_id, fields=None):
        return self._filter_by_id('host', host_id, fields)

    def create_host(self, hostname):
        host_create_url = '/api/types/host/instances'
        data = {'type': EMCUnityRESTClient.HostTypeEnum_HostManual,
                'name': hostname}
        err, resp = self._request(host_create_url, data)
        return (err, None) if err else (err, resp['content'])

    def delete_host(self, host_id):
        host_delete_url = '/api/instances/host/%s' % host_id
        err, resp = self._request(host_delete_url, None, 'DELETE')
        return err, resp

    def create_initiator(self, initiator_uid, host_id):
        initiator_create_url = '/api/types/hostInitiator/instances'
        data = {'host': {'id': host_id},
                'initiatorType': 2 if initiator_uid.lower().find('iqn') == 0
                else 1,
                'initiatorWWNorIqn': initiator_uid}
        err, resp = self._request(initiator_create_url, data)
        return (err, None) if err else (err, resp['content'])

    def register_initiator(self, initiator_id, host_id):
        initiator_register_url = \
            '/api/instances/hostInitiator/%s/action/modify' % (
                initiator_id)
        data = {'host': {'id': host_id}}
        err, resp = self._request(initiator_register_url, data)
        return err, resp

    def get_initiators(self, fields=None):
        return self._get_all('hostInitiator', fields)

    def get_initiator_by_uid(self, initiator_uid, fields=None):
        return self._filter_by_field('hostInitiator',
                                     'initiatorId', initiator_uid,
                                     fields)

    def get_initiator_paths_by_initiator_id(self, initiator_id, fields=None):
        conditions = (('id', 'lk', initiator_id + '%'),)
        return self._filter_by_fields('hostInitiatorPath', conditions, fields)

    def get_host_luns(self, fields=None):
        return self._get_all('hostLUN', fields)

    def get_host_lun_by_ends(self, host_id, lun_id, snap_id=None,
                             use_type=None, fields=None):
        use_type = self.HostLUNTypeEnum_LUN if use_type is None else use_type
        conditions = [('id', 'lk', '%%%(host)s_%(lun)s%%' %
                       {'host': host_id, 'lun': lun_id}),
                      ('type', 'eq', use_type)]
        if use_type == self.HostLUNTypeEnum_LUN_Snap:
            conditions.append(('snap.id', 'eq', snap_id))
        return self._filter_by_fields('hostLUN', conditions, fields)

    def get_iscsi_portals(self, fields=None):
        return self._get_all('iscsiPortal', fields)

    def get_iscsi_nodes(self, fields=None):
        return self._get_all('iscsiNode', fields)

    def get_ethernet_ports(self, fields=None):
        return self._get_all('ethernetPort', fields)

    def get_fc_ports(self, fields=None):
        return self._get_all('fcPort', fields)

    def expose_lun(self, lun_id, lun_cg, current_host_access, host_id):
        lun_modify_url = (
            '/api/instances/storageResource/%s/action/modifyLun' % lun_id)
        host_access_list = current_host_access if current_host_access else []
        host_access_list = filter(lambda entry: entry['host']['id'] != host_id,
                                  host_access_list)
        host_access_list.append(
            {'host': {'id': host_id},
             'accessMask': self.HostLUNAccessEnum_Production})
        if lun_cg:
            lun_modify_url = (
                '/api/instances/storageResource/%s/action/'
                'modifyConsistencyGroup'
                % lun_cg)
            data = {"lunModify": [
                {'lun': {'id': lun_id},
                 'lunParameters': {'hostAccess': host_access_list}}]}
        else:
            data = {'lunParameters': {'hostAccess': host_access_list}}
        err, resp = self._request(lun_modify_url, data)
        return err, resp

    def hide_lun(self, lun_id, lun_cg, current_host_access, host_id):
        lun_modify_url = (
            '/api/instances/storageResource/%s/action/modifyLun' % lun_id)

        host_access_list = current_host_access if current_host_access else []
        host_access_list = filter(lambda entry: entry['host']['id'] != host_id,
                                  host_access_list)
        host_access_list.append(
            {'host': {'id': host_id},
             'accessMask': self.HostLUNAccessEnum_NoAccess})
        if lun_cg:
            lun_modify_url = (
                '/api/instances/storageResource/%s/action/'
                'modifyConsistencyGroup' % lun_cg)
            data = {"lunModify": [
                {'lun': {'id': lun_id},
                 'lunParameters': {'hostAccess': host_access_list}}]}
        else:
            data = {'lunParameters': {'hostAccess': host_access_list}}
        err, resp = self._request(lun_modify_url, data)
        return err, resp

    def attach_snap(self, snap_id, host_id):
        # Snapshot can be attached to ONLY one host.
        snap_action_url = (
            '/api/instances/snap/%s/action/attach' % snap_id)
        data = {'hostAccess':
                [{'host': {'id': host_id},
                  'allowedAccess': self.HostSnapAccessEnum_ReadWrite}]}
        err, resp = self._request(snap_action_url, data)
        return err, resp

    def detach_snap(self, snap_id):
        snap_action_url = (
            '/api/instances/snap/%s/action/detach' % snap_id)
        err, resp = self._request(snap_action_url, method='POST')
        return err, resp

    def get_snap_by_name(self, snap_name, fields=None):
        """Gets the snap properties by name."""
        return self._filter_by_field('snap', 'name', snap_name, fields)

    def create_snap(self, lun_id, snap_name, snap_description=None):
        create_snap_url = '/api/types/snap/instances'
        req_data = {'storageResource': {'id': lun_id},
                    'name': snap_name}
        if snap_description:
            req_data['description'] = snap_description
        err, resp = self._request(create_snap_url, req_data)
        return (err, None) if err else \
            (err, resp['content']['id'])

    def delete_snap(self, snap_id):
        """Deletes the snap by the snap_id."""
        delete_snap_url = '/api/instances/snap/%s' % snap_id
        err, resp = self._request(delete_snap_url, None, 'DELETE')
        return err, resp

    def extend_lun(self, lun_id, size):
        lun_modify_url = \
            '/api/instances/storageResource/%s/action/modifyLun' % lun_id
        data = {'lunParameters': {'size': size}}
        return self._request(lun_modify_url, data)

    def modify_lun_name(self, lun_id, new_name):
        """Modify the lun name."""
        lun_modify_url = \
            '/api/instances/storageResource/%s/action/modifyLun' % lun_id
        data = {'name': new_name}
        err, resp = self._request(lun_modify_url, data)
        if err:
            if err['errorCode'] in (0x6701020,):
                LOG.warning(_LW('Nothing to modify, the lun %(lun)s '
                                'already has the name %(name)s.'),
                            {'lun': lun_id, 'name': new_name})
            else:
                reason = (_('Manage existing lun failed. Can not '
                          'rename the lun %(lun)s to %(name)s') %
                          {'lun': lun_id, 'name': new_name})
                raise exception.VolumeBackendAPIException(
                    data=reason)

    def get_limit_policy(self, name):
        """Get existing IO limits by name."""
        return self._filter_by_field(
            'ioLimitPolicy', 'name', name,
            ('id', 'maxIOPS::ioLimitRules.maxIOPS',
             'maxKBPS::ioLimitRules.maxKBPS'))

    def create_limit_policy(self, name, max_iops=None, max_kbps=None):
        """Create host IO limits."""
        create_limit_url = \
            '/api/types/ioLimitPolicy/instances'
        data = {'name': name, 'ioLimitRules': []}
        rule = {}
        if max_iops:
            rule.update({'maxIOPS': max_iops})
        if max_kbps:
            rule.update({'maxKBPS': max_kbps})
        rule.update({'name': name})
        data['ioLimitRules'].append(rule)
        err, resp = self._request(create_limit_url, data)
        if err:
            if err['errorCode'] == self.POLICY_NAME_IN_USE:
                return self.get_limit_policy(name)[0]
            else:
                raise exception.VolumeBackendAPIException(err['messages'])
        return resp['content']


class ArrangeHostTask(task.Task):
    def __init__(self, helper, connector):
        LOG.debug('ArrangeHostTask.__init__ %s', connector)
        super(ArrangeHostTask, self).__init__(provides='host_id')
        self.helper = helper
        self.connector = connector

    def execute(self, *args, **kwargs):
        LOG.debug('ArrangeHostTask.execute %s', self.connector)
        host_id = self.helper.arrange_host(self.connector)
        return host_id


class ExposeLUNTask(task.Task):
    def __init__(self, helper, volume, lun_data):
        LOG.debug('ExposeLUNTask.__init__ %s', lun_data)
        super(ExposeLUNTask, self).__init__()
        self.helper = helper
        self.lun_data = lun_data
        self.volume = volume

    def execute(self, host_id):
        LOG.debug('ExposeLUNTask.execute %(vol)s %(host)s'
                  % {'vol': self.lun_data,
                     'host': host_id})
        self.helper.expose_lun(self.volume, self.lun_data, host_id)

    def revert(self, result, host_id, *args, **kwargs):
        LOG.warning(_LW('ExposeLUNTask.revert %(vol)s %(host)s'),
                    {'vol': self.lun_data, 'host': host_id})
        if isinstance(result, failure.Failure):
            LOG.warning(_LW('ExposeLUNTask.revert: Nothing to revert'))
            return
        else:
            LOG.warning(_LW('ExposeLUNTask.revert: hide_lun'))
            self.helper.hide_lun(self.volume, self.lun_data, host_id)


class AttachSnapTask(task.Task):
    def __init__(self, helper, emc_snap):
        LOG.debug('AttachSnapTask.__init__ %s', emc_snap)
        super(AttachSnapTask, self).__init__()
        self.helper = helper
        self.emc_snap = emc_snap

    def execute(self, host_id):
        LOG.debug('AttachSnapTask.execute %(snap)s %(host)s'
                  % {'snap': self.emc_snap,
                     'host': host_id})
        self.helper.attach_snap(self.emc_snap, host_id)

    def revert(self, result, host_id, *args, **kwargs):
        LOG.warning(_LW('AttachSnapTask.revert %(snap)s %(host)s'),
                    {'snap': self.emc_snap, 'host': host_id})
        if isinstance(result, failure.Failure):
            LOG.warning(_LW('AttachSnapTask.revert: Nothing to revert'))
            return
        else:
            LOG.warning(_LW('AttachSnapTask.revert: detach_snap'))
            self.helper.detach_snap(self.emc_snap)


class GetConnectionInfoTask(task.Task):
    def __init__(self, helper, volume, lun_data, connector, *argv, **kwargs):
        LOG.debug('GetConnectionInfoTask.__init__ %(vol)s %(conn)s',
                  {'vol': lun_data, 'conn': connector})
        super(GetConnectionInfoTask, self).__init__(provides='connection_info')
        self.helper = helper
        self.lun_data = lun_data
        self.connector = connector
        self.volume = volume

    def execute(self, host_id):
        LOG.debug('GetConnectionInfoTask.execute %(vol)s %(conn)s %(host)s',
                  {'vol': self.lun_data, 'conn': self.connector,
                   'host': host_id})
        snap_id = (None if 'snap_id' not in self.lun_data
                   else self.lun_data['snap_id'])
        return self.helper.get_connection_info(self.volume,
                                               self.connector,
                                               self.lun_data['currentNode'],
                                               self.lun_data['id'],
                                               host_id,
                                               snap_id)


def ignore_exception(func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except Exception as ex:
        LOG.warning(_LW('Error occurred but ignored. Function: %(func)s, '
                        'args: %(ar)s, kwargs: %(kw)s, exception: %(ex)s'),
                    {'func': func.__name__, 'ar': args,
                     'kw': kwargs, 'ex': ex})


@contextlib.contextmanager
def assure_cleanup(enter_func, exit_func, use_internal, *args, **kwargs):
    try:
        LOG.debug('Entering context. Function: %s, args: %s, kwargs: %s',
                  enter_func.__name__, args, kwargs)
        enter_return = enter_func(*args, **kwargs)
        if use_internal:
            args = (enter_return, )
        yield enter_return
    finally:
        LOG.debug('Exiting context. Function: %s, args: %s, kwargs: %s',
                  exit_func.__name__, args, kwargs)
        ignore_exception(exit_func, *args, **kwargs)


@decorate_all_methods(log_enter_exit)
class EMCUnityHelper(object):
    stats = {'driver_version': VERSION,
             'storage_protocol': None,
             'free_capacity_gb': 'unknown',
             'reserved_percentage': 0,
             'total_capacity_gb': 'unknown',
             'vendor_name': 'EMC',
             'volume_backend_name': None}

    LUN_NOT_MODIFY_ERROR = 108007456
    RESOURCE_ALREADY_EXIST = 108007952
    RESOURCE_DOES_NOT_EXIST = 131149829

    def __init__(self, conf):
        self.configuration = conf
        self.configuration.append_config_values(loc_opts)
        self.configuration.append_config_values(san.san_opts)
        self.storage_protocol = conf.storage_protocol
        self.supported_storage_protocols = ('iSCSI', 'FC')
        if self.storage_protocol not in self.supported_storage_protocols:
            msg = _('storage_protocol %(invalid)s is not supported. '
                    'The valid one should be among %(valid)s.') % {
                'invalid': self.storage_protocol,
                'valid': self.supported_storage_protocols}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        self.active_storage_ip = self.configuration.san_ip
        self.storage_username = self.configuration.san_login
        self.storage_password = self.configuration.san_password
        self.max_over_subscription_ratio = (
            self.configuration.max_over_subscription_ratio)
        self.lookup_service_instance = None
        # Here we use group config to keep same as cinder manager
        zm_conf = Configuration(manager.volume_manager_opts)
        if (zm_conf.safe_get('zoning_mode') == 'fabric' or
                self.configuration.safe_get('zoning_mode') == 'fabric'):
            from cinder.zonemanager.fc_san_lookup_service \
                import FCSanLookupService
            self.lookup_service_instance = \
                FCSanLookupService(configuration=self.configuration)
        self.client = EMCUnityRESTClient(self.active_storage_ip, 443,
                                         self.storage_username,
                                         self.storage_password,
                                         debug=CONF.debug)
        system_info = self.client.get_basic_system_info(
            ('name', 'softwareVersion'))
        if not system_info:
            msg = _('Basic system information is unavailable.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        self.storage_serial_number = system_info[0]['name']
        conf_pools = self.configuration.safe_get("storage_pool_names")
        # When managed_all_pools is True, the storage_pools_map will be
        # updated in update_volume_stats.
        self.is_managing_all_pools = False if conf_pools else True
        self.storage_pools_map = self._get_managed_storage_pools_map(
            conf_pools)
        self.thin_enabled = False
        self.storage_targets = self._get_storage_targets()

    def _get_managed_storage_pools_map(self, pools):

        managed_pools = self.client.get_pools(('name', 'id'))
        if pools:
            storage_pool_names = set([po.strip() for po in pools.split(",")])
            array_pool_names = set([po['name'] for po in managed_pools])
            non_exist_pool_names = storage_pool_names.difference(
                array_pool_names)
            storage_pool_names.difference_update(non_exist_pool_names)
            if not storage_pool_names:
                msg = _("All the specified storage pools to be managed "
                        "do not exist. Please check your configuration. "
                        "Non-existent "
                        "pools: %s") % ",".join(non_exist_pool_names)
                raise exception.VolumeBackendAPIException(data=msg)
            if non_exist_pool_names:
                LOG.warning(_LW("The following specified storage pools "
                                "do not exist: %(unexist)s. "
                                "This host will only manage the storage "
                                "pools: %(exist)s"),
                            {'unexist': ",".join(non_exist_pool_names),
                             'exist': ",".join(storage_pool_names)})
            else:
                LOG.debug("This host will manage the storage pools: %s.",
                          ",".join(storage_pool_names))

            managed_pools = filter(lambda po: po['name'] in storage_pool_names,
                                   managed_pools)
        else:
            LOG.debug("No storage pool is configured. This host will "
                      "manage all the pools on the Unity system.")

        return self._build_storage_pool_id_map(managed_pools)

    def _build_storage_pool_id_map(self, pools):
        return {po['name']: po['id'] for po in pools}

    def _get_iscsi_targets(self):
        res = {'a': [], 'b': []}
        node_dict = {}
        for node in self.client.get_iscsi_nodes(('id', 'name')):
            node_dict[node['id']] = node['name']
        fields = ('id', 'ipAddress', 'ethernetPort', 'iscsiNode')
        pat = re.compile(r'sp(a|b)', flags=re.IGNORECASE)
        for portal in self.client.get_iscsi_portals(fields):
            eth_id = portal['ethernetPort']['id']
            node_id = portal['iscsiNode']['id']
            m = pat.match(eth_id)
            if m:
                sp = m.group(1).lower()
                item = (node_dict[node_id], portal['ipAddress'],
                        portal['id'])
                res[sp].append(item)
            else:
                LOG.warning(_LW('SP of %s is unknown'), portal['id'])
        return res

    def _get_fc_targets(self):
        res = {'a': [], 'b': []}
        storage_processor = 'storageProcessor'
        fields = ('id', 'wwn', storage_processor)
        pat = re.compile(r'sp(a|b)', flags=re.IGNORECASE)
        for port in self.client.get_fc_ports(fields):
            sp_id = port[storage_processor]['id']
            m = pat.match(sp_id)
            if m:
                sp = m.group(1).lower()
                wwn = port['wwn'].replace(':', '')
                node_wwn = wwn[0:16]
                port_wwn = wwn[16:32]
                item = (node_wwn, port_wwn, port['id'])
                res[sp].append(item)
            else:
                LOG.warning(_LW('SP of %s is unknown'), port['id'])
        return res

    def _get_storage_targets(self):
        if self.storage_protocol == 'iSCSI':
            return self._get_iscsi_targets()
        elif self.storage_protocol == 'FC':
            return self._get_fc_targets()
        else:
            return {'a': [], 'b': []}

    def _get_volumetype_extraspecs(self, volume):
        specs = {}

        type_id = volume['volume_type_id']
        if type_id is not None:
            specs = volume_types.get_volume_type_extra_specs(type_id)

        return specs

    def _get_qos_specs(self, volume_type):
        specs_id = (None if volume_type is None
                    else volume_type['qos_specs_id'])
        specs = (None if volume_type is None
                 else volume_types.get_volume_type_qos_specs(
                     volume_type['id']))
        emc_qos = {}

        if specs_id and specs and specs['qos_specs']:
            specs = specs['qos_specs']

            # We do not handle front-end qos specs
            if specs['consumer'] != QOS_CONSUMER_FRONTEND:
                emc_qos = specs['specs']

        return emc_qos, specs_id

    def _load_provider_location(self, provider_location):
        pl_dict = {}
        for item in provider_location.split('|'):
            k_v = item.split('^')
            if len(k_v) == 2 and k_v[0]:
                pl_dict[k_v[0]] = k_v[1]
        return pl_dict

    def _dumps_provider_location(self, pl_dict):
        return '|'.join([k + '^' + pl_dict[k] for k in pl_dict])

    def get_lun_by_id(self, lun_id,
                      fields=('id', 'type', 'name',
                              'currentNode', 'hostAccess',
                              'pool')):
        data = self.client.get_lun_by_id(lun_id, fields)
        if not data:
            raise exception.VolumeBackendAPIException(
                data=_('Cannot find lun with id : {}').format(lun_id))
        return data[0]

    def _get_target_storage_pool_name(self, volume):
        return vol_utils.extract_host(volume['host'], 'pool')

    def _get_target_storage_pool_id(self, volume):
        name = self._get_target_storage_pool_name(volume)
        return self.storage_pools_map[name]

    def _get_group_id_by_name(self, group_name, raise_exp_flag=True):
        """Gets the group id by the group name."""
        group_id = self.client.get_group_by_name(group_name, {'id'})
        if not group_id:
            msg = (_('Failed to get ID for Consistency Group %s') %
                   group_name)
            if raise_exp_flag:
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                LOG.warning(_LW('%s'), msg)
                return None
        return group_id[0]['id']

    def _get_snap_id_by_name(self, snap_name, raise_exp_flag=True):
        """Gets the snap id by the snap name."""
        snap_id = self.client.get_snap_by_name(snap_name, {'id'})
        if not snap_id:
            msg = (_('Failed to get ID for Snapshot %s') %
                   snap_name)
            if raise_exp_flag:
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                LOG.warning(_LW('%s'), msg)
                return None
        return snap_id[0]['id']

    def create_consistencygroup(self, group):
        """Creates a consistency group."""
        cg_id = group.id
        model_update = {'status': 'available'}
        err, res = self.client.create_consistencygroup(cg_id)
        if err:
            # Ignore the error if CG already exist
            if err['errorCode'] == self.RESOURCE_ALREADY_EXIST:
                LOG.warning(_LW('CG %s with this name already exists'),
                            cg_id)
            else:
                raise exception.VolumeBackendAPIException(data=err['messages'])
        return model_update

    def delete_consistencygroup(self, group, volumes):
        """Deletes a consistency group."""
        cg_id = self._get_group_id_by_name(group.id, False)
        model_update = {'status': group.status}
        if cg_id is not None:
            err, res = self.client.delete_consistencygroup(cg_id)
            if err:
                # Ignore the error if CG doesn't exist
                if err['errorCode'] == self.RESOURCE_DOES_NOT_EXIST:
                    LOG.warning(
                        _LW("CG %(cg_name)s does not exist."),
                        {'cg_name': cg_id, 'msg': err['messages']})
                else:
                    raise exception.VolumeBackendAPIException(
                        data=err['messages'])
        for volume in volumes:
                volume['status'] = 'deleted'
        return model_update, volumes

    def update_consistencygroup(self, group, add_volumes, remove_volumes):
        """Adds or removes LUN(s) to/from an existing consistency group"""
        model_update = {'status': 'available'}
        cg_id = self._get_group_id_by_name(group.id)
        add_luns = [six.text_type(self._extra_lun_or_snap_id(vol))
                    for vol in add_volumes] if add_volumes else []
        remove_luns = [six.text_type(self._extra_lun_or_snap_id(vol))
                       for vol in remove_volumes] if remove_volumes else []
        err, res = self.client.update_consistencygroup(cg_id, add_luns,
                                                       remove_luns)
        if err:
            raise exception.VolumeBackendAPIException(data=err['messages'])
        return model_update, None, None

    def create_cgsnapshot(self, cgsnapshot, snapshots):
        """Creates a cgsnapshot (snap group)."""
        cg_name = self._get_group_id_by_name(cgsnapshot['consistencygroup_id'])
        snap_name = cgsnapshot['id']
        snap_desc = cgsnapshot['description']
        err, res = self.client.create_snap(cg_name, snap_name, snap_desc)
        if err:
            # Ignore the error if CG Snapshot already exists
            if err['errorCode'] == self.RESOURCE_ALREADY_EXIST:
                LOG.warning(
                    _LW('CG Snapshot %s with this name already exists'),
                    snap_name)
            else:
                raise exception.VolumeBackendAPIException(data=err['messages'])
        model_update = {'status': 'available'}
        for snapshot in snapshots:
            snapshot['status'] = 'available'
        return model_update, snapshots

    def delete_cgsnapshot(self, cgsnapshot, snapshots):
        """Deletes a cgsnapshot (snap group)."""
        snap_id = self._get_snap_id_by_name(cgsnapshot['id'], False)
        model_update = {'status': cgsnapshot['status']}
        if snap_id is not None:
            err, resp = self.client.delete_snap(snap_id)
            if err:
                # Ignore the error if CG Snapshot doesn't exist
                if err['errorCode'] == self.RESOURCE_DOES_NOT_EXIST:
                    LOG.warning(
                        _LW("CG Snapshot %(cg_name)s does not exist."),
                        {'cg_name': snap_id, 'msg': err['messages']})
                else:
                    raise exception.VolumeBackendAPIException(
                        data=err['messages'])
        for snapshot in snapshots:
            snapshot['status'] = 'deleted'
        return model_update, snapshots

    def create_volume(self, volume):
        name = volume['name']
        size = volume['size'] * GiB
        extra_specs = self._get_volumetype_extraspecs(volume)
        qos_specs, qos_specs_id = self._get_qos_specs(volume['volume_type'])
        k = 'storagetype:provisioning'
        is_thin = True
        if k in extra_specs:
            v = extra_specs[k].lower()
            if v == 'thin':
                is_thin = True
            elif v == 'thick':
                is_thin = False
            else:
                msg = _('Value %(v)s of %(k)s is invalid') % {'k': k, 'v': v}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        limit_policy_id = None
        if qos_specs_id:
            limit_policy = self.client.get_limit_policy(qos_specs_id)
            if not limit_policy:
                limit_policy = self.client.create_limit_policy(
                    qos_specs_id,
                    max_iops=qos_specs.get(QOS_MAX_IOPS, None),
                    max_kbps=qos_specs.get(QOS_MAX_BWS, None))
            else:
                limit_policy = limit_policy[0]
            limit_policy_id = limit_policy['id']
        err, lun = self.client.create_lun(
            self._get_target_storage_pool_id(volume), name, size,
            is_thin=is_thin,
            display_name=(None if 'display_name' not in volume
                          else volume['display_name']),
            limit_policy_id=limit_policy_id)
        if err:
            raise exception.VolumeBackendAPIException(data=err['messages'])

        if volume.get('consistencygroup_id'):
            cg_id = (
                self._get_group_id_by_name(volume.get('consistencygroup_id')))
            err, res = self.client.update_consistencygroup(cg_id, [lun['id']])
            if err:
                raise exception.VolumeBackendAPIException(data=err['messages'])

        pl_dict = {'system': self.storage_serial_number,
                   'type': 'lun',
                   'id': lun['id']}
        model_update = {'provider_location':
                        self._dumps_provider_location(pl_dict)}
        volume['provider_location'] = model_update['provider_location']
        return model_update

    @staticmethod
    def _get_lun_id_of_snap(emc_snap):
        return emc_snap['storageResource']['id']

    def _extra_lun_or_snap_id(self, volume):
        if volume.get('provider_location') is None:
            return None
        pl_dict = self._load_provider_location(volume['provider_location'])
        res_type = pl_dict.get('type', None)
        if 'lun' == res_type or 'snap' == res_type:
            if pl_dict.get('id', None):
                return pl_dict['id']
        msg = _('Fail to find LUN ID of %(vol)s in from %(pl)s') % {
            'vol': volume['name'], 'pl': volume['provider_location']}
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def delete_volume(self, volume):
        lun_id = self._extra_lun_or_snap_id(volume)
        err, resp = self.client.delete_lun(lun_id)
        if err:
            if not self.client.get_lun_by_id(lun_id):
                LOG.warning(_LW("LUN %(name)s is already deleted or does not "
                                "exist. Message: %(msg)s"),
                            {'name': volume['name'], 'msg': err['messages']})
            else:
                raise exception.VolumeBackendAPIException(data=err['messages'])

    def create_snapshot(self, snapshot, name, snap_desc):
        """This function will create a snapshot of the given volume."""
        LOG.debug('Entering EMCUnityHelper.create_snapshot.')
        snap_id = self._create_snapshot(snapshot['volume'],
                                        name,
                                        snap_desc)
        pl_dict = {'system': self.storage_serial_number,
                   'type': 'snap',
                   'id': snap_id}
        model_update = {'provider_location':
                        self._dumps_provider_location(pl_dict)}
        snapshot['provider_location'] = model_update['provider_location']
        return model_update

    def _create_snapshot(self, volume, snap_name, snap_desc=None):
        lun_id = self._extra_lun_or_snap_id(volume)
        if not lun_id:
            msg = _('Failed to get LUN ID for volume %s') % volume['name']
            raise exception.VolumeBackendAPIException(data=msg)
        err, snap_id = self.client.create_snap(
            lun_id, snap_name, snap_desc)
        if err:
            raise exception.VolumeBackendAPIException(data=err['messages'])
        else:
            return snap_id

    def delete_snapshot(self, snapshot):
        """Gets the snap id by the snap name and delete the snapshot."""
        snap_id = self._extra_lun_or_snap_id(snapshot)
        if not snap_id:
            return
        err, resp = self.client.delete_snap(snap_id)
        if err:
            raise exception.VolumeBackendAPIException(data=err['messages'])

    def extend_volume(self, volume, new_size):
        lun_id = self._extra_lun_or_snap_id(volume)
        err, resp = self.client.extend_lun(lun_id, new_size * GiB)
        if err:
            if err['errorCode'] == self.LUN_NOT_MODIFY_ERROR:
                LOG.warning(
                    _LW("Lun %(lun)s is already expanded. Message: %(msg)s"),
                    {'lun': volume['name'], 'msg': err['messages']})
            else:
                raise exception.VolumeBackendAPIException(data=err['messages'])

    def _extract_iscsi_uids(self, connector):
        if 'initiator' not in connector:
            if self.storage_protocol == 'iSCSI':
                msg = _('Host %s has no iSCSI initiator') % connector['host']
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                return ()
        return [connector['initiator']]

    def _extract_fc_uids(self, connector):
        if 'wwnns' not in connector or 'wwpns' not in connector:
            if self.storage_protocol == 'FC':
                msg = _('Host %s has no FC initiators') % connector['host']
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                return ()
        wwnns = connector['wwnns']
        wwpns = connector['wwpns']
        wwns = [(node + port).upper() for node, port in zip(wwnns, wwpns)]
        return map(lambda wwn: re.sub(r'\S\S',
                                      lambda m: m.group(0) + ':',
                                      wwn,
                                      len(wwn) / 2 - 1),
                   wwns)

    def _categorize_initiators(self, connector):
        if self.storage_protocol == 'iSCSI':
            initiator_uids = self._extract_iscsi_uids(connector)
        elif self.storage_protocol == 'FC':
            initiator_uids = self._extract_fc_uids(connector)
        else:
            initiator_uids = []
        registered_initiators = []
        orphan_initiators = []
        new_initiator_uids = []
        for initiator_uid in initiator_uids:
            initiator = self.client.get_initiator_by_uid(
                initiator_uid, ('parentHost',))
            if initiator:
                initiator = initiator[0]
                if 'parentHost' in initiator and initiator['parentHost']:
                    registered_initiators.append(initiator)
                else:
                    orphan_initiators.append(initiator)
            else:
                new_initiator_uids.append(initiator_uid)
        return registered_initiators, orphan_initiators, new_initiator_uids

    def _extract_host(self, registered_initiators, hostname=None):
        """Return host object by initiators or hostname."""
        if registered_initiators:
            reg_id = registered_initiators[0]['parentHost']['id']
            return self.client.get_host_by_id(
                reg_id, ('id', 'name', 'hostLUNs'))[0]
        if hostname:
            host = self.client.get_host_by_name(
                hostname, ('id', 'name', 'hostLUNs'))
            if host:
                return host[0]
        return None

    def _create_initiators(self, new_initiator_uids, host_id):
        for initiator_uid in new_initiator_uids:
            err, initiator = self.client.create_initiator(initiator_uid,
                                                          host_id)
            if err:
                if err['httpStatusCode'] in (409,):
                    LOG.warning(_LW('Initiator %s had been created.'),
                                initiator_uid)
                    return
                msg = _('Failed to create initiator %s') % initiator_uid
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def _register_initiators(self, orphan_initiators, host_id):
        for initiator in orphan_initiators:
            err, resp = self.client.register_initiator(initiator['id'],
                                                       host_id)
            if err:
                msg = _('Failed to register initiator %(initiator)s '
                        'to %(host)s') % {'initiator': initiator['id'],
                                          'host': host_id}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def _build_init_targ_map(self, mapping):
        """Function to process data from lookup service."""
        #   mapping
        #   {
        #        <San name>: {
        #            'initiator_port_wwn_list':
        #            ('200000051e55a100', '200000051e55a121'..)
        #            'target_port_wwn_list':
        #            ('100000051e55a100', '100000051e55a121'..)
        #        }
        #   }
        target_wwns = []
        init_targ_map = {}

        for san_name in mapping:
            mymap = mapping[san_name]
            for target in mymap['target_port_wwn_list']:
                if target not in target_wwns:
                    target_wwns.append(target)
            for initiator in mymap['initiator_port_wwn_list']:
                init_targ_map[initiator] = mymap['target_port_wwn_list']
        LOG.debug("target_wwns: %s", target_wwns)
        LOG.debug("init_targ_map: %s", init_targ_map)
        return target_wwns, init_targ_map

    def arrange_host(self, connector):
        registered_initiators, orphan_initiators, new_initiator_uids = \
            self._categorize_initiators(connector)
        host = self._extract_host(registered_initiators,
                                  connector['host'])
        if host is None:
            err, host = self.client.create_host(connector['host'])

            if err:
                msg = _('Failed to create host %s.') % connector['host']
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        host_id = host['id']
        # Occupy HLU 0 to avoid LUNZ issue
        if 'hostLUNs' not in host or not host['hostLUNs']:
            err, lun = self.client.create_lun(
                self.storage_pools_map.values()[0],
                EMC_OPENSTACK_DUMMY_LUN,
                GiB)
            if err:
                msg = _('Failed to create dummy LUN'
                        ' for host %s') % connector['host']
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=err['messages'])
            self.client.expose_lun(lun['id'], None, None, host_id)
        self._create_initiators(new_initiator_uids, host_id)
        self._register_initiators(orphan_initiators, host_id)
        return host_id

    def expose_lun(self, volume, lun_data, host_id):
        lun_id = lun_data['id']
        lun_cg = (self._get_group_id_by_name(volume.get('consistencygroup_id'))
                  if volume.get('consistencygroup_id') else None)
        host_access = (lun_data['hostAccess'] if 'hostAccess' in lun_data
                       else [])
        if self.lookup_service_instance and self.storage_protocol == 'FC':
            @lockutils.synchronized('emc-unity-host-' + host_id,
                                    "emc-unity-host-", True)
            def _expose_lun():
                return self.client.expose_lun(lun_id,
                                              lun_cg,
                                              host_access,
                                              host_id)

            err, resp = _expose_lun()
        else:
            err, resp = self.client.expose_lun(lun_id,
                                               lun_cg,
                                               host_access,
                                               host_id)
        if err:
            if err['errorCode'] in (0x6701020,):
                LOG.warning(_LW('LUN %(lun)s backing %(vol)s had been '
                            'exposed to %(host)s.'),
                            {'lun': lun_id, 'vol': lun_data['name'],
                             'host': host_id})
                return
            msg = _('Failed to expose %(lun)s to %(host)s.') % \
                {'lun': lun_id, 'host': host_id}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def attach_snap(self, emc_snap, host_id):
        emc_snap_id = emc_snap['id']
        if self.lookup_service_instance and self.storage_protocol == 'FC':
            @lockutils.synchronized('emc-unity-host-' + host_id,
                                    "emc-unity-host-", True)
            def _attach_snap():
                return self.client.attach_snap(emc_snap_id, host_id)

            err, resp = _attach_snap()
        else:
            err, resp = self.client.attach_snap(emc_snap_id, host_id)
        if err:
            if err['errorCode'] in (0x6000bdc, 100666332):
                # One snapshot can be attached to ONLY one host,
                # so cannot figure out the error is caused by attaching snap
                # to the same host twice (retry) or attaching snap to two
                # hosts. The later case should raise exception.
                LOG.warning(_LW('EMC snapshot %(snap)s had been '
                            'attached to %(host)s.'),
                            {'snap': emc_snap_id, 'host': host_id})
                return
            msg = _('Failed to attach %(snap)s to %(host)s.') % \
                {'snap': emc_snap_id, 'host': host_id}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _get_driver_volume_type(self):
        if self.storage_protocol == 'iSCSI':
            return 'iscsi'
        elif self.storage_protocol == 'FC':
            return 'fibre_channel'
        else:
            return 'unknown'

    def _get_fc_zone_info(self, connector, targets):
        initiator_wwns = connector['wwpns']
        target_wwns = [item[1] for item in targets]
        mapping = self.lookup_service_instance. \
            get_device_mapping_from_network(initiator_wwns,
                                            target_wwns)
        target_wwns, init_targ_map = self._build_init_targ_map(mapping)
        return {'initiator_target_map': init_targ_map,
                'target_wwn': target_wwns}

    def get_connection_info(self, volume, connector, current_sp_node,
                            lun_id, host_id, snap_id=None):
        data = {'target_discovered': True,
                'target_lun': 'unknown',
                'volume_id': volume['id']}

        spa_targets = list(self.storage_targets['a'])
        spb_targets = list(self.storage_targets['b'])
        random.shuffle(spa_targets)
        random.shuffle(spb_targets)
        # Owner SP is preferred
        if current_sp_node == 0:
            targets = spa_targets + spb_targets
        else:
            targets = spb_targets + spa_targets

        if not targets:
            msg = _('Connection information is unavailable '
                    'because no target ports are available in the system.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if snap_id is None:
            host_lun_type = self.client.HostLUNTypeEnum_LUN
        else:
            host_lun_type = self.client.HostLUNTypeEnum_LUN_Snap
        host_lun = self.client.get_host_lun_by_ends(host_id, lun_id,
                                                    snap_id,
                                                    use_type=host_lun_type,
                                                    fields=('hlu',))
        if not host_lun or 'hlu' not in host_lun[0]:
            msg = _('Can not get the hlu information of host %s.') % host_id
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        data['target_lun'] = host_lun[0]['hlu']
        if self.storage_protocol == 'iSCSI':
            data['target_iqn'] = targets[0][0]
            data['target_portal'] = '%s:3260' % targets[0][1]
            data['target_iqns'] = [t[0] for t in targets]
            data['target_portals'] = ['%s:3260' % t[1] for t in targets]
            data['target_luns'] = [host_lun[0]['hlu']] * len(targets)
        elif self.storage_protocol == 'FC':
            host = self.client.get_host_by_id(host_id,
                                              ('fcHostInitiators',))
            if not host or not host[0]['fcHostInitiators']:
                msg = _('Connection information is unavailable because '
                        'no FC initiator can access resources in %s') % host_id
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            host = host[0]
            logined_fc_set = set()
            for initiator in host['fcHostInitiators']:
                paths = self.client.get_initiator_paths_by_initiator_id(
                    initiator['id'], ('fcPort', 'isLoggedIn'))
                for path in paths:
                    if path['isLoggedIn']:
                        logined_fc_set.add(path['fcPort']['id'])
            if self.lookup_service_instance:
                zone_info = self._get_fc_zone_info(connector, targets)
                data.update(zone_info)
            else:
                accessible_targets = filter(lambda entry:
                                            entry[2] in logined_fc_set,
                                            targets)
                if not accessible_targets:
                    msg = _('Connection information is unavailable '
                            'because no FC initiator in %s has paths '
                            'to the system.') % host_id
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                data['target_wwn'] = map(lambda entry: entry[1],
                                         accessible_targets)
            LOG.debug('FC Target WWNs accessible to %(host)s: %(targets)s.'
                      % {'host': connector['host'],
                         'targets': data['target_wwn']})

        connection_info = {
            'driver_volume_type': self._get_driver_volume_type(),
            'data': data}
        return json.dumps(connection_info)

    def initialize_connection(self, volume, connector):
        flow_name = 'initialize_connection'
        volume_flow = linear_flow.Flow(flow_name)
        lun_id = self._extra_lun_or_snap_id(volume)
        lun_data = self.get_lun_by_id(lun_id)
        volume_flow.add(ArrangeHostTask(self, connector),
                        ExposeLUNTask(self, volume, lun_data),
                        GetConnectionInfoTask(self, volume, lun_data,
                                              connector))

        flow_engine = taskflow.engines.load(volume_flow,
                                            store={})
        flow_engine.run()
        return json.loads(flow_engine.storage.fetch('connection_info'))

    def initialize_connection_snap(self, emc_snap, connector):
        flow_name = 'initialize_connection_snap'
        snap_flow = linear_flow.Flow(flow_name)

        lun_data = self.get_lun_by_id(self._get_lun_id_of_snap(emc_snap))
        lun_data['snap_id'] = emc_snap['id']
        snap_flow.add(ArrangeHostTask(self, connector),
                      AttachSnapTask(self, emc_snap),
                      GetConnectionInfoTask(self, emc_snap, lun_data,
                                            connector))

        flow_engine = taskflow.engines.load(snap_flow, store={})
        flow_engine.run()
        return json.loads(flow_engine.storage.fetch('connection_info'))

    def hide_lun(self, volume, lun_data, host_id):
        lun_id = lun_data['id']
        lun_cg = (self._get_group_id_by_name(volume.get('consistencygroup_id'))
                  if volume.get('consistencygroup_id') else None)
        host_access = (lun_data['hostAccess'] if 'hostAccess' in lun_data
                       else [])
        err, resp = self.client.hide_lun(lun_id,
                                         lun_cg,
                                         host_access,
                                         host_id)
        if err:
            if err['errorCode'] in (0x6701020,):
                LOG.warning(_LW('LUN %(lun)s backing %(vol) had been '
                                'hidden from %(host)s.'), {
                            'lun': lun_id, 'vol': lun_data['name'],
                            'host': host_id})
                return
            msg = _('Failed to hide %(vol)s from host %(host)s '
                    ': %(msg)s.') % {'vol': lun_data['name'],
                                     'host': host_id, 'msg': resp}
            raise exception.VolumeBackendAPIException(data=msg)

    def detach_snap(self, emc_snap):
        emc_snap_id = emc_snap['id']
        attached_host_id = None
        host_access = emc_snap.get('hostAccess', [])
        if host_access:
            attached_host_id = host_access[0].get('host', {}).get('id', '')
        err, resp = self.client.detach_snap(emc_snap_id)
        if err:
            # Detaching snapshot from host more than once will not return
            # error.
            msg = _('Failed to detach %(snap)s from host %(host)s '
                    ': %(msg)s.') % {'snap': emc_snap['name'],
                                     'host': attached_host_id, 'msg': resp}
            raise exception.VolumeBackendAPIException(data=msg)

    def get_fc_zone_info_for_empty_host(self, connector, host_id):
        @lockutils.synchronized('emc-unity-host-' + host_id,
                                "emc-unity-host-", True)
        def _get_fc_zone_info_in_sync():
            if self.isHostContainsLUNs(host_id):
                return {}
            else:
                targets = self.storage_targets['a'] + self.storage_targets['b']
                return self._get_fc_zone_info(connector,
                                              targets)

        return {
            'driver_volume_type': self._get_driver_volume_type(),
            'data': _get_fc_zone_info_in_sync()}

    def terminate_connection(self, volume, connector, **kwargs):
        lun_id = self._extra_lun_or_snap_id(volume)
        registered_initiators, orphan_initiators, new_initiator_uids = \
            self._categorize_initiators(connector)
        host = self._extract_host(registered_initiators,
                                  connector['host'])
        if not host:
            LOG.warning(_LW("Host using %s is not found."), volume['name'])
        else:
            host_id = host['id']
            lun_data = self.get_lun_by_id(lun_id)
            self.hide_lun(volume, lun_data, host_id)

        if self.lookup_service_instance and self.storage_protocol == 'FC':
            return self.get_fc_zone_info_for_empty_host(connector, host_id)
        else:
            return

    def terminate_connection_snap(self, emc_snap, connector, **kwargs):
        registered_initiators, orphan_initiators, new_initiator_uids = \
            self._categorize_initiators(connector)
        host = self._extract_host(registered_initiators,
                                  connector['host'])
        if not host:
            LOG.warning(_LW("Host using %s is not found."), emc_snap['name'])
        else:
            self.detach_snap(emc_snap)

        if self.lookup_service_instance and self.storage_protocol == 'FC':
            return self.get_fc_zone_info_for_empty_host(connector, host['id'])

    def isHostContainsLUNs(self, host_id):
        host = self.client.get_host_by_id(host_id, ('hostLUNs',))
        if not host:
            return False
        else:
            luns = host[0]['hostLUNs']
            return True if luns else False

    def get_volume_stats(self, refresh=False):
        if refresh:
            self.update_volume_stats()
        return self.stats

    def update_volume_stats(self):
        LOG.debug("Updating volume stats")
        # Check if thin provisioning license is installed
        licenses = self.client.get_licenses(('id', 'isValid'))
        thin_license = filter(lambda lic: (lic['id'] == 'VNXE_PROVISION'
                                           and lic['isValid'] is True),
                              licenses)
        if thin_license:
            self.thin_enabled = True
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or 'EMCUnityDriver'
        data['storage_protocol'] = self.storage_protocol
        data['driver_version'] = VERSION
        data['vendor_name'] = "EMC"
        pools = self.client.get_pools(('name', 'sizeTotal', 'sizeFree',
                                       'id', 'sizeSubscribed'))
        if not self.is_managing_all_pools:
            pools = filter(lambda a: a['name'] in self.storage_pools_map,
                           pools)
        else:
            self.storage_pools_map = self._build_storage_pool_id_map(pools)
        data['pools'] = map(
            lambda po: self._build_pool_stats(po), pools)
        self.stats = data
        self.storage_targets = self._get_storage_targets()
        LOG.debug('Volume Stats: %s', data)
        return self.stats

    def _build_pool_stats(self, pool):
        pool_stats = {
            'pool_name': pool['name'],
            'free_capacity_gb': pool['sizeFree'] / GiB,
            'total_capacity_gb': pool['sizeTotal'] / GiB,
            'provisioned_capacity_gb': pool['sizeSubscribed'] / GiB,
            'reserved_percentage': 0,
            'thin_provisioning_support': self.thin_enabled,
            'thick_provisioning_support': True,
            'consistencygroup_support': True,
            'max_over_subscription_ratio': self.max_over_subscription_ratio
        }
        return pool_stats

    def manage_existing_get_size(self, volume, ref):
        """Return size of volume to be managed by manage_existing."""
        if 'source-id' in ref:
            lun = self.client.get_lun_by_id(ref['source-id'],
                                            fields=['pool', 'sizeTotal'])
        elif 'source-name' in ref:
            lun = self.client.get_lun_by_name(ref['source-name'],
                                              fields=['pool', 'sizeTotal'])
        else:
            reason = _('Reference must contain source-id or source-name key.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=reason)

        # Check for existence of the lun
        if len(lun) == 0:
            reason = _('Find no lun with the specified id or name.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=reason)
        if lun[0]['pool']['id'] != self._get_target_storage_pool_id(volume):
            reason = _('The input lun %s is not in a manageable '
                       'pool backend.') % lun[0]['id']
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=reason)
        return lun[0]['sizeTotal'] / GiB

    def manage_existing(self, volume, ref):
        """Manage an existing lun in the array."""
        if 'source-id' in ref:
            lun_id = ref['source-id']
        elif 'source-name' in ref:
            lun_id = self.client.get_lun_by_name(ref['source-name'])[0]['id']
        else:
            reason = _('Reference must contain source-id or source-name key.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=reason)
        self.client.modify_lun_name(lun_id, volume['name'])

        pl_dict = {'system': self.storage_serial_number,
                   'type': 'lun',
                   'id': lun_id}
        model_update = {
            'provider_location': self._dumps_provider_location(pl_dict)}
        return model_update


@decorate_all_methods(log_enter_exit)
class EMCUnityDriver(san.SanDriver):
    """EMC VMXe Driver."""

    def __init__(self, *args, **kwargs):
        super(EMCUnityDriver, self).__init__(*args, **kwargs)
        self.helper = EMCUnityHelper(self.configuration)

    def check_for_setup_error(self):
        pass

    def create_consistencygroup(self, context, group):
        return self.helper.create_consistencygroup(group)

    def delete_consistencygroup(self, context, group):
        volumes = self.db.volume_get_all_by_group(context, group.id)
        return self.helper.delete_consistencygroup(group, volumes)

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        return self.helper.update_consistencygroup(group,
                                                   add_volumes, remove_volumes)

    def create_cgsnapshot(self, context, cgsnapshot):
        snapshots = self.db.snapshot_get_all_for_cgsnapshot(
            context, cgsnapshot['id'])
        return self.helper.create_cgsnapshot(cgsnapshot, snapshots)

    def delete_cgsnapshot(self, context, cgsnapshot):
        snapshots = self.db.snapshot_get_all_for_cgsnapshot(
            context, cgsnapshot['id'])
        return self.helper.delete_cgsnapshot(cgsnapshot, snapshots)

    def create_volume(self, volume):
        return self.helper.create_volume(volume)

    def _disconnect_device(self, conn):
        conn['connector'].disconnect_volume(conn['conn']['data'],
                                            conn['device'])

    def _create_volume_from_snapshot(self, volume, emc_snap, size_in_m=None):
        model_update = None
        try:
            model_update = self.helper.create_volume(volume)
            conn_props = utils.brick_get_connector_properties()

            with assure_cleanup(self.helper.initialize_connection_snap,
                                self.helper.terminate_connection_snap,
                                False, emc_snap,
                                conn_props) as src_conn_info, \
                assure_cleanup(self._connect_device,
                               self._disconnect_device,
                               True, src_conn_info) as src_attach_info, \
                assure_cleanup(self.helper.initialize_connection,
                               self.helper.terminate_connection,
                               False, volume,
                               conn_props) as dest_conn_info, \
                assure_cleanup(self._connect_device,
                               self._disconnect_device,
                               True, dest_conn_info) as dest_attach_info:
                if size_in_m is None:
                    # If size is not specified, need to get the size from LUN
                    # of snapshot.
                    lun = self.helper.get_lun_by_id(
                        emc_snap['storageResource']['id'],
                        fields=('id', 'sizeTotal'))
                    size_in_m = lun['sizeTotal'] / units.Mi
                vol_utils.copy_volume(
                    src_attach_info['device']['path'],
                    dest_attach_info['device']['path'],
                    size_in_m,
                    self.configuration.volume_dd_blocksize)
        except Exception as ex:
            if model_update is not None:
                ignore_exception(self.helper.delete_volume, volume)
            msg = _('Failed to create cloned volume: {vol_id}, '
                    'source emc snapshot: {snap_name}. '
                    'Exception: {msg}').format(vol_id=volume['id'],
                                               snap_name=emc_snap['name'],
                                               msg=ex)
            raise exception.VolumeBackendAPIException(data=msg)

        return model_update

    def create_volume_from_snapshot(self, volume, snapshot):
        emc_snap = self.helper.client.get_snap_by_name(
            snapshot['name'],
            fields=('id', 'name', 'storageResource', 'hostAccess'))[0]
        return self._create_volume_from_snapshot(volume, emc_snap)

    def create_cloned_volume(self, volume, src_vref):
        """Creates cloned volume.

        1. Take an internal snapshot of source volume, and attach it.
        2. Create a new volume, and attach it.
        3. Copy from attached snapshot of step 1 to the volume of step 2.
        """

        src_snap_name = 'snap_clone_{}'.format(volume['id'])
        with assure_cleanup(self.helper._create_snapshot,
                            self.helper.client.delete_snap,
                            True, src_vref, src_snap_name) as src_snap_id:
            src_emc_snap = self.helper.client.get_snap_by_id(src_snap_id)
            LOG.debug('Internal snapshot for clone is created, '
                      'name: %s, id: %s.', src_snap_name, src_snap_id)
            return self._create_volume_from_snapshot(
                volume, src_emc_snap, size_in_m=volume['size'] * units.Ki)

    def delete_volume(self, volume):
        return self.helper.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        LOG.debug('Entering create_snapshot.')
        snapshotname = snapshot['name']
        volumename = snapshot['volume_name']
        snap_desc = snapshot['display_description']

        LOG.info(_LI('Create snapshot: %(snapshot)s: volume: %(volume)s'),
                 {'snapshot': snapshotname, 'volume': volumename})

        return self.helper.create_snapshot(
            snapshot, snapshotname, snap_desc)

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        LOG.info(_LI('Delete snapshot: %s'), snapshot['name'])
        return self.helper.delete_snapshot(snapshot)

    def extend_volume(self, volume, new_size):
        return self.helper.extend_volume(volume, new_size)

    @zm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        return self.helper.initialize_connection(volume, connector)

    @zm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        return self.helper.terminate_connection(volume, connector)

    def get_volume_stats(self, refresh=False):
        return self.helper.get_volume_stats(refresh)

    def update_volume_stats(self):
        return self.helper.update_volume_stats()

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing."""
        return self.helper.manage_existing_get_size(
            volume, existing_ref)

    def manage_existing(self, volume, existing_ref):
        return self.helper.manage_existing(
            volume, existing_ref)

    def unmanage(self, volume):
        pass
