import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import errors

from services import llm_service


PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODEL = "gemini-3.6-flash"


def quota_error():
    return errors.ClientError(
        429,
        {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota exceeded"}},
    )


class FakeModels:
    def __init__(self, outcomes, calls):
        self.outcomes = outcomes
        self.calls = calls

    def generate_content(self, **kwargs):
        model = kwargs["model"]
        self.calls.append(model)
        outcome = self.outcomes[model]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes, calls, **kwargs):
        self.models = FakeModels(outcomes, calls)


class GeminiFallbackTests(unittest.TestCase):
    def make_client_factory(self, outcomes, calls):
        return lambda **kwargs: FakeClient(outcomes, calls, **kwargs)

    def run_chat(self, outcomes):
        calls = []
        with (
            patch.object(llm_service, "GEMINI_API_KEY", "AIzaTestCredentialForUnitTests"),
            patch.object(llm_service, "GEMINI_MODEL", PRIMARY_MODEL),
            patch.object(llm_service, "has_google_api_key_format", return_value=True),
            patch.object(llm_service.genai, "Client", self.make_client_factory(outcomes, calls)),
            patch.object(llm_service.time, "sleep"),
        ):
            result = llm_service.chat_with_assistant(
                [{"role": "user", "content": "What should I do during a flood?"}]
            )
        return result, calls

    def test_primary_quota_error_calls_fallback_without_retrying_primary(self):
        fallback_response = SimpleNamespace(
            text="Move to higher ground if it is safe to do so.",
            usage_metadata=None,
            candidates=[],
            prompt_feedback=None,
        )
        result, calls = self.run_chat({
            PRIMARY_MODEL: quota_error(),
            FALLBACK_MODEL: fallback_response,
        })

        self.assertEqual(calls, [PRIMARY_MODEL, FALLBACK_MODEL])
        self.assertTrue(result["success"])
        self.assertEqual(result["model"], FALLBACK_MODEL)

    def test_successful_fallback_returns_its_generated_answer(self):
        answer = "Move to higher ground and follow local emergency instructions."
        result, calls = self.run_chat({
            PRIMARY_MODEL: quota_error(),
            FALLBACK_MODEL: SimpleNamespace(
                text=answer,
                usage_metadata=None,
                candidates=[],
                prompt_feedback=None,
            ),
        })

        self.assertEqual(calls, [PRIMARY_MODEL, FALLBACK_MODEL])
        self.assertTrue(result["success"])
        self.assertEqual(result["reply"], answer)
        self.assertEqual(result["model"], FALLBACK_MODEL)

    def test_failure_of_both_models_reports_fallback_failure(self):
        result, calls = self.run_chat({
            PRIMARY_MODEL: quota_error(),
            FALLBACK_MODEL: quota_error(),
        })

        self.assertEqual(calls, [PRIMARY_MODEL, FALLBACK_MODEL])
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "rate_limited")
        self.assertIn(FALLBACK_MODEL, result["reply"])
        self.assertIn("quota or rate limit", result["reply"])


if __name__ == "__main__":
    unittest.main()
