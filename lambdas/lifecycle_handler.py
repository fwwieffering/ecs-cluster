import boto3
import traceback
import logging
import json
import os
import datetime
from lifecycle_event import LifecycleEvent

logger = logging.getLogger()
logging.basicConfig()
logger.setLevel(logging.INFO)

def main(event):
    ecs_event = LifecycleEvent(event)
    endtime = ecs_event.endtime
    logger.info("Event Type: {}".format(ecs_event.type))
    if ecs_event.type == "state_machine:init":
        # set instance to draining
        ecs_event.drain_instance()
        # send heartbeat
        ecs_event.send_heartbeat()
        # set event_type
        ecs_event.set_type("state_machine:retry")
        return ecs_event.event
    else:
        # send heartbeat
        ecs_event.send_heartbeat()
        if ecs_event.check_done():
            ecs_event.set_type("state_machine:end")
            ecs_event.complete_asg_lifecycle()
            return ecs_event.event
        elif datetime.datetime.now() > ecs_event.endtime:
            logger.info('Instance {} passed its endtime of {} and is being shut down'.format(ecs_event.ec2instanceid, ecs_event.event["endtime"]))
            ecs_event.set_type("state_machine:end")
            ecs_event.complete_asg_lifecycle()
            return ecs_event.event
        else:
            logger.info('Checking back in a bit on {}'.format(ecs_event.ec2instanceid))
            return ecs_event.event

def lambda_handler(event, context):
    logger.info(json.dumps(event))
    try:
        return main(event)
    except Exception as err:
        print(err)
        traceback.print_exc()
