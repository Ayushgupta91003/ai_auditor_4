import unittest
from pydantic import ValidationError
from agent.translation_contract import TranslationResult
from agent.config import prompt
import test_local_flow as flow

class TranslationContractTests(unittest.TestCase):
    def test_missing_language_rejected(self):
        with self.assertRaises(ValidationError):TranslationResult.model_validate({"text":"Invoice","confidence":1})
    def test_alias_and_name_normalized(self):
        result=TranslationResult.model_validate({"text":"Invoice","confidence":0.9,"source_language":" English "})
        self.assertEqual(result.language,"en")
    def test_invalid_confidence_rejected(self):
        for value in (-1,2,float("nan")):
            with self.assertRaises(ValidationError):TranslationResult(text="Invoice",language="en",confidence=value)
    def test_empty_translation_rejected(self):
        with self.assertRaises(ValidationError):TranslationResult(text="  ",language="en",confidence=1)
    def test_prompt_example_contains_language(self):
        self.assertIn('"language"',prompt("translation"))

class TranslationRetryTests(unittest.TestCase):
    setUp=flow.LocalFlowTests.setUp
    tearDown=flow.LocalFlowTests.tearDown
    process=flow.LocalFlowTests.process
    def test_missing_language_retried_before_stage_is_saved(self):
        import json
        original=self.engine.ask;calls=[]
        def reply(system,data,**kwargs):
            if "Detect the source language" in system:
                calls.append(system)
                if len(calls)==1:return json.dumps({"text":data,"confidence":1,"notes":"missing field"})
                return json.dumps({"text":data,"confidence":1,"language":"en","notes":"corrected"})
            return original(system,data,**kwargs)
        self.engine.ask=reply
        id=self.process()
        self.assertEqual(len(calls),2)
        self.assertEqual(self.store.get(id)["translation"]["language"],"en")
        self.assertEqual(self.store.get(id)["status"],"completed")
    def test_invalid_language_retries_bounded_and_extraction_reused(self):
        import json
        original=self.engine.ask;calls=[]
        def reply(system,data,**kwargs):
            if "Detect the source language" in system:
                calls.append(system);return json.dumps({"text":data,"confidence":1})
            return original(system,data,**kwargs)
        self.engine.ask=reply
        with self.assertRaises(ValueError):self.process()
        self.assertEqual(len(calls),2)
        id=self.store.list()[0]["id"]
        self.assertIsNone(self.store.cached_stage(id,"translation"))
        self.engine.ask=lambda system,data,**kwargs:json.dumps({"text":data,"confidence":1,"language":"en"}) if "Detect the source language" in system else original(system,data,**kwargs)
        self.engine.resume(id)
        self.assertEqual(len(self.extractions),1)
        self.assertEqual(self.store.get(id)["status"],"completed")
