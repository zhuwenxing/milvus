#!/usr/bin/env python3
"""
Script to detect and cleanup Chaos Mesh CRDs that target a specific Milvus release.

Usage:
    # List all chaos resources for a release (dry-run)
    python cleanup_chaos_for_release.py --release my-milvus --namespace chaos-testing --dry-run

    # Delete all chaos resources for a release
    python cleanup_chaos_for_release.py --release my-milvus --namespace chaos-testing --delete

    # List all chaos resources in namespace
    python cleanup_chaos_for_release.py --namespace chaos-testing --list-all
"""

import argparse
import os
import sys
import time
from typing import List, Dict, Tuple

from kubernetes import client, config
from kubernetes.client.rest import ApiException


# Chaos Mesh constants
CHAOS_GROUP = 'chaos-mesh.org'
CHAOS_VERSION = 'v1alpha1'
DEFAULT_CHAOS_NAMESPACE = 'chaos-testing'

# All Chaos Mesh CRD types
CHAOS_KINDS = [
    'podchaos',
    'networkchaos',
    'iochaos',
    'stresschaos',
    'timechaos',
    'dnschaos',
    'httpchaos',
    'kernelchaos',
    'jvmchaos',
    'awschaos',
    'gcpchaos',
    'azurechaos',
    'physicalmachinechaos',
    'schedules',  # Schedule kind uses 'schedules' as plural
    'workflows',
]


def init_k8s_client():
    """Initialize Kubernetes client configuration."""
    in_cluster = os.getenv('IN_CLUSTER', 'False')
    if in_cluster.lower() == 'true':
        config.load_incluster_config()
    else:
        config.load_kube_config()


def get_selector_from_chaos_resource(chaos_resource: Dict) -> Dict:
    """
    Extract selector from chaos resource spec.

    Args:
        chaos_resource: The chaos resource dict

    Returns:
        The selector dict
    """
    kind = chaos_resource.get('kind', '')
    spec = chaos_resource.get('spec', {})

    # For Schedule type, selector is nested under the specific chaos type
    if kind == 'Schedule':
        chaos_type = spec.get('type', '').lower()
        type_mapping = {
            'podchaos': 'podChaos',
            'iochaos': 'ioChaos',
            'networkchaos': 'networkChaos',
            'stresschaos': 'stressChaos',
            'timechaos': 'timeChaos',
            'dnschaos': 'dnsChaos',
            'httpchaos': 'httpChaos',
            'kernelchaos': 'kernelChaos',
            'jvmchaos': 'jvmChaos',
        }
        nested_key = type_mapping.get(chaos_type, chaos_type)
        nested_spec = spec.get(nested_key, {})
        return nested_spec.get('selector', {})

    # For Workflow type
    elif kind == 'Workflow':
        # Workflow may have multiple templates, check all of them
        templates = spec.get('templates', [])
        selectors = []
        for template in templates:
            if 'podChaos' in template:
                selectors.append(template['podChaos'].get('selector', {}))
            elif 'networkChaos' in template:
                selectors.append(template['networkChaos'].get('selector', {}))
            # Add more chaos types as needed
        return selectors[0] if selectors else {}

    else:
        # For direct chaos types (PodChaos, IOChaos, NetworkChaos, etc.)
        return spec.get('selector', {})


def check_selector_matches_release(selector: Dict, release_name: str) -> Tuple[bool, List[str]]:
    """
    Check if the selector targets the specified release.

    Args:
        selector: The selector dict from chaos spec
        release_name: The Milvus release name to match

    Returns:
        Tuple of (matches: bool, matched_labels: list of matching label strings)
    """
    if not selector:
        return False, []

    label_selectors = selector.get('labelSelectors', {})
    namespaces = selector.get('namespaces', [])

    matched_labels = []

    # Check common release label patterns
    release_labels = ['release', 'app.kubernetes.io/instance']

    for label_key in release_labels:
        if label_key in label_selectors:
            if label_selectors[label_key] == release_name:
                matched_labels.append(f"{label_key}={release_name}")

    return len(matched_labels) > 0, matched_labels


def list_chaos_resources(namespace: str, kind_plural: str) -> List[Dict]:
    """
    List all chaos resources of a specific kind in a namespace.

    Args:
        namespace: The Kubernetes namespace
        kind_plural: The plural form of the chaos kind (e.g., 'podchaos', 'schedules')

    Returns:
        List of chaos resource dicts
    """
    api_instance = client.CustomObjectsApi()
    try:
        response = api_instance.list_namespaced_custom_object(
            group=CHAOS_GROUP,
            version=CHAOS_VERSION,
            namespace=namespace,
            plural=kind_plural
        )
        return response.get('items', [])
    except ApiException as e:
        if e.status == 404:
            # CRD not installed, skip silently
            return []
        print(f"Warning: Failed to list {kind_plural}: {e.reason}")
        return []


def delete_chaos_resource(namespace: str, kind_plural: str, name: str) -> bool:
    """
    Delete a chaos resource.

    Args:
        namespace: The Kubernetes namespace
        kind_plural: The plural form of the chaos kind
        name: The name of the resource to delete

    Returns:
        True if deleted successfully, False otherwise
    """
    api_instance = client.CustomObjectsApi()
    try:
        api_instance.delete_namespaced_custom_object(
            group=CHAOS_GROUP,
            version=CHAOS_VERSION,
            namespace=namespace,
            plural=kind_plural,
            name=name
        )
        return True
    except ApiException as e:
        print(f"Error deleting {kind_plural}/{name}: {e.reason}")
        return False


def remove_finalizers(namespace: str, kind_plural: str, name: str) -> bool:
    """
    Remove finalizers from a chaos resource to force deletion.
    This is useful when IOChaos/NetworkChaos gets stuck due to chaos-mesh/records finalizer.

    Args:
        namespace: The Kubernetes namespace
        kind_plural: The plural form of the chaos kind
        name: The name of the resource

    Returns:
        True if successful, False otherwise
    """
    api_instance = client.CustomObjectsApi()
    try:
        api_instance.patch_namespaced_custom_object(
            group=CHAOS_GROUP,
            version=CHAOS_VERSION,
            namespace=namespace,
            plural=kind_plural,
            name=name,
            body={"metadata": {"finalizers": None}}
        )
        print(f"  Removed finalizers from {kind_plural}/{name}")
        return True
    except ApiException as e:
        print(f"  Warning: Failed to remove finalizers from {kind_plural}/{name}: {e.reason}")
        return False


def force_delete_chaos_resource(namespace: str, kind_plural: str, name: str, timeout: int = 30) -> bool:
    """
    Force delete a chaos resource, removing finalizers if stuck in Terminating state.

    Args:
        namespace: The Kubernetes namespace
        kind_plural: The plural form of the chaos kind
        name: The name of the resource to delete
        timeout: Timeout in seconds to wait for deletion

    Returns:
        True if deleted successfully, False otherwise
    """
    api_instance = client.CustomObjectsApi()

    # First attempt normal delete
    try:
        api_instance.delete_namespaced_custom_object(
            group=CHAOS_GROUP,
            version=CHAOS_VERSION,
            namespace=namespace,
            plural=kind_plural,
            name=name
        )
    except ApiException as e:
        if e.status != 404:
            print(f"  Warning: Initial delete failed for {kind_plural}/{name}: {e.reason}")

    # Wait and check if resource is deleted, remove finalizers if stuck
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            resource = api_instance.get_namespaced_custom_object(
                group=CHAOS_GROUP,
                version=CHAOS_VERSION,
                namespace=namespace,
                plural=kind_plural,
                name=name
            )

            # Check if resource is stuck in Terminating (has deletionTimestamp)
            metadata = resource.get('metadata', {})
            if metadata.get('deletionTimestamp'):
                finalizers = metadata.get('finalizers', [])
                if finalizers:
                    print(f"  {kind_plural}/{name} stuck in Terminating with finalizers: {finalizers}")
                    remove_finalizers(namespace, kind_plural, name)

            time.sleep(2)
        except ApiException as e:
            if e.status == 404:
                return True  # Successfully deleted
            time.sleep(2)

    # Final check
    try:
        api_instance.get_namespaced_custom_object(
            group=CHAOS_GROUP,
            version=CHAOS_VERSION,
            namespace=namespace,
            plural=kind_plural,
            name=name
        )
        print(f"  Warning: {kind_plural}/{name} still exists after {timeout}s")
        return False
    except ApiException as e:
        if e.status == 404:
            return True
        return False


def find_chaos_for_release(namespace: str, release_name: str) -> List[Dict]:
    """
    Find all chaos resources targeting a specific release.

    Args:
        namespace: The Kubernetes namespace where chaos resources are deployed
        release_name: The Milvus release name to search for

    Returns:
        List of dicts with chaos resource info
    """
    matching_resources = []

    for kind_plural in CHAOS_KINDS:
        resources = list_chaos_resources(namespace, kind_plural)

        for resource in resources:
            selector = get_selector_from_chaos_resource(resource)
            matches, matched_labels = check_selector_matches_release(selector, release_name)

            if matches:
                matching_resources.append({
                    'kind': resource.get('kind'),
                    'kind_plural': kind_plural,
                    'name': resource['metadata']['name'],
                    'namespace': resource['metadata']['namespace'],
                    'matched_labels': matched_labels,
                    'creation_timestamp': resource['metadata'].get('creationTimestamp'),
                    'selector': selector
                })

    return matching_resources


def list_all_chaos_resources(namespace: str) -> List[Dict]:
    """
    List all chaos resources in a namespace.

    Args:
        namespace: The Kubernetes namespace

    Returns:
        List of dicts with chaos resource info
    """
    all_resources = []

    for kind_plural in CHAOS_KINDS:
        resources = list_chaos_resources(namespace, kind_plural)

        for resource in resources:
            selector = get_selector_from_chaos_resource(resource)
            label_selectors = selector.get('labelSelectors', {}) if selector else {}

            all_resources.append({
                'kind': resource.get('kind'),
                'kind_plural': kind_plural,
                'name': resource['metadata']['name'],
                'namespace': resource['metadata']['namespace'],
                'creation_timestamp': resource['metadata'].get('creationTimestamp'),
                'label_selectors': label_selectors,
                'target_namespaces': selector.get('namespaces', []) if selector else []
            })

    return all_resources


def print_resource_table(resources: List[Dict], show_selector: bool = False):
    """Print resources in a formatted table."""
    if not resources:
        print("No chaos resources found.")
        return

    print(f"\n{'Kind':<15} {'Name':<50} {'Created':<25} {'Target Labels'}")
    print("-" * 130)

    for r in resources:
        labels = r.get('matched_labels', []) or [f"{k}={v}" for k, v in r.get('label_selectors', {}).items()]
        labels_str = ', '.join(labels[:3])  # Show first 3 labels
        if len(labels) > 3:
            labels_str += f" (+{len(labels)-3} more)"

        print(f"{r['kind']:<15} {r['name']:<50} {r.get('creation_timestamp', 'N/A'):<25} {labels_str}")

    print(f"\nTotal: {len(resources)} resource(s)")


def main():
    parser = argparse.ArgumentParser(
        description='Detect and cleanup Chaos Mesh CRDs for a specific Milvus release',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--release', '-r',
        type=str,
        help='Milvus release name to search for'
    )

    parser.add_argument(
        '--namespace', '-n',
        type=str,
        default=DEFAULT_CHAOS_NAMESPACE,
        help=f'Kubernetes namespace where chaos resources are deployed (default: {DEFAULT_CHAOS_NAMESPACE})'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='List matching chaos resources without deleting (default behavior)'
    )

    parser.add_argument(
        '--delete',
        action='store_true',
        help='Delete all matching chaos resources'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force delete by removing finalizers if resources are stuck in Terminating state (useful for IOChaos)'
    )

    parser.add_argument(
        '--list-all',
        action='store_true',
        help='List all chaos resources in the namespace'
    )

    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt when deleting'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.list_all and not args.release:
        parser.error("Either --release or --list-all must be specified")

    # Initialize k8s client
    try:
        init_k8s_client()
    except Exception as e:
        print(f"Error: Failed to initialize Kubernetes client: {e}")
        sys.exit(1)

    # List all chaos resources
    if args.list_all:
        print(f"\nListing all Chaos Mesh resources in namespace '{args.namespace}'...")
        resources = list_all_chaos_resources(args.namespace)
        print_resource_table(resources)
        return

    # Find chaos resources for release
    print(f"\nSearching for Chaos Mesh resources targeting release '{args.release}' in namespace '{args.namespace}'...")
    resources = find_chaos_for_release(args.namespace, args.release)

    if not resources:
        print(f"No Chaos Mesh resources found targeting release '{args.release}'")
        return

    print_resource_table(resources)

    # Delete if requested
    if args.delete:
        if not args.yes:
            response = input(f"\nAre you sure you want to delete {len(resources)} chaos resource(s)? [y/N]: ")
            if response.lower() != 'y':
                print("Aborted.")
                return

        delete_mode = "force delete" if args.force else "delete"
        print(f"\n{delete_mode.capitalize()}ing {len(resources)} chaos resource(s)...")
        success_count = 0

        for r in resources:
            print(f"  Deleting {r['kind']}/{r['name']}...", end=' ')

            if args.force:
                # Use force delete with finalizer removal for stuck resources
                if force_delete_chaos_resource(r['namespace'], r['kind_plural'], r['name']):
                    print("OK")
                    success_count += 1
                else:
                    print("FAILED")
            else:
                if delete_chaos_resource(r['namespace'], r['kind_plural'], r['name']):
                    print("OK")
                    success_count += 1
                else:
                    print("FAILED")

        print(f"\nDeleted {success_count}/{len(resources)} resource(s)")

    else:
        print("\nRun with --delete to remove these resources")
        print("Run with --delete --force to force delete (removes finalizers)")


if __name__ == '__main__':
    main()
