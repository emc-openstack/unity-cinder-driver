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


class StoropsException(Exception):
    message = 'Storops Error.'


class UnityException(StoropsException):
    pass


class UnityLunNameInUseError(UnityException):
    pass


class UnityResourceNotFoundError(UnityException):
    pass


class UnitySnapNameInUseError(UnityException):
    pass


class UnityDeleteAttachedSnapError(UnityException):
    pass


class UnityResourceAlreadyAttachedError(UnityException):
    pass


class UnityPolicyNameInUseError(UnityException):
    pass


class UnityNothingToModifyError(UnityException):
    pass


class UnityThinCloneLimitExceededError(UnityException):
    pass


class ExtendLunError(Exception):
    pass


class DetachIsCalled(Exception):
    pass


class DetachAllIsCalled(Exception):
    pass


class DetachFromIsCalled(Exception):
    pass


class LunDeleteIsCalled(Exception):
    pass


class SnapDeleteIsCalled(Exception):
    pass


class UnexpectedLunDeletion(Exception):
    pass


class AdapterSetupError(Exception):
    pass


class ReplicationManagerSetupError(Exception):
    pass


class HostDeleteIsCalled(Exception):
    pass


class UnityThinCloneNotAllowedError(UnityException):
    pass


class SystemAPINotSupported(UnityException):
    pass


class UnityDeleteLunInReplicationError(UnityException):
    pass


class UnityConsistencyGroupNameInUseError(StoropsException):
    pass
