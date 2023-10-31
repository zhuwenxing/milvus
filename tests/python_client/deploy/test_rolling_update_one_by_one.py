from pprint import pformat
from pathlib import Path
import subprocess
import pytest
from time import sleep
import yaml
from datetime import datetime
from utils.util_log import test_log as log
from common.common_type import CaseLabel
from chaos import constants
from common.cus_resource_opts import CustomResourceOperations as CusResource
import time
from kubernetes import client, config

class TestBase:
    expect_create = constants.SUCC
    expect_insert = constants.SUCC
    expect_flush = constants.SUCC
    expect_index = constants.SUCC
    expect_search = constants.SUCC
    expect_query = constants.SUCC
    host = '127.0.0.1'
    port = 19530
    _chaos_config = None
    health_checkers = {}


def interrupt_rolling(release_name, component, timeout=60):
    # get the querynode pod name which age is the newest
    cmd = f"kubectl get pod -n chaos-testing|grep {release_name}|grep {component}|awk '{{print $1}}'"
    output = run_cmd(cmd)
    
    chaos_config = {}
    # apply chaos object
    chaos_res = CusResource(kind=chaos_config['kind'],
                            group=constants.CHAOS_GROUP,
                            version=constants.CHAOS_VERSION,
                            namespace=constants.CHAOS_NAMESPACE)
    chaos_res.create(chaos_config)
    create_time = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S.%f')
    log.info("chaos injected")


def pause_and_resume_deployment(deployment_name, namespace, updated_pod_count, pause_seconds):
    # Load Kubernetes configuration
    config.load_kube_config()

    api_instance = client.AppsV1Api()

    # Monitor the number of updated Pods
    while True:
        updated_replicas = api_instance.read_namespaced_deployment(deployment_name, namespace).status.updated_replicas
        if updated_replicas >= updated_pod_count:
            break
        time.sleep(5)

    # Pause the Deployment's rolling update
    deployment = api_instance.read_namespaced_deployment(deployment_name, namespace)
    deployment.spec.paused = True
    api_instance.patch_namespaced_deployment(deployment_name, namespace, deployment)
    print(f"Paused deployment after updating {updated_replicas} replicas. Waiting for {pause_seconds} seconds...")

    # Wait for the specified pause time
    time.sleep(pause_seconds)

    # Resume the Deployment's rolling update
    deployment = api_instance.read_namespaced_deployment(deployment_name, namespace)
    deployment.spec.paused = False
    api_instance.patch_namespaced_deployment(deployment_name, namespace, deployment)
    print("Resumed deployment")



def run_cmd(cmd):
    log.info(f"cmd: {cmd}")
    res = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = res.communicate()
    output = stdout.decode("utf-8")
    log.info(f"{cmd}\n{output}\n")
    return output     



class TestOperations(TestBase):

    @pytest.mark.tags(CaseLabel.L3)
    def test_operations(self, new_image_repo, new_image_tag, components_order):
        log.info("*********************Rolling Update Start**********************")
        origin_file_path = f"{str(Path(__file__).parent)}/milvus_crd.yaml"
        with open(origin_file_path, "r") as f:
                config = yaml.load(f, Loader=yaml.FullLoader)
        target_image = f"{new_image_repo}:{new_image_tag}"
        if "image" in config["spec"]["components"]:
            del config["spec"]["components"]["image"]
        config["spec"]["components"]["imageUpdateMode"] = "all"
        log.info(f"config: {pformat(config['spec']['components'])}")
        # save config to a modified file
        modified_file_path = f"{str(Path(__file__).parent)}/milvus_crd_modified.yaml"
        with open(modified_file_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        kind = config["kind"]
        meta_name = config["metadata"]["name"]
        components = eval(components_order) # default is ['indexNode', 'rootCoord', ['dataCoord', 'indexCoord'], 'queryCoord', 'dataNode', 'queryNode', 'proxy']
        log.info(f"update order: {components}")
        component_time_map = {}
        for component in components:
            prefix = f"[update image for {component}]"
            # load config and update
            with open(modified_file_path, "r") as f:
                config = yaml.load(f, Loader=yaml.FullLoader)
            if isinstance(component, list):
                for c in component:
                    config["spec"]["components"][c]["image"] = target_image
            else:
                config["spec"]["components"][component]["image"] = target_image
            log.info(prefix + f"config: {pformat(config['spec']['components'])}")
            # save config to file
            with open(modified_file_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            log.info(f"update image for component {component}")
            cmd = f"kubectl patch {kind} {meta_name} --patch-file {modified_file_path} --type merge"
            run_cmd(cmd)
            component_time_map[str(component)] = datetime.now()
            if component in ["querynode", "datanode", "indexnode"]:
                pause_and_resume_deployment(component, "chaos-testing", 1, 30)

            # check pod status
            log.info(prefix + "wait 10s after rolling update patch")
            sleep(10)
            cmd = f"kubectl get pod|grep {meta_name}"
            run_cmd(cmd)
            # check milvus status
            ready = False
            while ready is False:
                cmd = f"kubectl get pod|grep {meta_name}"
                run_cmd(cmd)
                sleep(10)
                cmd = f"kubectl get mi |grep {meta_name}"
                output = run_cmd(cmd)
                log.info(f"output: {output}")
                if "True" in output:
                    ready = True
                else:
                    log.info(prefix + "wait 10s for milvus ready")
                    sleep(10)
            sleep(60)
        log.info(f"rolling update time: {component_time_map}")
        log.info("*********************Test Completed**********************")
