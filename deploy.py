#!/usr/bin/env python3
import os
import zipfile
import boto3
import botocore
import hashlib
import io
import yaml
import time


def load_config():
    with open("config.yml") as f:
        config = yaml.load(f.read())
    return config


def package_lambda(config):
    print("Packaging lambda function...")
    s3 = boto3.client('s3', region_name=config["region"])

    zip_contents = io.BytesIO()
    zippy = zipfile.ZipFile(zip_contents, mode="w")
    for script in os.scandir("./lambdas/"):
        path = script.path
        zippy.write(path, arcname=script.name)
    zippy.close()

    zip_contents.seek(0)
    sha = hashlib.sha256()
    sha.update(zip_contents.read())
    s3_path = "ecs/lambdas/{}/code.zip".format(sha.hexdigest())
    if config["Environment"]:
        s3_path = config["Environment"] + "/" + s3_path
    zip_contents.seek(0)

    print("Uploading lambda function to s3://{}/{}".format(config["S3Bucket"], s3_path))
    s3.put_object(
        Bucket=config["S3Bucket"],
        Key=s3_path,
        Body=zip_contents
    )

    return s3_path


def format_params(config):
    # not every config item is a param. Blacklist:
    config_blacklist =["region"]
    # if AmiId is not provided we need to discover it
    if not config["AmiId"]:
        ec2 = boto3.client('ec2', region_name=config["region"])
        imgs = ec2.describe_images(
            Filters=[
                {
                    "Name": "state",
                    "Values": ["available"]
                },
                {
                    "Name": "virtualization-type",
                    "Values": ["hvm"]
                },
                {
                    "Name": "architecture",
                    "Values": ["x86_64"]
                },
                {
                    "Name": "owner-id",
                    "Values": ["591542846629"]
                },
                {
                    "Name": "name",
                    "Values": ["amzn-ami-*-amazon-ecs-optimized"]
                }
            ]
        ).get("Images")
        sorted_imgs = sorted(imgs, key=lambda k: k["CreationDate"])
        config["AmiId"] = sorted_imgs[-1]["ImageId"]
        print("Found AMI: {}".format(config["AmiId"]))
    params = []
    for k, v in config.items():
        if v and k not in config_blacklist:
            params.append({
                "ParameterKey": k,
                "ParameterValue": str(v)
            })
    return params


def call_cloudformation(template, cluster_name, params, region, environment):
    stack_name = cluster_name + "-ecs-" + template.split('-')[0] + "-stack"
    if environment:
        stack_name = environment + "-" + stack_name

    cfn = boto3.client("cloudformation", region_name=region)
    # check if stack exists
    with open("./templates/"+ template) as f:
        body = f.read()
    try:
        cfn.create_stack(
            TemplateBody=body,
            StackName=stack_name,
            Parameters=params,
            Capabilities=["CAPABILITY_NAMED_IAM"]
        )
        wait_on_stack(cfn, stack_name, "create")
    except botocore.exceptions.ClientError as e:
        print(e)
        if "AlreadyExistsException" in str(e):
            try:
                cfn.update_stack(
                    TemplateBody=body,
                    StackName=stack_name,
                    Parameters=params,
                    Capabilities=["CAPABILITY_NAMED_IAM"]
                )
                wait_on_stack(cfn, stack_name, "update")
            except botocore.exceptions.ClientError:
                pass


def wait_on_stack(client, stack_name, stack_action):
    counter = 1
    for time_to_wait in range(counter, 30, 1):

        res = client.describe_stacks(
            StackName=stack_name)
        if res['Stacks'][0]['StackStatus'] == '{}_IN_PROGRESS'.format(
                stack_action.upper()):
            time.sleep(30)
            print("Waiting on CloudFormation...")

        elif res['Stacks'][0][
                'StackStatus'] == 'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS':
            time.sleep(30)
            print("Almost done, Cleaning up.")

        elif res['Stacks'][0]['StackStatus'] == '{}_COMPLETE'.format(
                stack_action.upper()):
            return
        else:
            print("Deploy failed: {}".format(
                res['Stacks'][0]['StackStatus']))
            raise


def main():
    config = load_config()
    config["S3Key"] = package_lambda(config)
    params = format_params(config)
    for t in ["cluster-template.json", "lambda-template.json", "compute-template.json"]:
        print("Deploying {} to {}".format(t, config["region"]))
        call_cloudformation(t, config["ClusterName"], params, config["region"], config["Environment"])


if __name__ == '__main__':
    main()
