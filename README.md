## ECS Cluster
Bootstraps an ECS Cluster

### Usage
#### Requirements
Requires the `boto3` python package and python3. AWS permissions are needed in order to run the deployment
#### Configuration
Configuration options are stored in the file `config.yml`
#### Invoking
Just type `make`!

### Components

#### ECS Cluster
Creates an ECS Cluster and cluster Security Group for use in ECS Service load balancers.

#### Auto Scaling Group
Configures an autoscaling group that will attach to the ECS Cluster on startup. The instance type, ami ID and initial group size are configurable.

The ASG will automatically expand/contract to fit the needs of the cluster until it reaches its upper/lower bound. The scaling is based upon a custom Cloudwatch metric that is posted by the [metric lambda](#Metric Lambda)

When scaling in, the instances to be terminated have their tasks stopped gracefully by the [lifecycle lambda](#Lifecycle Lambda)

#### Serverless functions

##### Metric Lambda
Runs on a 1 minute cron and posts a metric `AdditionalTasks` to cloudwatch that is used for scaling the [auto scaling group](#Auto Scaling Group)

`AdditionalTasks` is the number of additional tasks that can be scheduled on the cluster. It is calculated by finding the most resource intensive task and determining how many more times it can fit on the cluster.

##### Lifecycle Lambda
Upon instance shutdown sets the instance to `DRAINING`. Checks back until either the configurable `TaskStopTimeout` has been reached or all tasks have stopped, and then terminates the instance.
