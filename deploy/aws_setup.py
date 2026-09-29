"""One-time AWS setup for the Recall EC2 host (idempotent): a Bedrock-invoke-only role on the instance and port 8300.
Run by the account owner:  python3 deploy/aws_setup.py
"""
import json
import os
import time

import boto3
from botocore.exceptions import ClientError

IID, REGION, SG = os.environ["RECALL_INSTANCE_ID"], os.environ.get("RECALL_REGION", "us-east-1"), os.environ["RECALL_SG_ID"]
iam, ec2 = boto3.client("iam"), boto3.client("ec2", region_name=REGION)
acct = boto3.client("sts").get_caller_identity()["Account"]

assoc = ec2.describe_iam_instance_profile_associations(Filters=[{"Name": "instance-id", "Values": [IID]}])["IamInstanceProfileAssociations"]
if assoc:
    print("instance already has a profile:", assoc[0]["IamInstanceProfile"]["Arn"], "(leaving it alone)")
else:
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    policy = {"Version": "2012-10-17", "Statement": [{
        "Sid": "RecallBedrockInvoke", "Effect": "Allow",
        "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        "Resource": ["arn:aws:bedrock:*::foundation-model/*", f"arn:aws:bedrock:*:{acct}:inference-profile/*"]}]}
    try:
        iam.create_role(RoleName="recall-bedrock", AssumeRolePolicyDocument=json.dumps(trust),
                        Description="Recall app on EC2: invoke Bedrock models only", Tags=[{"Key": "app", "Value": "recall"}])
        print("created role recall-bedrock")
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
    iam.put_role_policy(RoleName="recall-bedrock", PolicyName="bedrock-invoke", PolicyDocument=json.dumps(policy))
    try:
        iam.create_instance_profile(InstanceProfileName="recall-bedrock")
        iam.add_role_to_instance_profile(InstanceProfileName="recall-bedrock", RoleName="recall-bedrock")
        print("created instance profile recall-bedrock")
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
    time.sleep(10)  # IAM propagation
    for _ in range(5):
        try:
            r = ec2.associate_iam_instance_profile(IamInstanceProfile={"Name": "recall-bedrock"}, InstanceId=IID)
            print("associated:", r["IamInstanceProfileAssociation"]["State"])
            break
        except ClientError as e:
            print("retrying:", e.response["Error"]["Message"][:100])
            time.sleep(6)

try:
    ec2.authorize_security_group_ingress(GroupId=SG, IpPermissions=[{
        "IpProtocol": "tcp", "FromPort": 8300, "ToPort": 8300, "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "Recall demo"}]}])
    print("opened tcp/8300")
except ClientError as e:
    print("tcp/8300:", "already open" if "Duplicate" in str(e) else e)
