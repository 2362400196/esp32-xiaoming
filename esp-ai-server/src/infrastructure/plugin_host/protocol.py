"""子进程插件沙箱 RPC 协议（JSON-lines over stdin/stdout）。

消息约定：
    主进程 → 子进程（stdin，每行一个 JSON 对象）：
        {"type": "call",      "id": int, "tool": str, "args": dict}
        {"type": "sdk_reply", "id": int, "result": dict, "error": str|null}
        {"type": "ping",      "id": int}

    子进程 → 主进程（stdout，每行一个 JSON 对象）：
        {"type": "ready",       "plugin": str, "tools": [ToolSchema]}
        {"type": "result",      "id": int, "result": dict}      # call 的回复
        {"type": "sdk_request", "id": int, "call": int|null, "op": str, "params": dict}
        {"type": "pong",        "id": int}

    ToolSchema = {"name": str, "description": str, "schema": dict, "cache": bool,
                  "signature": [{"name": str, "kind": str, "default": bool}]}

    call 回复 result 结构：
        {"ok": true, "value": str|null, "stop": bool, "error": null}
        {"ok": false, "error": str}          # 工具抛异常（含 StackTrace）

    sdk_reply 结构：
        {"ok": true, "result": any}          # result 需 JSON 可序列化
        {"ok": false, "error": str}          # 权限拒绝/内部错误（SDK 侧抛异常）

安全：
    - 单条消息最大 MAX_MSG_BYTES 字节，防止内存炸弹。
    - 每条消息都是完整 JSON 行，行内不能有换行。

SDK 操作类型（sdk_request.op）注册表：
    op 名由 sdk_shim 桩函数发出、adjudicator._op_<op> 处理，权限见 adjudicator._OP_PERMS。

    设备标识 / 配置（无权限）：
        device_key            {}                                            -> str
        resolve_device_key    {device_key}                                  -> str
        plugin_config         {plugin, key, env_var, default}               -> str
        skill_catalog         {}                                            -> str
        plugin_log            {level, message}                              -> None

    设备指令 / 状态（device）：
        device_send_instruct      {command_id, data}                        -> None
        device_send_command       {command_id, data}                        -> str|None
        device_send_command_ack   {command_id, data, timeout}               -> [result, status, detail]
        device_request_result     {command_id, future_attr, timeout, data, if_busy}
                                                                            -> [result, status, detail]
        device_is_online          {device_key}                              -> bool
        device_get_info           {device_key}                              -> dict

    设备 IO（device）——参数对照 src/use_cases/sdk/io.py：
        gpio_mode     {pin, mode, device_key}        写操作  -> str  ("ok"/错误串)
        gpio_write    {pin, value, device_key}       写操作  -> str  ("ok"/错误串)
        gpio_read     {pin, device_key}              读操作  -> int  (0/1，失败 -1)
        pwm_write     {pin, duty, freq, device_key}  写操作  -> str  ("ok"/错误串)
        adc_read      {pin, device_key}              读操作  -> int  (0-4095，失败 -1)
        servo_write   {pin, angle, device_key}       写操作  -> str  ("ok"/错误串)

    音乐播放（device）——参数对照 src/use_cases/sdk/music.py：
        play_music_url    {url, title, artist, duration, device_key,
                           lyric_url, lyrics_offset}                    -> str  ("ok"/错误串)

    HTTP（network）：
        http_request      {method, url, params, headers, content, timeout} -> [status, body, err]
        http_get_json     {url, params, headers, timeout}                  -> [data, err]
        http_stream_open  {method, url, headers, content, timeout}         -> [stream_id, err]
        http_stream_read  {stream_id, timeout}                             -> [line, err]
        http_stream_close {stream_id}                                      -> None

    计费上报（billing）——参数对照 src/use_cases/sdk/billing.py：
        billing_add_asr   {minutes}                                        -> None
        billing_add_llm   {input_tokens, output_tokens, cache_hit_tokens}  -> None
        billing_add_tts   {chars}                                          -> None
    （ltm_* / diary_* / device_config_* / env_read / llm_* / tts_synthesize /
      plugin_data_* / kv_* / get_user_profile_summary / ws_* 等其余 op 详见 adjudicator._OP_PERMS）
"""

from __future__ import annotations

import json

MAX_MSG_BYTES = 1024 * 1024  # 单条消息上限 1MB


class ProtocolError(Exception):
    """协议层错误（消息过大/JSON 损坏/字段缺失）。"""


def encode(msg: dict) -> str:
    """将消息编码为单行 JSON 字符串（供写入管道）。"""
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    if len(raw.encode("utf-8")) > MAX_MSG_BYTES:
        raise ProtocolError(f"消息过大（>{MAX_MSG_BYTES} 字节），已拒绝发送")
    return raw + "\n"


def _json_default(o):
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace")
    return repr(o)


def decode(line: str) -> dict:
    """解析一行消息。行过长/损坏时抛 ProtocolError。"""
    if len(line.encode("utf-8")) > MAX_MSG_BYTES:
        raise ProtocolError(f"消息过大（>{MAX_MSG_BYTES} 字节），已拒绝接收")
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProtocolError(f"消息不是合法 JSON: {e}") from e
    if not isinstance(msg, dict):
        raise ProtocolError("消息必须是 JSON 对象")
    return msg