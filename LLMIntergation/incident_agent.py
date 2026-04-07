import asyncio
import json
from ollama import AsyncClient
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

MCP_SERVER_URL = "http://192.168.1.102:8000/sse"
MODEL_NAME = "qwen2.5-coder"

SYSTEM_PROMPT = """
Ты — автономный AI-агент, старший аналитик кибербезопасности. Твоя задача — анализировать логи серверов через базу VictoriaLogs.КРИТИЧЕСКИЕ ПРАВИЛА ПОВЕДЕНИЯ:1. Вызывай инструменты НАПРЯМУЮ. НИКОГДА не пиши сырой JSON-код вызова в чат! Если тебе нужно вызвать инструмент, просто сделай это молча.2. ШПАРГАЛКА ПО СИНТАКСИСУ VICTORIALOGS (LogsQL):   - VictoriaLogs использует простой текстовый поиск.   - НЕ используй пайпы (|), функции (stats by) или SQL-синтаксис.   - ПРАВИЛЬНЫЙ пример запроса для поиска 404: "404" или "status:404"   - ПРАВИЛЬНЫЙ пример поиска админки: "wp-admin" или ".env"Проанализируй логи и дай развернутый ответ пользователю на русском языке.
"""

async def chat_loop():
    print(f"🔌 Подключение к MCP серверу: {MCP_SERVER_URL}...")
    
    try:
        async with sse_client(MCP_SERVER_URL, timeout=None) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("✅ Соединение установлено!\n")
                
                mcp_tools = await session.list_tools()
                ollama_tools = [
                    {
                        'type': 'function',
                        'function': {
                            'name': t.name,
                            'description': t.description,
                            'parameters': t.inputSchema,
                        },
                    } for t in mcp_tools.tools
                ]

                messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
                client = AsyncClient()

                while True:
                    user_input = input("\n👤 Вы: ")
                    if user_input.lower() in ['exit', 'quit', 'выход']:
                        break
                    if not user_input.strip(): continue

                    messages.append({'role': 'user', 'content': user_input})
                    print("⏳ Qwen думает...")
                    
                    response = await client.chat(
                        model=MODEL_NAME,
                        messages=messages,
                        tools=ollama_tools,
                    )

                    assistant_msg = response['message']
                    messages.append(assistant_msg)

                    tool_calls_to_execute = []
                    
                    if assistant_msg.get('tool_calls'):
                        tool_calls_to_execute = assistant_msg['tool_calls']
                    
                    elif assistant_msg.get('content'):
                        content_text = assistant_msg['content'].strip()
                        clean_text = content_text.replace('```json', '').replace('```', '').strip()
                        
                        if clean_text.startswith('{') and clean_text.endswith('}'):
                            try:
                                parsed = json.loads(clean_text)
                                if 'name' in parsed and 'arguments' in parsed:
                                    print("   [!] Перехвачен сырой JSON. Превращаем в команду...")
                                    tool_calls_to_execute.append({
                                        'function': {
                                            'name': parsed['name'],
                                            'arguments': parsed['arguments']
                                        }
                                    })
                            except json.JSONDecodeError:
                                pass
                    if tool_calls_to_execute:
                        for tool_call in tool_calls_to_execute:
                            tool_name = tool_call['function']['name']
                            tool_args = tool_call['function']['arguments']
                            
                            print(f"   🛠 Отправляю запрос: {tool_args}")
                            
                            try:
                                tool_result = await session.call_tool(tool_name, tool_args)
                                result_text = "\n".join([item.text for item in tool_result.content if item.type == 'text'])
                                
                                if not result_text.strip():
                                    print("   📥 База вернула ПУСТОЙ ответ (0 записей)!")
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
                                print(f"   ❌ Ошибка базы: {e}")
                                messages.append({'role': 'tool', 'content': f"Error: {e}", 'name': tool_name})

                        print("⏳ Qwen анализирует результаты...")
                        final_response = await client.chat(model=MODEL_NAME, messages=messages)
                        final_msg = final_response['message']
                        messages.append(final_msg)
                        print(f"\n🤖 Qwen:\n{final_msg['content']}")
                        
                    else:
                        print(f"\n🤖 Qwen:\n{assistant_msg.get('content', '')}")

    except Exception as e:
        print(f"\n❌ Ошибка: {e}")

if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(chat_loop())