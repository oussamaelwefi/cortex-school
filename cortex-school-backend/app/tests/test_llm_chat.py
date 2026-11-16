"""Provider selection and safe error handling; no network or database access."""
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from openai import AuthenticationError, RateLimitError

from ai.llm import LLMNotConfiguredError, LLMProviderError, ainvoke, get_chat_model
from core.config import settings


class ChatProviderTests(unittest.TestCase):
    def test_openrouter_uses_its_own_endpoint_and_model(self):
        with patch.object(settings.llm, 'OPENROUTER_API_KEY', 'test-router-key'), \
             patch.object(settings.llm, 'OPENROUTER_MODEL', 'openai/gpt-4.1-mini'), \
             patch('ai.llm.ChatOpenAI') as factory:
            get_chat_model()
            args = factory.call_args.kwargs
            self.assertEqual(args['base_url'], 'https://openrouter.ai/api/v1')
            self.assertEqual(args['api_key'], 'test-router-key')
            self.assertEqual(args['model'], 'openai/gpt-4.1-mini')

    def test_openai_key_uses_openai_without_router_override(self):
        with patch.object(settings.llm, 'OPENROUTER_API_KEY', ''), \
             patch.object(settings.llm, 'OPENAI_API_KEY', 'test-openai-key'), \
             patch('ai.llm.ChatOpenAI') as factory:
            get_chat_model()
            self.assertNotIn('base_url', factory.call_args.kwargs)

    def test_misplaced_router_key_is_rejected_before_network(self):
        with patch.object(settings.llm, 'OPENROUTER_API_KEY', ''), \
             patch.object(settings.llm, 'OPENAI_API_KEY', 'sk-or-test'):
            with self.assertRaisesRegex(LLMNotConfiguredError, 'Move it to'):
                get_chat_model()


class ChatErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_authentication_failure_is_safe_and_actionable(self):
        response = httpx.Response(401, request=httpx.Request('POST', 'https://example.invalid'))
        failure = AuthenticationError('sensitive provider body', response=response, body=None)
        model = AsyncMock()
        model.ainvoke.side_effect = failure
        with patch('ai.llm.get_chat_model', return_value=model):
            with self.assertRaises(LLMProviderError) as caught:
                await ainvoke('hello')
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn('rejected the API key', str(caught.exception))
        self.assertNotIn('sensitive', str(caught.exception))

    async def test_rate_limit_preserves_retryable_status(self):
        response = httpx.Response(429, request=httpx.Request('POST', 'https://example.invalid'))
        model = AsyncMock()
        model.ainvoke.side_effect = RateLimitError('quota', response=response, body=None)
        with patch('ai.llm.get_chat_model', return_value=model):
            with self.assertRaises(LLMProviderError) as caught:
                await ainvoke('hello')
        self.assertEqual(caught.exception.status_code, 429)


if __name__ == '__main__':
    unittest.main()
