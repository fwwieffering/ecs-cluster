import boto3
import traceback
import logging
import json
import datetime
import os
from lifecycle_event import LifecycleEvent

# default is for testing
state_fxn_arn = os.environ.get("STATE_FUNCTION", "arn:aws:states:us-east-1:056684691971:stateMachine:fake_state_machine")

logger = logging.getLogger()
logging.basicConfig()
logger.setLevel(logging.INFO)

def main(event):
    ecs_event = LifecycleEvent(event)
    # sns kicks off state machine
    step = boto3.client('stepfunctions')
    # set end time
    # end time = task timeout time + 1m for stopped tasks to start on another host
    endtime = datetime.datetime.now() + datetime.timedelta(seconds=ecs_event.ecs_timeout) + datetime.timedelta(minutes=1)
    ecs_event.event["endtime"] = endtime.isoformat()
    ecs_event.set_type("state_machine:init")
    logger.info('Starting state function for instance {}'.format(ecs_event.ec2instanceid))
    logger.info('State function input: \n{}'.format(json.dumps(ecs_event.event)))
    step.start_execution(
        stateMachineArn=state_fxn_arn,
        input=json.dumps(ecs_event.event)
    )
    return ecs_event.event

def lambda_handler(event, context):
    logger.info(json.dumps(event))
    try:
        main(event)
    except Exception as err:
        print(err)
        traceback.print_exc()
