"""Generate the older-man footage with Amazon Nova Reel 1.1 (multi-shot, same man across shots).

    python3 video/generate_reel.py <s3-bucket-in-us-east-1> [seed]        # starts a job, prints the invocation ARN
    python3 video/generate_reel.py --wait <invocation-arn> <bucket>       # waits, then downloads the shots to video/reel/

Nova Reel 1.1 exists only in us-east-1, writes to S3 (give it the bucket ROOT, not a prefix), and costs $0.08 per
second of video (18 s ≈ $1.44; verified via the AWS Price List API). The prompt below produced the clips used in the
video's opening (seed 7). Afterwards the shots were processed with ffmpeg:
    hue=s=0, scale=720:405, gblur=0.6, noise=alls=8:allf=t, eq=contrast=1.12:brightness=-0.03:gamma=0.95, vignette, scale=1280:720
and trimmed before the model's face drifts (shot 3 is cut at 4.4 s).
"""
import pathlib, sys, time

import boto3

PROMPT = (
    "Home security camera footage recorded in the late evening at blue hour twilight, very dim ambient light with a dark blue sky, "
    "porch lights and warm window lights switched on, slightly grainy wide-angle lens, camera mounted high on the wall and completely "
    "static, no camera movement, no zoom, no pan, no shallow depth of field, everything in focus, no foreground blur, realistic. "
    "The same elderly man appears in every shot: an 81-year-old man with white hair, wearing a blue knitted sweater and khaki trousers, "
    "walking slowly with a slight stoop. He is completely alone, no other people. "
    "Shot 1: high wide fixed view of a suburban driveway at dusk with a garage door on the right and the street at the bottom of the "
    "frame; the elderly man walks slowly up the driveway toward the house. "
    "Shot 2: fixed view of the front porch with the front door lit by a warm porch light; the same elderly man in the blue sweater walks "
    "up the steps to the front door, stops in front of it, then turns and walks along the side of the house. "
    "Shot 3: high wide fixed view of the back garden behind the house at dusk: a lawn, a wooden fence, a patio with a table and chairs, "
    "and a sliding glass back door with a light on inside; the same elderly man in the blue sweater walks slowly across the lawn toward "
    "the back door.")

client = boto3.client("bedrock-runtime", region_name="us-east-1")

if sys.argv[1] == "--wait":
    arn, bucket = sys.argv[2], sys.argv[3]
    while True:
        r = client.get_async_invoke(invocationArn=arn)
        if r["status"] != "InProgress":
            break
        time.sleep(20)
    print(r["status"], r.get("failureMessage") or "")
    if r["status"] == "Completed":
        s3, out = boto3.client("s3", region_name="us-east-1"), pathlib.Path(__file__).parent / "reel"
        out.mkdir(exist_ok=True)
        for o in s3.list_objects_v2(Bucket=bucket, Prefix=arn.split("/")[-1] + "/").get("Contents", []):
            if o["Key"].endswith(".mp4"):
                s3.download_file(bucket, o["Key"], str(out / o["Key"].split("/")[-1])); print("downloaded", o["Key"])
else:
    bucket, seed = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 7
    r = client.start_async_invoke(
        modelId="amazon.nova-reel-v1:1",
        modelInput={"taskType": "MULTI_SHOT_AUTOMATED", "multiShotAutomatedParams": {"text": PROMPT},
                    "videoGenerationConfig": {"seed": seed, "durationSeconds": 18, "fps": 24, "dimension": "1280x720"}},
        outputDataConfig={"s3OutputDataConfig": {"s3Uri": f"s3://{bucket}"}})
    print(r["invocationArn"])
