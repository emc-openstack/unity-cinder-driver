Dell EMC Unity Cinder driver
============================

## IMPORTANT NOTE:

**Please follow the [Driver configuration](#driver-configuration)
exactly if you are upgrading Unity Cinder driver from version 0.3.0
(and before), or newly installing Unity Cinder driver.**

License
-------

[Apache License, Version 2.0](./Apache_License_Version_2.0.pdf)

Overview
--------

Unity driver is built on the top of Block Storage framework and a Dell EMC
distributed Python package
[storops](https://pypi.python.org/pypi/storops).

Version
-------

0.3.1

Prerequisites
-------------

| Software  | Version         |
|-----------|-----------------|
| Unity OE  | 4.1.X           |
| OpenStack | Liberty         |
| storops   | 0.4.11 or newer |

Supported operations
--------------------

-   Create, delete, attach, and detach volumes.
-   Create, list, and delete volume snapshots.
-   Create a volume from a snapshot.
-   Copy an image to a volume.
-   Clone a volume.
-   Extend a volume.
-   Migrate a volume.
-   Get volume statistics.
-   Efficient non-disruptive volume backup.

Driver configuration
--------------------

> **NOTE**
>
> The following instructions should all be performed on Black Storage nodes.
>

1.  Install Unity Cinder driver

    Unity Cinder driver is provided in the folder:
`cinder/volume/drivers/dell_emc/unity`.

    Merge the folder `dell_emc` into
the `cinder/volume/drivers` directory of your OpenStack node(s) where
cinder-volume is running.

2.  Install storops from pypi:

    ``` sourceCode
    # pip install storops
    ```

3.  Add the following content into `/etc/cinder/cinder.conf`:

    ``` sourceCode
    [DEFAULT]
    enabled_backends = unity

    [unity]
    # Storage protocol
    storage_protocol = iSCSI
    # Unisphere IP
    san_ip = <SAN IP>
    # Unisphere username and password
    san_login = <SAN LOGIN>
    san_password = <SAN PASSWORD>
    # Volume driver name
    volume_driver = cinder.volume.drivers.dell_emc.unity.Driver
    # backend's name
    volume_backend_name = Storage_ISCSI_01
    ```

    > **NOTE**
    >
    > These are minimal options for Unity driver, for more options,
    > see [Driver options](#driver-options).
    >

> **NOTE**
>
> (**Optional**) If you require multipath based data access, perform
> below steps on both Block Storage and Compute nodes.
>

1.  Install `sysfsutils`, `sg3-utils` and `multipath-tools`:

    ``` sourceCode
    # apt-get install multipath-tools sg3-utils sysfsutils
    ```

2.  (Required for FC driver in case [Auto-zoning support](#auto-zoning-support)
is disabled) Zone the FC ports of Compute nodes with Unity FC target ports.

3.  Enable Unity storage optimized multipath configuration:

    Add the following content into `/etc/multipath.conf`

    ``` sourceCode
    blacklist {
        # Skip the files uner /dev that are definitely not FC/iSCSI devices
        # Different system may need different customization
        devnode "^(ram|raw|loop|fd|md|dm-|sr|scd|st)[0-9]*"
        devnode "^hd[a-z][0-9]*"
        devnode "^cciss!c[0-9]d[0-9]*[p[0-9]*]"

        # Skip LUNZ device from VNX/Unity
        device {
            vendor "DGC"
            product "LUNZ"
        }
    }

    defaults {
        user_friendly_names no
        flush_on_last_del yes
    }

    devices {
        # Device attributed for EMC CLARiiON and VNX/Unity series ALUA
        device {
            vendor "DGC"
            product ".*"
            product_blacklist "LUNZ"
            path_grouping_policy group_by_prio
            path_selector "round-robin 0"
            path_checker emc_clariion
            features "0"
            no_path_retry 12
            hardware_handler "1 alua"
            prio alua
            failback immediate
        }
    }
    ```

4.  Restart the multipath service:

    ``` sourceCode
    # service multipath-tools restart
    ```

5.  Enable multipath for image transfer in `/etc/cinder/cinder.conf`.

    ``` sourceCode
    use_multipath_for_image_xfer = True
    ```

    Restart the `cinder-volume` service to load the change.

6.  Enable multipath for volume attache/detach in `/etc/nova/nova.conf`.

    ``` sourceCode
    [libvirt]
    ...
    volume_use_multipath = True
    ...
    ```

7.  Restart the `nova-compute` service.

Driver options
--------------
### Storage pools option

Specify the name list (comma-seperated) of pools to be managed in the driver.

``` sourceCode
unity_storage_pool_names = pool_a, pool_b
```

### FC or iSCSI ports option

Specify the list of FC or iSCSI ports to be used to perform the IO. Wild card
character is supported. For iSCSI ports, use the following format:

``` sourceCode
unity_io_ports = spa_eth2, spb_eth2, *_eth3
```

For FC ports, use the following format:

``` sourceCode
unity_io_ports = spa_iom_0_fc0, spb_iom_0_fc0, *_iom_0_fc1
```

List the port ID with the uemcli command:

``` sourceCode
$ uemcli /net/port/eth show -output csv
...
"spa_eth2","SP A Ethernet Port 2","spa","file, net, iscsi", ...
"spb_eth2","SP B Ethernet Port 2","spb","file, net, iscsi", ...
...

$ uemcli /net/port/fc show -output csv
...
"spa_iom_0_fc0","SP A I/O Module 0 FC Port 0","spa", ...
"spb_iom_0_fc0","SP B I/O Module 0 FC Port 0","spb", ...
...
```

Live migration integration
--------------------------

It is suggested to have multipath configured on Compute nodes for robust data
access in VM instances live migration scenario. Once `user_friendly_names no`
is set in defaults section of `/etc/multipath.conf`, Compute nodes will use the
WWID as the alias for the multipath devices.

To enable multipath in live migration:

> **NOTE**
>
> Make sure [Driver configuration](#driver-configuration) steps are performed
> before following steps.
>

1.  Set multipath in `/etc/nova/nova.conf`:

    ``` sourceCode
    [libvirt]
    ...
    volume_use_multipath = True
    ...
    ```

    Restart nova-compute service.

2.  Set `user_friendly_names no` in `/etc/multipath.conf`

    ``` sourceCode
    ...
    defaults {
        user_friendly_names no
        find_multipaths no
    }
    ...
    ```

3.  Restart the `multipath-tools` service.

Thin and thick provisioning
---------------------------

Only thin volume provisioning is supported in Unity volume driver.

QoS support
-----------

Unity driver supports `maxBWS` and `maxIOPS` specs for the back-end consumer
type. `maxBWS` represents the `Maximum IO/S` absolute limit, `maxIOPS`
represents the `Maximum Bandwidth (KBPS)` absolute limit on the Unity
respectively.

Auto-zoning support
-------------------

Unity volume driver supports auto-zoning, and share the same configuration
guide for other vendors. Refer to
[Fibre Channel Zone Manager](https://docs.openstack.org/mitaka/config-reference/block-storage/fc-zoning.html) for detailed
configuration steps.

Solution for LUNZ device
------------------------

The EMC host team also found LUNZ on all of the hosts, EMC best practice is to
present a LUN with HLU 0 to clear any LUNZ devices as they can cause issues on
the host. See KB [LUNZ Device](https://support.emc.com/kb/463402).

To workaround this issue, Unity driver creates a Dummy LUN (if not present),
and adds it to each host to occupy the HLU 0 during volume attachment.

> **NOTE**
>
> This Dummy LUN is shared among all hosts connected to the Unity.

Efficient non-disruptive volume backup
--------------------------------------

The default implementation in Block Storage for non-disruptive volume backup is
not efficient since a cloned volume will be created during backup.

An effective approach to backups is to create a snapshot for the volume and
connect this snapshot to the Block Storage host for volume backup.

Troubleshooting
---------------

To troubleshoot a failure in OpenStack deployment, the best way is to enable
verbose and debug log, at the same time, leverage the build-in
[request_id](https://specs.openstack.org/openstack/openstack-specs/specs/return-request-id.html)
to track specific Block Storage command logs.

1.  Enable verbose log, set following in `/etc/cinder/cinder.conf` and restart
all Block Storage services:

    ``` sourceCode
    [DEFAULT]

    ...

    debug = True
    verbose = True

    ...
    ```

    If other projects (usually Compute) are also involved, set debug and
 `verbose` to `True`.

2.  Use `--debug` to trigger any problematic Block Storage operation:

    ``` sourceCode
    # cinder --debug create --name unity_vol1 100
    ```

    You will see the request ID from the console, for example:

    ``` sourceCode
    DEBUG:keystoneauth:REQ: curl -g -i -X POST
    http://192.168.1.9:8776/v2/e50d22bdb5a34078a8bfe7be89324078/volumes -H
    "User-Agent: python-cinderclient" -H "Content-Type: application/json" -H
    "Accept: application/json" -H "X-Auth-Token:
    {SHA1}bf4a85ad64302b67a39ad7c6f695a9630f39ab0e" -d '{"volume": {"status":
    "creating", "user_id": null, "name": "unity_vol1", "imageRef": null,
    "availability_zone": null, "description": null, "multiattach": false,
    "attach_status": "detached", "volume_type": null, "metadata": {},
    "consistencygroup_id": null, "source_volid": null, "snapshot_id": null,
    "project_id": null, "source_replica": null, "size": 10}}'
    DEBUG:keystoneauth:RESP: [202] X-Compute-Request-Id:
    req-3a459e0e-871a-49f9-9796-b63cc48b5015 Content-Type: application/json
    Content-Length: 804 X-Openstack-Request-Id:
    req-3a459e0e-871a-49f9-9796-b63cc48b5015 Date: Mon, 12 Dec 2016 09:31:44 GMT
    Connection: keep-alive
    ```

3.  Use commands like `grep`, `awk` to find the error related to the Block
Storage operations.

    ``` sourceCode
    # grep "req-3a459e0e-871a-49f9-9796-b63cc48b5015" cinder-volume.log
    ```
