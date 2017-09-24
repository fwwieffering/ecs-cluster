import boto3
import time
import logging
import datetime
import json
from pprint import pprint

logger = logging.getLogger()
logging.basicConfig()
logger.setLevel(logging.INFO)

# quickly convert minutes, hours, seconds to seconds
time_convert = {
    'm': 60,
    'h': 3600,
    's': 1
}

class LifecycleEvent:
    ecs = boto3.client('ecs')
    asg = boto3.client('autoscaling')

    def __init__(self, event):
        self.event = event
        self.message = json.loads(event['Records'][0]['Sns']['Message'])
        self.type = self.get_type(self.event)
        self.ecsinstanceid = self.get_ecs_instance()


    def get_type(self, event):
        event_source = event['Records'][0]['EventSource']
        self.set_initial()
        # if its the init, set heartbeat timeout
        if "aws:sns" in event_source:
            self.send_heartbeat()
            return "sns"
        else:
            return event_source


    def get_ecs_instance(self):
        # if not init this should be set
        if self.event.get("containerInstanceArn"):
            return self.event["containerInstanceArn"]
        # this sucks. Only way to link EC2 Instance + ECS Instance
        # is to list all containers for cluster, then describe each instance
        # and check for the EC2InstanceID
        else:
            pager = self.ecs.get_paginator("list_container_instances")
            iterator = pager.paginate(cluster=self.ecs_cluster)
            instance_info = []
            for page in iterator:
                full_instances = self.ecs.describe_container_instances(
                    cluster=self.ecs_cluster,
                    containerInstances=page['containerInstanceArns']
                    )["containerInstances"]

                instance_info.extend(full_instances)
            matching_instance = [i for i in instance_info if i["ec2InstanceId"] == self.ec2instanceid]
            if matching_instance:
                # save to event
                self.event["containerInstanceArn"] = matching_instance[0]["containerInstanceArn"]
                logger.info("Found container instance {} for ec2Instance {}".format(matching_instance[0]["containerInstanceArn"], self.ec2instanceid))
                return matching_instance[0]["containerInstanceArn"]
            else:
                logger.error('Unable to find corresponding ecsInstanceId in cluster {} for ec2InstanceId {}'.format(self.ecs_cluster, self.ec2instanceid))


    def set_type(self, t):
        self.event['Records'][0]['EventSource'] = t
        # for state machine checking
        self.event["state"] = t


    def set_initial(self):
        # Parse SNS message for required data.
        self.ec2instanceid = self.message['EC2InstanceId']
        self.stackname = self.message['NotificationMetadata']
        self.asgname = self.message['AutoScalingGroupName']
        self.lifecycleactiontoken = self.message['LifecycleActionToken']
        self.lifecyclehookname = self.message['LifecycleHookName']
        # load metadata
        metadata = json.loads(self.message['NotificationMetadata'])
        self.ecs_cluster = metadata["ecs_cluster"]
        # timeout formatted something like 1m, 300s, etc
        raw_timeout = str(metadata["ecs_timeout"])
        unit = raw_timeout[-1]
        self.ecs_timeout = int(raw_timeout[:-1]) * time_convert[unit]
        # param passed by init function
        self.endtime = None
        if self.event.get("endtime"):
            self.endtime = datetime.datetime.strptime(self.event.get("endtime"), '%Y-%m-%dT%H:%M:%S.%f')


    def drain_instance(self):
        try:
            self.ecs.update_container_instances_state(
                cluster=self.ecs_cluster,
                containerInstances=[self.ecsinstanceid],
                status='DRAINING'
            )
            logger.info("Set instance {} to DRAINING".format(self.ec2instanceid))
        except Exception as e:
            logger.error(e)


    def check_done(self):
        try:
            tasks = self.ecs.list_tasks(
                cluster = self.ecs_cluster,
                containerInstance = self.ecsinstanceid,
                desiredStatus = 'RUNNING'
            )
            if tasks.get('taskArns'):
                logger.info("{} tasks still running on {} - waiting....".format(str(len(tasks.get('taskArns'))),
                                                                                self.ec2instanceid))
                return False
            else:
                logger.info("No tasks running on {}".format(self.ec2instanceid))
                return True
        except Exception as e:
            logger.error(e)


    def send_heartbeat(self):
        try:
            self.asg.record_lifecycle_action_heartbeat(
                LifecycleHookName=self.lifecyclehookname,
                AutoScalingGroupName=self.asgname,
                LifecycleActionToken=self.lifecycleactiontoken,
                InstanceId=self.ec2instanceid
            )
            logger.info("Sending heartbeat to instance {} in asg {}".format(self.ec2instanceid, self.asgname))
        except Exception as e:
            logger.error(e)


    def complete_asg_lifecycle(self, testing=False):
        if not testing:
            try:
                res = self.asg.complete_lifecycle_action(
                    LifecycleHookName=self.lifecyclehookname,
                    AutoScalingGroupName=self.asgname,
                    LifecycleActionToken=self.lifecycleactiontoken,
                    LifecycleActionResult='CONTINUE',
                    InstanceId=self.ec2instanceid
                )
                logger.info("ASG Complete Lifecycle Action Response: %s" % res[u'ResponseMetadata'][u'HTTPStatusCode'])
            except Exception as e:
                logger.error(e)
