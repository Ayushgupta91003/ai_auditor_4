"""Actual Bedrock Converse/LiteLLM adapter, with the AWS HTTP response stubbed."""
import importlib.util
import os
import unittest
from unittest.mock import patch
AVAILABLE=importlib.util.find_spec("langchain_aws") is not None and importlib.util.find_spec("boto3") is not None
@unittest.skipUnless(AVAILABLE,"Install full requirements for Bedrock Converse gateway tests")
class BedrockGatewayTests(unittest.TestCase):
    def test_bedrock_converse_through_litellm(self):
        from pathlib import Path
        from botocore.stub import Stubber
        from agent import llm
        from agent.settings import settings
        cache=Path(__file__).resolve().parents[1]/".local/tiktoken";cache.mkdir(parents=True,exist_ok=True)
        env={"AWS_ACCESS_KEY_ID":"test-only-not-real","AWS_SECRET_ACCESS_KEY":"test-only-not-real","AWS_EC2_METADATA_DISABLED":"true",
            "TIKTOKEN_CACHE_DIR":str(cache),"LITELLM_LOCAL_MODEL_COST_MAP":"True","LANGFUSE_PUBLIC_KEY":""}
        with patch.dict(os.environ,env),patch.object(settings,"provider","bedrock"):
            llm.chat_client.cache_clear()
            model=llm.chat_client("amazon.nova-lite-v1:0")
            self.assertEqual(type(model).__name__,"ChatBedrockConverse")
            response={"output":{"message":{"role":"assistant","content":[{"text":"Stubbed Bedrock Converse response"}]}},
                "stopReason":"end_turn","usage":{"inputTokens":10,"outputTokens":5,"totalTokens":15},"metrics":{"latencyMs":1}}
            with Stubber(model.client) as stub:
                stub.add_response("converse",response)
                answer=llm.ask("You are a test assistant","Synthetic test input",model="amazon.nova-lite-v1:0")
                self.assertEqual(answer,"Stubbed Bedrock Converse response")
                stub.assert_no_pending_responses()
