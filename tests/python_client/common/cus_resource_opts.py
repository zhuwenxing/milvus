from __future__ import print_function

import os

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from utils.util_log import test_log as log
from common.common_type import in_cluster_env

_GROUP = 'milvus.io'
_VERSION = 'v1alpha1'
_NAMESPACE = "default"


class CustomResourceOperations(object):
    def __init__(self, kind, group=_GROUP, version=_VERSION, namespace=_NAMESPACE):
        self.group = group
        self.version = version
        self.namespace = namespace
        if kind.lower()[-1] != "s":
            self.plural = kind.lower() + "s"
        else:
            self.plural = kind.lower()

        # init k8s client config
        in_cluster = os.getenv(in_cluster_env, default='False')
        log.debug(f"env variable IN_CLUSTER: {in_cluster}")
        if in_cluster.lower() == 'true':
            config.load_incluster_config()
        else:
            config.load_kube_config()

    def create(self, body):
        """create or apply a custom resource in k8s"""
        pretty = 'true'
        api_instance = client.CustomObjectsApi()
        try:
            api_response = api_instance.create_namespaced_custom_object(self.group, self.version, self.namespace,
                                                                        plural=self.plural, body=body, pretty=pretty)
            log.info(f"create custom resource response: {api_response}")
        except ApiException as e:
            log.error("Exception when calling CustomObjectsApi->create_namespaced_custom_object: %s\n" % e)
            raise Exception(str(e))
        return api_response

    def delete(self, metadata_name, raise_ex=True):
        """delete or uninstall a custom resource in k8s"""
        print(metadata_name)
        try:
            api_instance = client.CustomObjectsApi()
            api_response = api_instance.delete_namespaced_custom_object(self.group, self.version, self.namespace,
                                                                        self.plural,
                                                                        metadata_name)
            log.info(f"delete custom resource response: {api_response}")
        except ApiException as e:
            if raise_ex:
                log.error("Exception when calling CustomObjectsApi->delete_namespaced_custom_object: %s\n" % e)
                raise Exception(str(e))

    def patch(self, metadata_name, body):
        """patch a custom resource in k8s"""
        api_instance = client.CustomObjectsApi()
        try:
            api_response = api_instance.patch_namespaced_custom_object(self.group, self.version, self.namespace,
                                                                       plural=self.plural,
                                                                       name=metadata_name,
                                                                       body=body)
            log.debug(f"patch custom resource response: {api_response}")
        except ApiException as e:
            log.error("Exception when calling CustomObjectsApi->patch_namespaced_custom_object: %s\n" % e)
            raise Exception(str(e))
        return api_response

    def list_all(self):
        """list all the customer resources in k8s"""
        pretty = 'true'
        try:
            api_instance = client.CustomObjectsApi()
            api_response = api_instance.list_namespaced_custom_object(self.group, self.version, self.namespace,
                                                                      plural=self.plural, pretty=pretty)
            log.debug(f"list custom resource response: {api_response}")
        except ApiException as e:
            log.error("Exception when calling CustomObjectsApi->list_namespaced_custom_object: %s\n" % e)
            raise Exception(str(e))
        return api_response

    def get(self, metadata_name):
        """get a customer resources by name in k8s"""
        try:
            api_instance = client.CustomObjectsApi()
            api_response = api_instance.get_namespaced_custom_object(self.group, self.version,
                                                                     self.namespace, self.plural,
                                                                     name=metadata_name)
            # log.debug(f"get custom resource response: {api_response}")
        except ApiException as e:
            log.error("Exception when calling CustomObjectsApi->get_namespaced_custom_object: %s\n" % e)
            raise Exception(str(e))
        return api_response

    def remove_finalizers(self, metadata_name):
        """remove finalizers from a custom resource to force deletion"""
        body = {"metadata": {"finalizers": None}}
        api_instance = client.CustomObjectsApi()
        try:
            api_response = api_instance.patch_namespaced_custom_object(
                self.group, self.version, self.namespace,
                plural=self.plural,
                name=metadata_name,
                body=body
            )
            log.info(f"removed finalizers from {metadata_name}")
            return api_response
        except ApiException as e:
            log.warning(f"Failed to remove finalizers from {metadata_name}: {e}")
            return None

    def force_delete(self, metadata_name, timeout=60):
        """
        Force delete a custom resource, removing finalizers if stuck in Terminating state.
        This is useful for IOChaos/NetworkChaos that may get stuck due to chaos-mesh/records finalizer.
        """
        from time import sleep, time

        # First attempt normal delete
        self.delete(metadata_name, raise_ex=False)

        # Wait and check if resource is deleted
        t0 = time()
        while time() - t0 < timeout:
            try:
                res = self.get(metadata_name)
                # Check if resource is stuck in Terminating (has deletionTimestamp)
                if res.get('metadata', {}).get('deletionTimestamp'):
                    finalizers = res.get('metadata', {}).get('finalizers', [])
                    if finalizers:
                        log.warning(f"{metadata_name} stuck in Terminating with finalizers: {finalizers}")
                        log.info(f"Removing finalizers to force delete {metadata_name}")
                        self.remove_finalizers(metadata_name)
                sleep(2)
            except Exception as e:
                # get() raises Exception wrapping ApiException, check if it's 404
                if '404' in str(e) or 'Not Found' in str(e):
                    log.info(f"{metadata_name} successfully deleted")
                    return True
                log.warning(f"Error checking resource status: {e}")
                sleep(2)

        # Final check
        try:
            self.get(metadata_name)
            log.error(f"Failed to delete {metadata_name} within {timeout}s")
            return False
        except Exception as e:
            if '404' in str(e) or 'Not Found' in str(e):
                log.info(f"{metadata_name} successfully deleted")
                return True
            return False

    def delete_all(self):
        """delete all the customer resources in k8s"""
        cus_objects = self.list_all()
        if len(cus_objects["items"]) > 0:
            for item in cus_objects["items"]:
                metadata_name = item["metadata"]["name"]
                self.delete(metadata_name)
