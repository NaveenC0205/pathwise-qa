from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
ROOT = Path(__file__).resolve().parents[2]
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / '.env'), extra='ignore')
    llm_provider: str = 'openai'
    openai_api_key: str = ''
    openai_base_url: str = 'https://api.openai.com/v1'
    openai_model: str = 'gpt-5.4'
    qa_models: str = 'gpt-5.4'
    ollama_base_url: str = 'http://127.0.0.1:11434'
    ollama_model: str = 'llama3.1:8b'
    llm_timeout_s: float = 120
    figma_access_token: str = ''
    @property
    def llm_model(self): return self.ollama_model if self.llm_provider == 'ollama' else self.openai_model
    @property
    def models(self): return list(dict.fromkeys([self.llm_model] + [x.strip() for x in self.qa_models.split(',') if x.strip()]))
@lru_cache
def get_settings(): return Settings()
