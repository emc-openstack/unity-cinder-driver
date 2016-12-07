# Unity Cinder Driver

Copyright (c) 2016 EMC Corporation.
All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and limitations under the License.

## Overview

EMCUnityDriver (a.k.a. Unity Cinder Driver) is based on the SanDriver defined in Cinder, with the ability to create/delete, attach/detach volumes, create/delete snapshots, etc.

EMCUnityDriver performs the volume operations by Restful API management interface. 

## Supported OpenStack Release

This driver supports Kilo release.

## Requirements

* Unity with OE V4.1.x

## Supported Storage Protocol

* iSCSI
* Fibre Channel

## Supported Operations

The following operations will be supported by Unity Cinder Driver:

* Create volume
* Delete volume
* Extend volume
* Attach volume
* Detach volume
* Create snapshot
* Delete snapshot
* Copy Image to Volume
* Copy Volume to Image
* Create and delete consistency groups
* Create, list, and delete consistency group snapshots
* Modify consistency groups
* Clone volume

## Preparation

### Install Unity Cinder Driver

Unity Cinder Driver (EMCUnityDriver) is provided in the installer package consists of one python file:

        emc_unity.py

Copy the above python file to the `cinder/volume/drivers/emc/` directory of your OpenStack node(s) where cinder-volume is running.

### San Connection

To access the storage of Unity/Unity array, OpenStack nodes must have iSCSI or Fibre Channel connection with Unity/Unity.

#### iSCSI

Make sure that OpenStack nodes have ethernet connection with array's iSCSI ports.

#### Fibre Channel

Make sure OpenStack nodes's FC ports and array's FC ports are connected. If FC SAN Auto Zoning is not enabled, zoning need be set up so that OpenStack nodes' FC ports can access array's FC ports

## Backend Configuration

Make the following changes in `/etc/cinder/cinder.conf`:

Following are the elements specific to EMC Unity driver to be configured

        # Storage protocol
        storage_protocol = iSCSI
        # Storage pool which the backend is going to manage
        storage_pool_names = StoragePool00, StoragePool01
        # Unisphere IP
        san_ip = 192.168.1.58
        # Unisphere username and password
        san_login = Local/admin
        san_password = Password123!
        # Volume driver name
        volume_driver = cinder.volume.drivers.emc.emc_unity.EMCUnityDriver
        # backend's name
        volume_backend_name = Storage_ISCSI_01

        [database]
        max_pool_size=20
        max_overflow=30


* where `san_ip` is one of the Management IP address of the Unity array.
* where `storage_pool_names` is the comma separated pool names from which user wants to create volumes. The pools can be created using Unisphere for Unity. This option is optional. Refer to the "Multiple Pools Support" for more details
* Restart of cinder-volume service is needed to make the configuration change take effect.

## Authentication

Unity credentials are needed so that the driver could interact with the array. Credentials in Local and LDAP scopes are supported.

* Local user's san_login: Local/<username> or <username>
* LDAP user's san_login: <LDAP Domain Name>/<username>

## Multiple Pools Support

Option `storage_pool_names` is used to specify which storage pool or pools of a Unity/Unity system could be used by a Block Storage back end. To specify more than one pool, separate storage pool names with a comma.
If `storage_pool_names` is not configured, the Block Storage back end uses all the pools on the array.  The scheduler will choose which pool to place the volume based on the capacities and capabilities of the pools when more than one pools are managed by a Block Storage back end.
Note that the option 'storage_pool_name' has been deprecated, the user should use the option 'storage_pool_names' instead.

When a Block Storage back end is managing more than one pool, if the user wants to create a volume on a certain storage pool, a volume type with an extra spec specified storage pool should be created first, then the user can use this volume type to create the volume.

Here is an example about the volume type creation:

        cinder type-create "HighPerf"
        cinder type-key "HighPerf" set pool_name=Pool_02_SASFLASH volume_backend_name=unity_1

## Multi-backend configuration

        [DEFAULT]

        enabled_backends=backendA, backendB

        [backendA]

        storage_protocol = iSCSI
        san_ip = 192.168.1.58
        san_login = Local/admin
        san_password = Password123!
        volume_driver = cinder.volume.drivers.emc.emc_unity.EMCUnityDriver
        volume_backend_name = backendA

        [backendB]
        storage_protocol = FC
        storage_pool_names = StoragePool01
        san_ip = 192.168.1.58
        san_login = Local/admin
        san_password = Password123!
        volume_driver = cinder.volume.drivers.emc.emc_unity.EMCUnityDriver
        volume_backend_name = backendB

        [database]

        max_pool_size=20
        max_overflow=30

For more details on multi-backend, see [OpenStack Administration Guide](http://docs.openstack.org/admin-guide-cloud/content/multi_backend.html)

## Restriction of deployment

It is not suggested to deploy the driver on Nova Compute Node if "cinder upload-to-image --force True" is to be used against an in-use volume. Otherwise, "cinder upload-to-image --force True" will terminate the VM instance's data access to the volume.

## Thick/Thin Provisioning

Use Cinder Volume Type to define a provisioning type and the provisioning type could be either thin or thick.

Here is an example of how to create thick/thin volume. First create volume types. Then define extra specs for each volume type.

        cinder --os-username admin --os-tenant-name admin type-create "ThickVolume"
        cinder --os-username admin --os-tenant-name admin type-create "ThinVolume"
        cinder --os-username admin --os-tenant-name admin type-key "ThickVolume" set storagetype:provisioning=thick
        cinder --os-username admin --os-tenant-name admin type-key "ThinVolume" set storagetype:provisioning=thin

In the example above, two volume types are created: `ThickVolume` and `ThinVolume`. For `ThickVolume`, `storagetype:provisioning` is set to `thick`. Similarly for `ThinVolume`. If `storagetype:provisioning` is not specified, default value `thick` is adopted.

Volume Type names `ThickVolume` and `ThinVolume` are user-defined and can be any names. Extra spec key `storagetype:provisioning` has to be the exact name listed here. Extra spec value for `storagetype:provisioning` has to be either `thick` or `thin`.
During volume creation, if the driver find `storagetype:provisioning` in the extra spec of the Volume Type, it will create the volume of the provisioning type accordingly. Otherwise, the volume will be default to thick.

## FC SAN Auto Zoning

Unity cinder driver supports FC SAN auto zoning when ZoneManager is configured. Set "zoning_mode" to "fabric" in default section to enable this feature. For ZoneManager configuration, please refer to Block Storage official guide.

## Read-only Volumes

OpenStack support read-only volumes. Administrators can use following command to set a volume as read-only.

        cinder --os-username admin --os-tenant-name admin readonly-mode-update <volume> True

After a volume is marked as read-only, the driver will forward the information when a hypervisor is attaching the volume and the hypervisor will have implementation-specific way to make sure the volume is not written.

## Over subscription in thin provisioning

Over subscription allows that the sum of all volumes' capacity (provisioned capacity) to be larger than the pool's total capacity.

`max_over_subscription_ratio` in the back-end section is the ratio of provisioned capacity over total capacity.

The default value of `max_over_subscription_ratio` is 20.0, which means the provisioned capacity can be 20 times of the total capacity. If the value of this ratio is set larger than 1.0, the provisioned capacity can exceed the total capacity.

## QoS support

Unity driver now supports QoS. To enable this function, User needs to set
`maxIOPS` and/or `maxBWS` on QoS specs and associate it with a volume type.

Example:

    cinder qos-create unity_qos consumer=”back-end” maxIOPS=1000 maxBWS=1000
    cinder qos-associate <qos-spec-id> <volume-type-id>


NOTE: Unity driver only supports QoS spec whose consumer is set to `back-end`.
