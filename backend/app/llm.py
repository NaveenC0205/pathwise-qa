"""Server-owned model configuration with validated selection and bounded retries."""
import asyncio
import ssl
from dataclasses import dataclass
import httpx
from .config import get_settings

@dataclass
class CompletionRequest:
    prompt: str
    system: str = ''
    max_tokens: int = 9000
    purpose: str = ''

@dataclass
class Completion:
    text: str
    model: str
    provider: str

class LLMRouter:
    def __init__(self, model=''):
        self.settings = get_settings()
        self.model = model or self.settings.llm_model
        if self.model not in self.settings.models: raise ValueError('Choose a model enabled in the server model list.')
        self.provider_name = self.settings.llm_provider
    async def complete(self, req):
        s = self.settings
        if self.provider_name == 'ollama':
            url = s.ollama_base_url.rstrip('/') + '/api/generate'
            headers = {}
            payload = {'model': self.model, 'system': req.system, 'prompt': req.prompt, 'stream': False, 'format': 'json', 'options': {'num_predict': req.max_tokens, 'temperature': 0}}
        else:
            if not s.openai_api_key: raise ValueError('No model API key configured on the server. Add it to .env or use Offline draft.')
            url = s.openai_base_url.rstrip('/') + '/chat/completions'
            headers = {'Authorization': 'Bearer ' + s.openai_api_key}
            payload = {'model': self.model, 'messages': [{'role': 'system', 'content': req.system}, {'role': 'user', 'content': req.prompt}], 'response_format': {'type': 'json_object'}}
            if self.model.startswith(('gpt-5', 'o1', 'o3', 'o4')): payload['max_completion_tokens'] = req.max_tokens
            else: payload.update(max_tokens=req.max_tokens, temperature=0)
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=s.llm_timeout_s) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                text = data.get('response', '') if self.provider_name == 'ollama' else data['choices'][0]['message']['content'] or ''
                return Completion(text=text, model=self.model, provider=self.provider_name)
            except (httpx.TransportError, ssl.SSLError):
                if attempt == 2: raise ValueError('The model connection failed after retries. Check the provider or retry this run.')
                await asyncio.sleep(attempt + 1)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (429, 500, 502, 503) and attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1)); continue
                raise ValueError(f'Model service returned HTTP {exc.response.status_code}. Check access, quota and model selection.') from exc
