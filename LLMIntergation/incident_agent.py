import json
import re
import sys
import asyncio
from ollama import AsyncClient
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

# Настройки
MODEL_NAME = "qwen2.5-coder:14b" 
MCP_SERVER_URL = "http://192.168.1.101:8000/sse" 

SYSTEM_PROMPT = """Ты — высококвалифицированный DevOps и SRE-инженер. Твоя главная задача — помогать расследовать инциденты.
У тебя есть доступ к реальной базе логов.

❗️ КАК ИСКАТЬ ЛОГИ ❗️
Чтобы сделать запрос в базу, ты ОБЯЗАН ответить ТОЛЬКО строгим JSON-объектом в таком формате:
{
  "name": "query",
  "arguments": {
    "service": "backend",
    "time_range": "15m",
    "search_text": "ConnectionRefused"
  }
}

ТВОИ СТРОГИЕ ПРАВИЛА:
1. НИКАКИХ BASH-КОМАНД. Никогда не пиши команды вида search_logs .... Вызывай инструмент ТОЛЬКО через JSON.
2. НИКАКИХ ФАНТАЗИЙ. Если просят найти ошибку, не пытайся угадать причину. СНАЧАЛА верни JSON, чтобы получить логи.
3. Допустимые параметры: time_range (обязательно, например "15m", "1h"), service (опционально), search_text (опционально), level (опционально, например "ERROR").
4. Когда ты получишь реальные логи из базы (в следующем системном сообщении), внимательно изучи их и напиши подробный Root Cause Analysis (причину сбоя).
"""

async def chat_loop(client, session):
    print("\n💡 Оркестратор запущен. Напиши 'exit' для выхода.")
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]

    while True:
        try:
            user_query = input("\n👤 Ты: ")
            if user_query.strip().lower() in ['exit', 'quit']:
                break
            if not user_query.strip():
                continue

            messages.append({'role': 'user', 'content': user_query})
            
            print("⏳ Qwen думает...")
            response = await client.chat(model=MODEL_NAME, messages=messages)
            assistant_msg = response['message']
            messages.append(assistant_msg)

            tool_calls_to_execute = []

            if assistant_msg.get('tool_calls'):
                tool_calls_to_execute = assistant_msg['tool_calls']
                
            elif assistant_msg.get('content'):
                content_text = assistant_msg['content'].strip()
                
                json_pattern = r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\}'
                matches = list(re.finditer(json_pattern, content_text, re.DOTALL))
                
                clean_text = content_text
                for match in matches:
                    json_str = match.group(0)
                    try:
                        parsed = json.loads(json_str)
                        if 'name' in parsed and 'arguments' in parsed:
                            print(f"   [!] Перехвачен JSON-вызов ({parsed['name']})...")
                            tool_calls_to_execute.append({
                                'function': {
                                    'name': parsed['name'],
                                    'arguments': parsed['arguments']
                                }
                            })
                            clean_text = clean_text.replace(json_str, '').strip()
                    except json.JSONDecodeError:
                        pass
                
                final_print = clean_text.replace('```json', '').replace('```', '').strip()
                
                if final_print and not tool_calls_to_execute:
                    print(f"\n🤖 Qwen:\n{final_print}")
                elif final_print and tool_calls_to_execute:
                    print(f"\n🧠 Ход мыслей Qwen:\n{final_print}")
            if tool_calls_to_execute:
                for tool_call in tool_calls_to_execute:
                    func_data = tool_call.get('function', tool_call)
                    tool_name = func_data.get('name')
                    tool_args = func_data.get('arguments', {})
                    
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError:
                            print("   ❌ Ошибка: аргументы не являются валидным JSON.")
                            continue

                    print(f"   🛠 Отправляю запрос к {tool_name}: {tool_args}")
                    
                    try:
                        tool_result = await session.call_tool(tool_name, arguments=tool_args)
                        
                        if hasattr(tool_result, 'content'):
                            result_text = "\n".join([item.text for item in tool_result.content if getattr(item, 'type', '') == 'text' or hasattr(item, 'text')])
                        else:
                            result_text = str(tool_result)
                        
                        if not result_text.strip():
                            print("   📥 База вернула ПУСТОЙ ответ (0 записей)!")
                            result_text = "No logs found for this query."
                        else:
                            if len(result_text) < 200:
                                print(f"   📥 Ответ базы: {result_text}")
                            else:
                                print(f"   📥 База нашла логи! (Длина: {len(result_text)} симв.)")
                            
                            MAX_CHARS = 3000
                            if len(result_text) > MAX_CHARS:
                                print(f"   ✂️ Логи слишком большие! Обрезаем до {MAX_CHARS} символов...")
                                result_text = result_text[:MAX_CHARS] + "\n...[ОСТАЛЬНЫЕ ЛОГИ ОБРЕЗАНЫ ДЛЯ ЭКОНОМИИ ПАМЯТИ]..."
                        
                        messages.append({'role': 'tool', 'content': result_text, 'name': tool_name})
                        
                    except Exception as e:
                        print(f"   ❌ Ошибка базы MCP: {e}")
                        messages.append({'role': 'tool', 'content': f"Error: {e}", 'name': tool_name})

                print("⏳ Qwen анализирует результаты...")
                final_response = await client.chat(model=MODEL_NAME, messages=messages)
                final_msg = final_response['message']
                messages.append(final_msg)
                print(f"\n🤖 Qwen:\n{final_msg.get('content', '')}")

        except Exception as e:
            print(f"\n❌ Глобальная ошибка в цикле: {e}")

async def main():
    print(f"🔌 Подключение к MCP серверу по адресу {MCP_SERVER_URL}...")
    
    # Инициализация клиента Ollama
    client = AsyncClient()
    
    # Подключение к MCP серверу по протоколу SSE
    try:
        # Устанавливаем timeout=None для бесконечного ожидания ответа
        async with sse_client(MCP_SERVER_URL, timeout=None) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                print("✅ Успешно подключено к MCP и Ollama!")
                
                # Запускаем основной цикл общения, передавая готовые соединения
                await chat_loop(client, session)
                
    except Exception as e:
        print(f"\n❌ Критическая ошибка при подключении к серверу MCP: {e}")
        print("Убедись, что Docker-контейнер запущен на сервере и порт открыт.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Скрипт остановлен пользователем.")