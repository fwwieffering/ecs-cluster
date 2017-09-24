import logging
import json
import sys

import boto3
import botocore

logger = logging.getLogger()
logging.basicConfig()
logger.setLevel(logging.INFO)

class ClusterStatAggregator(object):

    def __init__(self, cluster):
        self.ecs = boto3.client('ecs')
        self.cluster = cluster
        self.setup_instance_stats()
        self.setup_services_stats()
        self.calculate_usage_info()

        self.output = {
            "cluster": self.cluster,
            "cluster_cpu": self.cpu,
            "cluster_memory": self.memory,
            "resource_pairs": self.resource_pairs,
            "services": self.services,
            "services_required_resources": self.service_requirements,
            "largest_service": self.largest,
            "free_spaces": self.free_spaces,
            "desired_tasks": self.desired_tasks,
            "percentage_occupied": self.percentage_occupied
        }

    def __repr__(self):
        return json.dumps(self.output, sort_keys=True, indent=4)

    def calculate_usage_info(self):
        """Calculate the count of the largest service that can still be scheduled"""
        if self.largest:
            spaces = 0
            for pair in self.resource_pairs:
                cpu_fits = pair[0]/self.largest["cpu_per_task"]
                mem_fits = pair[1]/self.largest["memory_per_task"]
                fits = min(cpu_fits, mem_fits)
                spaces += fits
            self.free_spaces = spaces
            # calculating percentage occupied as
            # (total # of tasks running) / (tasks running + spaces that the larges task can fit into)
            self.percentage_occupied = float(self.desired_tasks) / (self.desired_tasks + self.free_spaces)
        else:
            logger.info("No Services on cluster")
            self.free_spaces = 999999
            self.percentage_occupied = 0

        logger.info("Number of schedulable tasks for most resource heavy task: {}".format(self.free_spaces))
        logger.info("Total number of desired tasks across all services: {}".format(self.desired_tasks))

    def _get_container_instances(self):
        """Generator that yields all of the ContainerInstances on self.cluster"""
        pager = self.ecs.get_paginator("list_container_instances")
        iterator = pager.paginate(cluster=self.cluster)
        for page in iterator:
            arns = page["containerInstanceArns"]
            for arn in arns:
                yield arn

    def _resolve_container_instances(self):
        """Generator that yields all containerInstance information on self.cluster"""
        instance_arns = list(self._get_container_instances())

        def chunks(l, n):
            """Yield successive n-sized chunks from l."""
            for i in range(0, len(l), n):
                yield l[i:i + n]

        for batch in chunks(instance_arns, 50):
            instances = self.ecs.describe_container_instances(
                cluster=self.cluster,
                containerInstances=batch)["containerInstances"]
            for instance in instances:
                yield instance

    def setup_instance_stats(self):
        logger.info("Collecting instance resource statistics")
        instances = list(self._resolve_container_instances())

        # resource statistics
        cpu = {"total": 0, "free": 0}
        memory = {"total": 0, "free": 0}
        # hold resource pairs (cpu, memory)
        resource_pairs = []

        for instance in instances:
            free_cpu = [item["integerValue"] for item in instance["remainingResources"] if item["name"] == "CPU"][0]
            free_mem = [item["integerValue"] for item in instance["remainingResources"] if item["name"] == "MEMORY"][0]

            total_cpu = [item["integerValue"] for item in instance["registeredResources"] if item["name"] == "CPU"][0]
            total_mem = [item["integerValue"] for item in instance["registeredResources"] if item["name"] == "MEMORY"][0]

            # for some reason, when the cluster is empty
            cpu["total"] += total_cpu
            cpu["free"] += free_cpu
            memory["total"] += total_mem
            memory["free"] += free_mem

            resource_pairs.append((free_cpu, free_mem))

        self.cpu = cpu
        self.memory = memory
        self.resource_pairs = resource_pairs

        logger.info("Cluster CPU - Total: {}, Free: {}".format(str(cpu["total"]), str(cpu["free"])))
        logger.info("Cluster Memory - Total: {}, Free: {}".format(str(memory["total"]), str(memory["free"])))

    def _get_service_arns(self):
        """Generator that yields all of the ARNs for ECS services on self.cluster."""
        pager = self.ecs.get_paginator("list_services")
        iterator = pager.paginate(cluster=self.cluster, PaginationConfig={'MaxItems': 10})
        for page in iterator:
            arns = page["serviceArns"]
            for arn in arns:
                yield arn

    def _resolve_ecs_services(self):
        """Generator that yields all service definitions ECS services on self.cluster."""
        # http://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks
        def chunks(l, n):
            """Yield successive n-sized chunks from l."""
            for i in range(0, len(l), n):
                yield l[i:i + n]

        service_arns = list(self._get_service_arns())

        for batch in chunks(service_arns, 10):
            services = self.ecs.describe_services(cluster=self.cluster, services=batch)['services']
            for service in services:
                yield service

    def _get_service_stats(self, ecs_service):
        """Returns stats about the service for use in calculating and publishing metrics.

        Args:
            ecs_service: the ECS service details as returned from boto3.ecs.describe_service

        Returns:
            A dictionary containing details about the service.
        """
        task_def = self.ecs.describe_task_definition(taskDefinition=ecs_service["taskDefinition"])
        container_defs = task_def["taskDefinition"]["containerDefinitions"]
        svc_stats = {
            "name": ecs_service["serviceName"],
            "desired": ecs_service["desiredCount"],
            "running": ecs_service["runningCount"] + ecs_service["pendingCount"],
            "containers": [
                {
                    "name": container["name"],
                    "cpu": container["cpu"],
                    "memory": int(max(container.get("memory", 0),
                                      container.get("memoryReservation", 0))),
                }
                for container in container_defs
            ]
        }
        svc_stats['cpu_per_task'] = sum((container['cpu'] for container in svc_stats['containers']))
        svc_stats['cpu_requirement'] = svc_stats['cpu_per_task'] * svc_stats['desired']

        svc_stats['memory_per_task'] = sum((container['memory'] for container in svc_stats['containers']))
        svc_stats['memory_requirement'] = svc_stats['memory_per_task'] * svc_stats['desired']

        return svc_stats

    # need to collect service desired/running counts, as well as resource needs
    def setup_services_stats(self):
        logger.info("Collecting services statistics")
        ecs_services = list(self._resolve_ecs_services())

        self.services= [self._get_service_stats(ecs_service) for ecs_service in ecs_services]

        self.desired_tasks = sum((service['desired'] for service in self.services))

        self.service_requirements = {
            'cpu' : sum((service['cpu_requirement'] for service in self.services)),
            'memory': sum((service['memory_requirement'] for service in self.services))
        }

        try:
            self.largest = list(reversed(sorted(self.services, key=lambda svc: svc['memory_per_task'])))[0]
        except IndexError:
            self.largest = None
