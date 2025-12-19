import threading
import pytest
import time
from time import sleep
from pathlib import Path
import json
from pymilvus import connections
from kubernetes import client
from kubernetes.client.rest import ApiException
from common.cus_resource_opts import CustomResourceOperations as CusResource
from common.milvus_sys import MilvusSys
from utils.util_log import test_log as log
from datetime import datetime
from utils.util_k8s import wait_pods_ready, get_milvus_instance_name, get_milvus_deploy_tool, get_pod_list, init_k8s_client_config
from utils.util_common import update_key_value, update_key_name, gen_experiment_config, wait_signal_to_apply_chaos
import constants


def get_selector_from_chaos_config(chaos_config):
    """
    Extract selector from chaos config for different chaos types
    """
    kind = chaos_config.get('kind', '')
    spec = chaos_config.get('spec', {})

    # For Schedule type, selector is nested under podChaos/ioChaos/etc
    if kind == 'Schedule':
        chaos_type = spec.get('type', '').lower()
        type_mapping = {
            'podchaos': 'podChaos',
            'iochaos': 'ioChaos',
            'networkchaos': 'networkChaos',
            'stresschaos': 'stressChaos',
            'timechaos': 'timeChaos'
        }
        nested_key = type_mapping.get(chaos_type, chaos_type)
        nested_spec = spec.get(nested_key, {})
        return nested_spec.get('selector', {})
    else:
        # For direct chaos types (PodChaos, IOChaos, NetworkChaos, etc.)
        return spec.get('selector', {})


def build_label_selector_string(selector):
    """
    Build label selector string from selector dict
    """
    label_selectors = selector.get('labelSelectors', {})
    if not label_selectors:
        return ""

    label_parts = []
    for key, value in label_selectors.items():
        label_parts.append(f"{key}={value}")

    return ", ".join(label_parts)


def verify_chaos_selector_matches_pods(chaos_config, namespace):
    """
    Verify that the chaos selector can match at least one pod
    Returns: (matched, pod_names)
    """
    selector = get_selector_from_chaos_config(chaos_config)
    if not selector:
        log.warning("No selector found in chaos config")
        return False, []

    label_selector_str = build_label_selector_string(selector)
    if not label_selector_str:
        log.warning("No label selectors found in chaos config")
        return False, []

    log.info(f"Verifying chaos selector: namespace={namespace}, labels={label_selector_str}")

    try:
        pods = get_pod_list(namespace, label_selector_str)
        pod_names = [pod.metadata.name for pod in pods]

        if len(pod_names) > 0:
            log.info(f"Chaos selector matches {len(pod_names)} pod(s): {pod_names}")
            return True, pod_names
        else:
            log.error(f"Chaos selector matches NO pods! selector: {label_selector_str}")
            return False, []
    except Exception as e:
        log.error(f"Failed to verify chaos selector: {e}")
        return False, []


def cleanup_chaosfs_directories(pod_names, namespace, volume_path):
    """
    Cleanup residual __chaosfs__ directories in pods after IOChaos.
    IOChaos creates __chaosfs__<dir>__ proxy directories via FUSE that may remain
    after chaos cleanup failure.

    Args:
        pod_names: List of pod names to cleanup
        namespace: The namespace where pods are running
        volume_path: The volumePath from IOChaos config (e.g., /var/lib/milvus/data)

    Returns:
        (cleaned_count, pods_need_restart): Number of pods cleaned and list of pods that need restart
    """
    if not pod_names or not volume_path:
        return 0, []

    import os
    from kubernetes.stream import stream

    init_k8s_client_config()
    core_v1 = client.CoreV1Api()
    cleaned_count = 0
    pods_need_restart = []

    # Get parent directory of volumePath
    # e.g., /var/lib/milvus/data -> /var/lib/milvus
    parent_path = os.path.dirname(volume_path.rstrip('/'))
    if not parent_path:
        parent_path = '/'

    for pod_name in pod_names:
        try:
            # First check if __chaosfs__ directories exist
            check_cmd = [
                '/bin/sh', '-c',
                f'ls -d {parent_path}/__chaosfs__* 2>/dev/null || echo "none"'
            ]
            resp = stream(
                core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                command=check_cmd,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False
            )

            if 'none' in resp or '__chaosfs__' not in resp:
                # No residual directories
                cleaned_count += 1
                continue

            log.warning(f"Found __chaosfs__ residual in pod {pod_name}: {resp.strip()}")

            # Try to remove __chaosfs__ directories
            cleanup_cmd = [
                '/bin/sh', '-c',
                f'rm -rf {parent_path}/__chaosfs__* 2>&1'
            ]
            resp = stream(
                core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                command=cleanup_cmd,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False
            )

            # Check if removal failed (FUSE mount still active)
            if 'Device or resource busy' in resp or 'cannot remove' in resp:
                log.warning(f"Cannot remove __chaosfs__ in pod {pod_name} (FUSE mount busy), pod needs restart")
                pods_need_restart.append(pod_name)
            else:
                log.info(f"Cleaned __chaosfs__ directories in pod {pod_name}")
                cleaned_count += 1

        except ApiException as e:
            if e.status == 404:
                log.warning(f"Pod {pod_name} not found, may have been restarted")
                cleaned_count += 1  # Consider it cleaned
            else:
                log.warning(f"Failed to cleanup __chaosfs__ in pod {pod_name}: {e}")
        except Exception as e:
            log.warning(f"Failed to exec cleanup command in pod {pod_name}: {e}")

    return cleaned_count, pods_need_restart


def restart_pods(pod_names, namespace):
    """
    Restart pods by deleting them (StatefulSet/Deployment will recreate them).

    Args:
        pod_names: List of pod names to restart
        namespace: The namespace where pods are running

    Returns:
        Number of pods successfully deleted
    """
    if not pod_names:
        return 0

    init_k8s_client_config()
    core_v1 = client.CoreV1Api()
    deleted_count = 0

    for pod_name in pod_names:
        try:
            core_v1.delete_namespaced_pod(pod_name, namespace)
            log.info(f"Restarted pod {pod_name} for IOChaos cleanup")
            deleted_count += 1
        except ApiException as e:
            if e.status == 404:
                log.warning(f"Pod {pod_name} not found")
            else:
                log.warning(f"Failed to restart pod {pod_name}: {e}")

    return deleted_count


class TestChaosApply:

    @pytest.fixture(scope="function", autouse=True)
    def init_env(self, host, port, user, password, milvus_ns):
        if user and password:
            connections.connect('default', host=host, port=port, user=user, password=password)
        else:
            connections.connect('default', host=host, port=port)
        if connections.has_connection("default") is False:
            raise Exception("no connections")
        #
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.milvus_sys = MilvusSys(alias='default')
        self.chaos_ns = constants.CHAOS_NAMESPACE
        self.milvus_ns = milvus_ns
        self.release_name = get_milvus_instance_name(self.milvus_ns, milvus_sys=self.milvus_sys)
        self.deploy_by = get_milvus_deploy_tool(self.milvus_ns, self.milvus_sys)

    def reconnect(self):
        if self.user and self.password:
            connections.connect('default', host=self.host, port=self.port,
                                user=self.user,
                                password=self.password)
        else:
            connections.connect('default', host=self.host, port=self.port)
        if connections.has_connection("default") is False:
            raise Exception("no connections")

    def teardown(self):
        chaos_res = CusResource(kind=self.chaos_config['kind'],
                                group=constants.CHAOS_GROUP,
                                version=constants.CHAOS_VERSION,
                                namespace=constants.CHAOS_NAMESPACE)
        meta_name = self.chaos_config.get('metadata', None).get('name', None)
        # Use force_delete to handle stuck chaos resources with finalizers
        chaos_res.force_delete(meta_name, timeout=60)
        sleep(2)

    def test_chaos_apply(self, chaos_type, target_component, target_scope, target_number, chaos_duration, chaos_interval, wait_signal):
        # start the monitor threads to check the milvus ops
        log.info("*********************Chaos Test Start**********************")
        if wait_signal:
            log.info("need wait signal to start chaos")
            ready_for_chaos = wait_signal_to_apply_chaos()
            if not ready_for_chaos:
                log.info("get the signal to apply chaos timeout")
            else:
                log.info("get the signal to apply chaos")
        log.info(connections.get_connection_addr('default'))
        release_name = self.release_name
        chaos_config = gen_experiment_config(
            f"{str(Path(__file__).absolute().parent)}/chaos_objects/{chaos_type.replace('-', '_')}/chaos_{target_component}_{chaos_type.replace('-', '_')}.yaml")
        chaos_config['metadata']['name'] = f"test-{target_component}-{chaos_type.replace('_','-')}-{int(time.time())}"
        chaos_config['metadata']['namespace'] = self.chaos_ns
        meta_name = chaos_config.get('metadata', None).get('name', None)
        update_key_value(chaos_config, "release", release_name)
        update_key_value(chaos_config, "app.kubernetes.io/instance", release_name)
        update_key_value(chaos_config, "namespaces", [self.milvus_ns])
        update_key_value(chaos_config, "value", target_number)
        update_key_value(chaos_config, "mode", target_scope)
        self.chaos_config = chaos_config
        if "s" in chaos_interval:
            schedule = f"*/{chaos_interval[:-1]} * * * * *"
        if "m" in chaos_interval:
            schedule = f"00 */{chaos_interval[:-1]} * * * *"
        update_key_value(chaos_config, "schedule", schedule)
        # update chaos_duration from string to int with unit second
        chaos_duration = chaos_duration.replace('h', '*3600+').replace('m', '*60+').replace('s', '*1+') + '+0'
        chaos_duration = eval(chaos_duration)
        update_key_value(chaos_config, "duration", f"{chaos_duration//60}m")
        if self.deploy_by == "milvus-operator":
            update_key_name(chaos_config, "component", "app.kubernetes.io/component")
        self._chaos_config = chaos_config  # cache the chaos config for tear down
        log.info(f"chaos_config: {chaos_config}")

        # verify chaos selector can match pods before applying
        matched, matched_pods = verify_chaos_selector_matches_pods(chaos_config, self.milvus_ns)
        if not matched:
            raise Exception(f"Chaos selector cannot match any pods in namespace {self.milvus_ns}. "
                           f"Please check the label selectors in chaos config.")
        log.info(f"Chaos selector verification passed, will affect pods: {matched_pods}")

        # apply chaos object
        chaos_res = CusResource(kind=chaos_config['kind'],
                                group=constants.CHAOS_GROUP,
                                version=constants.CHAOS_VERSION,
                                namespace=constants.CHAOS_NAMESPACE)
        chaos_res.create(chaos_config)
        create_time = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S.%f')
        log.info("chaos injected")
        res = chaos_res.list_all()
        chaos_list = [r['metadata']['name'] for r in res['items']]
        assert meta_name in chaos_list
        res = chaos_res.get(meta_name)
        log.info(f"chaos inject result: {res['kind']}, {res['metadata']['name']}")
        sleep(chaos_duration)
        # delete chaos (use force_delete to handle stuck resources with finalizers)
        deleted = chaos_res.force_delete(meta_name, timeout=60)
        delete_time = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S.%f')
        log.info("chaos deleted")
        assert deleted, f"Failed to delete chaos {meta_name} within 60s"

        # For IOChaos, cleanup residual __chaosfs__ directories in affected pods
        if 'io' in chaos_type.lower():
            volume_path = chaos_config.get('spec', {}).get('volumePath', '')
            if volume_path:
                # Re-fetch current pods by selector (pods may have restarted during chaos)
                label_selector_str = build_label_selector_string(get_selector_from_chaos_config(chaos_config))
                current_pods = get_pod_list(self.milvus_ns, label_selector_str)
                current_pod_names = [pod.metadata.name for pod in current_pods]
                log.info(f"IOChaos detected (type={chaos_type}), cleaning up __chaosfs__ residual in pods: {current_pod_names}")
                cleaned_count, pods_need_restart = cleanup_chaosfs_directories(current_pod_names, self.milvus_ns, volume_path)
                log.info(f"Cleaned __chaosfs__ directories in {cleaned_count} pod(s)")

                # Restart pods that have FUSE mount stuck
                if pods_need_restart:
                    log.warning(f"Restarting {len(pods_need_restart)} pod(s) with stuck FUSE mount: {pods_need_restart}")
                    restart_pods(pods_need_restart, self.milvus_ns)

        # wait all pods ready
        t0 = time.time()
        log.info(f"wait for pods in namespace {constants.CHAOS_NAMESPACE} with label app.kubernetes.io/instance={release_name}")
        wait_pods_ready(constants.CHAOS_NAMESPACE, f"app.kubernetes.io/instance={release_name}")
        log.info(f"wait for pods in namespace {constants.CHAOS_NAMESPACE} with label release={release_name}")
        wait_pods_ready(constants.CHAOS_NAMESPACE, f"release={release_name}")
        log.info("all pods are ready")
        pods_ready_time = time.time() - t0
        log.info(f"pods ready time: {pods_ready_time}")
        recovery_time = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S.%f')
        event_records = {
            "chaos_type": chaos_type,
            "target_component": target_component,
            "meta_name": meta_name,
            "create_time": create_time,
            "delete_time": delete_time,
            "recovery_time": recovery_time
        }
        # save event records to json file
        with open(constants.CHAOS_INFO_SAVE_PATH, 'w') as f:
            json.dump(event_records, f)
        # reconnect to test the service healthy
        start_time = time.time()
        end_time = start_time + 120
        while time.time() < end_time:
            try:
                self.reconnect()
                break
            except Exception as e:
                log.error(e)
                sleep(2)
        recovery_time = time.time() - start_time
        log.info(f"recovery time from pod ready to can be connected: {recovery_time}")

        log.info("*********************Chaos Test Completed**********************")
