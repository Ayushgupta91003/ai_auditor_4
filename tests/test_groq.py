import json
import os
import unittest
from unittest.mock import patch
import httpx
from agent.groq_client import complete,request,ProviderError
from agent.llm import parse_json
from agent.local_vectors import vectorize,similarity

class GroqTests(unittest.TestCase):
    def test_missing_key_is_actionable(self):
        with patch.dict(os.environ,{"GROQ_API_KEY":""}):
            with self.assertRaisesRegex(ProviderError,"GROQ_API_KEY"): request("/models")
    def test_chat_uses_groq_only(self):
        seen=[]
        def handler(r):
            seen.append(r)
            return httpx.Response(200,json={"choices":[{"message":{"content":"answer"}}]})
        with patch.dict(os.environ,{"GROQ_API_KEY":"test-sentinel-not-real"}),httpx.Client(transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(complete("qwen/test",[{"role":"user","content":"test"}],client),"answer")
        self.assertEqual(seen[0].url.host,"api.groq.com")
        self.assertEqual(json.loads(seen[0].content)["model"],"qwen/test")
    def test_error_does_not_leak_provider_body(self):
        with patch.dict(os.environ,{"GROQ_API_KEY":"test-sentinel-not-real"}),httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(401,text="private-secret-response"))) as client:
            with self.assertRaises(ProviderError) as error: request("/models",client=client)
        self.assertNotIn("private-secret",str(error.exception))
        self.assertNotIn("test-sentinel",str(error.exception))
    def test_rate_limit_retries_are_bounded(self):
        calls=[]
        def handler(r): calls.append(r); return httpx.Response(429)
        with patch.dict(os.environ,{"GROQ_API_KEY":"test-sentinel-not-real"}),patch("agent.groq_client.time.sleep"),httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(ProviderError,"rate limit"): request("/models",client=client)
        self.assertEqual(len(calls),3)
    def test_successful_retry(self):
        replies=[httpx.Response(503),httpx.Response(200,json={"data":[]})]
        with patch.dict(os.environ,{"GROQ_API_KEY":"test-sentinel-not-real"}),patch("agent.groq_client.time.sleep"),httpx.Client(transport=httpx.MockTransport(lambda r:replies.pop(0))) as client:
            self.assertEqual(request("/models",client=client),{"data":[]})
    def test_openai_model_rejected(self):
        with self.assertRaisesRegex(ProviderError,"non-OpenAI"): complete("openai/gpt-oss-120b",[])
    def test_unexpected_endpoint_rejected(self):
        with patch.dict(os.environ,{"GROQ_API_KEY":"test-sentinel-not-real"}):
            with self.assertRaises(ValueError): request("https://untrusted.invalid")
    def test_reasoning_fenced_json(self):
        self.assertEqual(parse_json('<think>internal</think>\n```json\n{"a":1}\n```'),{"a":1})
    def test_json_array_rejected(self):
        with self.assertRaises(ValueError): parse_json("[]")
    def test_lexical_vectors_are_deterministic_and_normalized(self):
        import math
        a=vectorize("invoice price mismatch"); b=vectorize("invoice price mismatch")
        self.assertEqual(a,b); self.assertAlmostEqual(math.sqrt(sum(x*x for x in a)),1)
        self.assertGreater(similarity(a,b),similarity(a,vectorize("forest mountain landscape")))
