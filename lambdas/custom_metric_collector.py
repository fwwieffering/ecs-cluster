import logging
import datetime
import json

import dateutil
import boto3

from cluster_stats import ClusterStatAggregator

logger = logging.getLogger()
logging.basicConfig()
logger.setLevel(logging.INFO)

cw = boto3.client('cloudwatch')

def send_cluster_metrics(cluster):
    r = cw.put_metric_data(
        Namespace='AWS/ECS',
        MetricData=[{
            "MetricName": "AdditionalTasks",
            "Dimensions": [{
                "Name": "ClusterName",
                "Value": cluster.cluster
            }],
            "Timestamp": datetime.datetime.now(dateutil.tz.tzlocal()),
            "Value": cluster.free_spaces
        }]
    )
    logger.info('Cloudwatch metric sent {}'.format(r))

def main(event, context):
    logger.info(json.dumps(event))
    cluster = ClusterStatAggregator(event["Cluster"])
    logger.info('\n{}'.format(cluster))
    send_cluster_metrics(cluster)
