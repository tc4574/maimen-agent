"""DeepSeek text/tool API. No credentials or raw provider error bodies leave this module."""
import json
import httpx
from .settings import model_config


class ModelError(ValueError):
    pass


class DeepSeek:
    async def complete(self, messages, tools):
        config = model_config()
        if not config['key']:
            raise ModelError('model_not_configured')
        if config['base_url'] not in {'https://api.deepseek.com', 'https://api.deepseek.com/v1'}:
            raise ModelError('invalid_model_endpoint')
        body = {'model': config['model'], 'messages': messages, 'stream': False,
                'max_tokens': 1800, 'thinking': {'type': 'disabled'}}
        if tools:
            body['tools'] = tools
        try:
            async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
                async with client.stream('POST', config['base_url'] + '/chat/completions',
                                         headers={'Authorization': 'Bearer ' + config['key']}, json=body) as response:
                    if response.status_code != 200:
                        code = {401:'model_auth_failed', 402:'model_insufficient_balance',
                                429:'model_rate_limited'}.get(response.status_code, 'model_provider_failed')
                        raise ModelError(code)
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 256000:
                            raise ModelError('model_response_too_large')
            result = json.loads(chunks)
            choice = result['choices'][0]
            if choice.get('finish_reason') not in {'stop', 'tool_calls'}:
                raise ModelError('model_incomplete_response')
            message = choice['message']
            return {key: message[key] for key in ('role', 'content', 'tool_calls') if key in message}
        except ModelError:
            raise
        except httpx.TimeoutException:
            raise ModelError('model_timeout') from None
        except Exception:
            raise ModelError('model_provider_failed') from None
