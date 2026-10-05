"""Streaming model decisions for the embedded training assistant.

Only narrative JSON fields are published to the UI. Tool arguments are validated
as a complete object before the controller can execute any side effect.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from kohya_core.captioning import CaptionError, CaptionServiceError, _NoRedirect, _post

_EVENT_LIMIT = 512 * 1024
_WIRE_LIMIT = 8 * 1024 * 1024


def _json_text(text):
    text = text.strip()
    if text.startswith('<think>'):
        if '</think>' not in text:
            return ''
        text = text.split('</think>', 1)[1].strip()
    if text.startswith('```'):
        if '\n' not in text:
            return ''
        text = text.split('\n', 1)[1]
        if text.rstrip().endswith('```'):
            text = text.rstrip()[:-3]
    return text.strip()


def _partial_string(text, start):
    """Decode a JSON string prefix without publishing escapes or incomplete UTF-16."""
    result = []
    index = start
    escapes = {'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'f': '\f', '"': '"', '/': '/', '\\': '\\'}
    while index < len(text):
        char = text[index]
        if char == '"':
            break
        if char == '\\':
            index += 1
            if index >= len(text):
                break
            char = text[index]
            if char == 'u':
                if index + 4 >= len(text):
                    break
                try:
                    point = int(text[index + 1:index + 5], 16)
                except ValueError:
                    break
                index += 4
                if 0xD800 <= point <= 0xDBFF:
                    if text[index + 1:index + 3] != '\\u' or index + 6 >= len(text):
                        break
                    try:
                        low = int(text[index + 3:index + 7], 16)
                    except ValueError:
                        break
                    if not 0xDC00 <= low <= 0xDFFF:
                        break
                    point = 0x10000 + ((point - 0xD800) << 10) + low - 0xDC00
                    index += 6
                if 0xDC00 <= point <= 0xDFFF:
                    break
                result.append(chr(point))
            elif char in escapes:
                result.append(escapes[char])
            else:
                break
        else:
            if ord(char) < 32:
                break
            result.append(char)
        index += 1
    return ''.join(result)[:6000]


def _visible_text(raw):
    text = _json_text(raw)
    if not text.startswith('{'):
        return ''
    decoder = json.JSONDecoder()
    index = 1
    while index < len(text):
        while index < len(text) and text[index] in ' \r\n\t,':
            index += 1
        try:
            key, end = decoder.raw_decode(text, index)
        except ValueError:
            return ''
        if not isinstance(key, str):
            return ''
        index = end
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] != ':':
            return ''
        index += 1
        while index < len(text) and text[index].isspace():
            index += 1
        if key in ('message', 'question', 'answer') and index < len(text) and text[index] == '"':
            return _partial_string(text, index + 1)
        try:
            _, index = decoder.raw_decode(text, index)
        except ValueError:
            return ''
    return ''


def _stream(config, messages, stop, on_text):
    ollama = config['provider'] == 'ollama'
    payload = {'model': config['model'], 'messages': messages, 'stream': True}
    if ollama:
        payload.update(format='json', keep_alive='5m', options={'temperature': .1, 'num_predict': 3000, 'num_ctx': 16384})
        url = config['base_url'] + '/api/chat'
    else:
        payload.update(temperature=.1, max_tokens=3000)
        url = config['base_url'] + '/chat/completions'
    events = queue.Queue(maxsize=256)
    abandoned = threading.Event()
    handles = {}

    def publish(value):
        if value[0] == 'chunk' and not value[1] and not value[2]:
            return  # Reasoning-only deltas and heartbeats are not executable output.
        while not abandoned.is_set():
            try:
                events.put(value, timeout=.1)
                return
            except queue.Full:
                continue

    def request():
        try:
            headers = {'Content-Type': 'application/json', 'Accept': 'application/x-ndjson' if ollama else 'text/event-stream'}
            if not ollama and config.get('api_key'):
                headers['Authorization'] = 'Bearer ' + config['api_key']
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}) if urlsplit(url).hostname in ('localhost', '127.0.0.1', '::1') else urllib.request.ProxyHandler(),
                _NoRedirect())
            req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers)
            with opener.open(req, timeout=30) as response:
                handles['response'] = response
                if abandoned.is_set():
                    return
                total = 0
                media = response.headers.get('Content-Type', '').lower()
                if not ollama and 'application/json' in media:
                    raw = response.read(_WIRE_LIMIT + 1)
                    if len(raw) > _WIRE_LIMIT:
                        raise CaptionServiceError('文字服务响应超过 8MiB 协议上限；请降低模型思考长度或更换文字模型。已完成操作保留。')
                    value = json.loads(raw)
                    choice = value['choices'][0]
                    publish(('chunk', choice['message'].get('content', ''), choice.get('finish_reason')))
                    publish(('done', None, None))
                    return
                pending = []

                def emit_sse():
                    if not pending:
                        return False
                    data = '\n'.join(pending)
                    pending.clear()
                    if data == '[DONE]':
                        return True
                    value = json.loads(data)
                    if value.get('error'):
                        raise CaptionServiceError('文字服务返回错误，请检查模型和服务额度。')
                    choices = value.get('choices') or []
                    if choices:
                        choice = choices[0]
                        publish(('chunk', (choice.get('delta') or {}).get('content', ''), choice.get('finish_reason')))
                    return False

                while not abandoned.is_set():
                    line = response.readline(_EVENT_LIMIT + 1)
                    if not line:
                        if not ollama:
                            emit_sse()
                        break
                    if len(line) > _EVENT_LIMIT:
                        raise CaptionServiceError('文字服务单条流事件过大，请检查服务的流式接口。已完成操作保留。')
                    total += len(line)
                    if total > _WIRE_LIMIT:
                        raise CaptionServiceError('文字服务响应超过 8MiB 协议上限；请降低模型思考长度或更换文字模型。已完成操作保留。')
                    text = line.decode('utf-8').rstrip('\r\n')
                    if ollama:
                        if not text.strip():
                            continue
                        value = json.loads(text)
                        if value.get('error'):
                            raise CaptionServiceError('Ollama 返回错误，请检查本地模型和服务状态。')
                        publish(('chunk', (value.get('message') or {}).get('content', ''), value.get('done_reason')))
                        if value.get('done'):
                            break
                    elif text.startswith('data:'):
                        pending.append(text[5:].lstrip(' '))
                    elif not text and emit_sse():
                        break
                publish(('done', None, None))
        except urllib.error.HTTPError as exc:
            publish(('error', CaptionServiceError('文字服务返回 HTTP %d；请检查地址、模型、密钥或额度。' % exc.code), None))
        except CaptionError as exc:
            publish(('error', exc, None))
        except Exception as exc:
            publish(('error', CaptionServiceError('助手连接未完成（%s）；请检查文字服务。' % type(exc).__name__), None))

    stop()
    threading.Thread(target=request, daemon=True, name='agent-stream').start()
    deadline = time.monotonic() + 180
    text = ''
    last_visible = ''
    finish = None
    try:
        while True:
            stop()
            if time.monotonic() > deadline:
                raise CaptionServiceError('助手回复超时；可暂停后继续，已完成的操作会保留。')
            try:
                kind, value, reason = events.get(timeout=.1)
            except queue.Empty:
                continue
            if kind == 'error':
                raise value
            if kind == 'done':
                break
            if reason:
                finish = reason
            if isinstance(value, str):
                text += value
            if len(text) > 30000:
                raise CaptionServiceError('文字模型输出超过本次回复上限，当前步骤未执行；已完成操作保留。请要求模型简短回复或调整文字服务。')
            visible = _visible_text(text)
            if on_text and visible != last_visible:
                stop()
                on_text(visible)
                last_visible = visible
        stop()
        if finish == 'content_filter':
            raise CaptionServiceError('文字服务中止了本次回复，当前步骤未执行；已完成操作保留。')
        if finish == 'length':
            raise ValueError('reply_truncated')
        return text
    finally:
        abandoned.set()
        # Closing from a daemon avoids blocking the UI if another thread is in socket read.
        response = handles.get('response')
        if response:
            threading.Thread(target=response.close, daemon=True, name='agent-stream-close').start()


def request_action(config, messages, stop, on_text=None):
    """Retry malformed structured replies once; no operation runs before validation."""
    from kohya_core.training_agent import CATALOG
    allowed = {item['name'] for item in CATALOG}
    current = list(messages)
    for attempt in range(2):
        try:
            raw = _stream(config, current, stop, on_text)
            value = json.loads(_json_text(raw))
            if not isinstance(value, dict) or value.get('type') not in ('tool', 'ask', 'finish', 'say'):
                raise ValueError('type')
            if value['type'] == 'tool':
                if value.get('name') not in allowed or not isinstance(value.get('arguments', {}), dict):
                    raise ValueError('tool')
            else:
                field = 'question' if value['type'] == 'ask' else 'answer' if value['type'] == 'finish' else 'message'
                if not isinstance(value.get(field), str) or not value[field].strip():
                    raise ValueError('content')
                value[field] = value[field][:6000]
            if 'message' in value and not isinstance(value['message'], str):
                raise ValueError('message')
            if value.get('path_kind') not in (None, '', 'folder', 'model'):
                raise ValueError('path_kind')
            if value['type'] == 'ask':
                choices = value.get('choices', [])
                if not isinstance(choices, list) or any(not isinstance(item, str) for item in choices):
                    raise ValueError('choices')
                value['choices'] = list(dict.fromkeys(item.strip()[:200] for item in choices if item.strip()))[:6]
            return value
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            if attempt and str(exc) == 'reply_truncated':
                raise CaptionError('文字模型连续两次达到回复长度上限，当前步骤未执行；已完成操作保留。请让模型简短回复或调整文字服务的输出与思考设置。') from exc
            if attempt:
                raise CaptionError('模型连续两次未返回可执行的回复。对话与已完成步骤已保留，可修改连接设置后继续。')
            if on_text:
                on_text('')
            current.append({'role': 'user', 'content': '上一个回复格式不正确，未执行任何操作。请纠正为一个完整 JSON 对象，type 为 tool、ask、say 或 finish；只在 message/question/answer 写给用户看的简短说明。工具名必须来自目录，不要输出推理过程或代码围栏。'})
    raise CaptionError('助手回复未完成。')


def release_model(config, stop=lambda: None):
    """Free Ollama's selected model before GPU tasks, not after every chat decision."""
    if config.get('provider') != 'ollama':
        return {'ok': False, 'supported': False, 'error': '兼容接口不提供统一的模型卸载功能；本地服务需手动释放模型显存。'}
    try:
        _post(config['base_url'] + '/api/generate', {'model': config['model'], 'keep_alive': 0, 'stream': False}, '', stop, timeout=8)
        return {'ok': True, 'supported': True}
    except CaptionError:
        return {'ok': False, 'supported': True, 'error': '本地文字模型卸载未确认，请检查显存后再训练。'}
