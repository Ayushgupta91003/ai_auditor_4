"""Inspect container AWS credential availability without printing credential values."""
import os
import boto3

def main():
    print("AWS region:", os.getenv("AWS_REGION", "us-east-1"))
    try:
        credentials = boto3.Session().get_credentials()
        if credentials is None:
            raise RuntimeError("NoCredentials")
        credentials.get_frozen_credentials()
    except Exception as error:
        print("AWS credential discovery: FAILED (" + type(error).__name__ + ")")
        print("The agent container cannot obtain lab credentials. Follow START_HERE_NUVEPRO.md authentication options.")
        raise SystemExit(1) from None
    print("AWS credential discovery: OK; provider=" + credentials.method)
    print("No credential values displayed. Next run: python -m agent.bedrock_check")
    print("Credential discovery does not establish Bedrock model permission.")

if __name__ == "__main__":
    main()
