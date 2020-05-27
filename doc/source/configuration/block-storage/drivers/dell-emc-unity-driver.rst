=====================
Dell EMC Unity driver
=====================

Unity driver has been integrated in the OpenStack Block Storage project since
the Ocata release. The driver is built on the top of Block Storage framework
and a Dell EMC distributed Python package
`storops <https://pypi.python.org/pypi/storops>`_.

Prerequisites
~~~~~~~~~~~~~

+-------------------+-----------------+
|    Software       |    Version      |
+===================+=================+
| Unity OE          | 4.1.X or newer  |
+-------------------+-----------------+
| storops           | 0.5.10 or newer |
+-------------------+-----------------+


Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach, and detach volumes.
- Create, list, and delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Create an image from a volume.
- Clone a volume.
- Extend a volume.
- Migrate a volume.
- Get volume statistics.
- Efficient non-disruptive volume backup.
- Revert a volume to a snapshot.
- Create thick volumes.
- Attach a volume to multiple servers simultaneously (multiattach).

Driver configuration
~~~~~~~~~~~~~~~~~~~~

.. note:: The following instructions should all be performed on Black Storage
          nodes.

#. Install `storops` from pypi:

   .. code-block:: console

      # pip install storops


#. Add the following content into ``/etc/cinder/cinder.conf``:

   .. code-block:: ini

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

   .. note:: These are minimal options for Unity driver, for more options,
             see `Driver options`_.


.. note:: (**Optional**) If you require multipath based data access, perform
          below steps on both Block Storage and Compute nodes.


#. Install ``sysfsutils``, ``sg3-utils`` and ``multipath-tools``:

   .. code-block:: console

      # apt-get install multipath-tools sg3-utils sysfsutils


#. (Required for FC driver in case `Auto-zoning Support`_ is disabled) Zone the
   FC ports of Compute nodes with Unity FC target ports.


#. Enable Unity storage optimized multipath configuration:

   Add the following content into ``/etc/multipath.conf``

   .. code-block:: vim

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


#. Restart the multipath service:

   .. code-block:: console

      # service multipath-tools restart


#. Enable multipath for image transfer in ``/etc/cinder/cinder.conf``.

   .. code-block:: ini

      use_multipath_for_image_xfer = True

   Restart the ``cinder-volume`` service to load the change.

#. Enable multipath for volume attache/detach in ``/etc/nova/nova.conf``.

   .. code-block:: ini

      [libvirt]
      ...
      volume_use_multipath = True
      ...

#. Restart the ``nova-compute`` service.

Driver options
~~~~~~~~~~~~~~

.. include:: ../../tables/cinder-dell_emc_unity.inc

FC or iSCSI ports option
------------------------

Specify the list of FC or iSCSI ports to be used to perform the IO. Wild card
character is supported.
For iSCSI ports, use the following format:

.. code-block:: ini

   unity_io_ports = spa_eth2, spb_eth2, *_eth3

For FC ports, use the following format:

.. code-block:: ini

   unity_io_ports = spa_iom_0_fc0, spb_iom_0_fc0, *_iom_0_fc1

List the port ID with the :command:`uemcli` command:

.. code-block:: console

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

Live migration integration
~~~~~~~~~~~~~~~~~~~~~~~~~~

It is suggested to have multipath configured on Compute nodes for robust data
access in VM instances live migration scenario. Once ``user_friendly_names no``
is set in defaults section of ``/etc/multipath.conf``, Compute nodes will use
the WWID as the alias for the multipath devices.

To enable multipath in live migration:

.. note:: Make sure `Driver configuration`_ steps are performed before
          following steps.

#. Set multipath in ``/etc/nova/nova.conf``:

   .. code-block:: ini

      [libvirt]
      ...
      volume_use_multipath = True
      ...

   Restart `nova-compute` service.


#. Set ``user_friendly_names no`` in ``/etc/multipath.conf``

   .. code-block:: text

      ...
      defaults {
          user_friendly_names no
      }
      ...

#. Restart the ``multipath-tools`` service.


Thin and thick provisioning
~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, the volume created by Unity driver is thin provisioned. Run the
following commands to create a thick volume.

.. code-block:: console

    # openstack volume type create --property provisioning:type=thick \
      --property thick_provisioning_support='<is> True' thick_volume_type
    # openstack volume create --type thick_volume_type thick_volume


QoS support
~~~~~~~~~~~

Unity driver supports ``maxBWS`` and ``maxIOPS`` specs for the back-end
consumer type. ``maxBWS`` represents the ``Maximum IO/S`` absolute limit,
``maxIOPS`` represents the ``Maximum Bandwidth (KBPS)`` absolute limit on the
Unity respectively.


Auto-zoning support
~~~~~~~~~~~~~~~~~~~

Unity volume driver supports auto-zoning, and share the same configuration
guide for other vendors. Refer to :ref:`fc_zone_manager`
for detailed configuration steps.

Solution for LUNZ device
~~~~~~~~~~~~~~~~~~~~~~~~

The EMC host team also found LUNZ on all of the hosts, EMC best practice is to
present a LUN with HLU 0 to clear any LUNZ devices as they can cause issues on
the host. See KB `LUNZ Device <https://support.emc.com/kb/463402>`_.

To workaround this issue, Unity driver creates a `Dummy LUN` (if not present),
and adds it to each host to occupy the `HLU 0` during volume attachment.

.. note:: This `Dummy LUN` is shared among all hosts connected to the Unity.

Efficient non-disruptive volume backup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The default implementation in Block Storage for non-disruptive volume backup is
not efficient since a cloned volume will be created during backup.

An effective approach to backups is to create a snapshot for the volume and
connect this snapshot to the Block Storage host for volume backup.

SSL support
~~~~~~~~~~~

Admin is able to enable the SSL verification for any communication against
Unity REST API.

By default, the SSL verification is disabled, user can enable it by following
steps:

#. Setup the Unity array certificate and import it to the Unity, see section
   `Storage system certificate` of `Security Configuration Guide <https://www.emc.com/collateral/TechnicalDocument/docu69321.pdf>`_.

#. Import the CA certficate to the Cinder nodes on which the driver is running.

#. Enable the changes on cinder nodes and restart the cinder services.

.. code-block:: ini

     [unity]
     ...
     driver_ssl_cert_verify = True
     driver_ssl_cert_path = <path to the CA>
     ...


If `driver_ssl_cert_path` is omitted, the system default CA will be used for CA
verification.


IPv6 support
~~~~~~~~~~~~

This driver can support IPv6-based control path and data path.

For control path, please follow below steps:

- Enable Unity's Unipshere IPv6 address.
- Configure the IPv6 network to make sure that cinder node can access Unishpere
  via IPv6 address.
- Change Cinder config file ``/etc/cinder/cinder.conf``. Make the ``san_ip``
  as Unisphere IPv6 address. For example, ``san_ip = [fd99:f17b:37d0::100]``.
- Restart the Cinder service to make new configuration take effect.

**Note**: The IPv6 support on control path depends on the fix of cpython
`bug 32185 <https://bugs.python.org/issue32185>`__. Please make sure your
Python's version includes this bug's fix.

For data path, please follow below steps:

- On Unity, Create iSCSI interface with IPv6 address.
- Configure the IPv6 network to make sure that you can ``ping``
  the Unity's iSCSI IPv6 address from the Cinder node.
- If you create a volume using Cinder and attach it to a VM,
  the connection between this VM and volume will be IPv6-based iSCSI.

Force detach volume from all hosts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The user could use `os-force_detach` action to detach a volume from all its
attached hosts.
For more detail, please refer to
https://developer.openstack.org/api-ref/block-storage/v2/?expanded=force-detach-volume-detail#force-detach-volume

Troubleshooting
~~~~~~~~~~~~~~~

To troubleshoot a failure in OpenStack deployment, the best way is to
enable verbose and debug log, at the same time, leverage the build-in
`Return request ID to caller
<https://specs.openstack.org/openstack/openstack-specs/specs/return-request-id.html>`_
to track specific Block Storage command logs.


#. Enable verbose log, set following in ``/etc/cinder/cinder.conf`` and restart
   all Block Storage services:

   .. code-block:: ini

      [DEFAULT]

      ...

      debug = True
      verbose = True

      ...


   If other projects (usually Compute) are also involved, set `debug`
   and ``verbose`` to ``True``.

#. use ``--debug`` to trigger any problematic Block Storage operation:

   .. code-block:: console

      # cinder --debug create --name unity_vol1 100


   You will see the request ID from the console, for example:

   .. code-block:: console

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

#. Use commands like ``grep``, ``awk`` to find the error related to the Block
   Storage operations.

   .. code-block:: console

      # grep "req-3a459e0e-871a-49f9-9796-b63cc48b5015" cinder-volume.log

