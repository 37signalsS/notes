# Интеграция Wazuh с Telegram

## Определения

**Интеграция с Telegram** — механизм оперативного оповещения администраторов безопасности о критических событиях в инфраструктуре через мессенджер Telegram. В версии **Wazuh 5.0+** интеграция базируется на модуле **Wazuh-Engine** и демоне `wazuh-integratord`, обеспечивающем передачу данных внешним обработчикам.

**`custom-telegram`** — пользовательский скрипт-интеграция, выполняющий парсинг JSON-алерта, его форматирование и доставку в Telegram Bot API. С 2026 года стандартом является использование встроенного Python-окружения Wazuh для минимизации зависимостей в системе.

## Основные концепции

### Архитектура модуля интеграции (Wazuh 5.x)

С выходом Wazuh 5.0 процесс обработки внешних уведомлений претерпел ряд улучшений производительности и безопасности:

1.  **Многопоточность (Parallel Execution)**: Демон `wazuh-integratord` теперь поддерживает параллельный запуск нескольких экземпляров скрипта, что предотвращает задержки при «шторме» алертов.
2.  **Изолированное окружение**: Скрипты выполняются с использованием `/var/wazuh-manager/framework/python/bin/python3`, что гарантирует наличие необходимых библиотек (requests, json) без установки в основную ОС.
3.  **Нормализация путей**: Все компоненты интеграции перенесены в директорию `/var/wazuh-manager/integrations/`.
4.  **Расширенные опции**: Тег `<options>` в конфигурации позволяет передавать в скрипт произвольные параметры (например, приоритет или идентификатор проекта) без изменения исходного кода.

### Параметры настройки в ossec.conf

| Параметр | Описание | Рекомендация 2026 |
| :--- | :--- | :--- |
| **`<level>`** | Порог срабатывания интеграции. | 12+ для критических инцидентов. |
| **`<hook_url>`** | URL эндпоинта Bot API. | `https://api.telegram.org/botTOKEN/sendMessage` |
| **`<api_key>`** | Ключ или Chat ID. | Используйте для хранения ID целевого чата. |
| **`<max_workers>`** | Количество потоков обработки. | 2–5 для высоконагруженных менеджеров. |

## Практические сценарии

### 1. Конфигурация Wazuh Manager

Добавьте блок интеграции в `/var/wazuh-manager/etc/ossec.conf`. В 2026 году рекомендуется использовать тег `<options>` для гибкого управления метаданными.

```xml
<ossec_config>
  <integration>
    <name>custom-telegram</name>
    <level>12</level>
    <hook_url>https://api.telegram.org/bot<YOUR_BOT_TOKEN>/sendMessage</hook_url>
    <api_key><YOUR_CHAT_ID></api_key>
    <alert_format>json</alert_format>
    <options>{"environment": "production", "org": "SOC-TEAM-01"}</options>
  </integration>
</ossec_config>
```

### 2. Реализация Python-скрипта (Wazuh 5.0 Style)

Создайте файл `/var/wazuh-manager/integrations/custom-telegram`. Обратите внимание на использование встроенного интерпретатора в Shebang.

```python
#!/var/wazuh-manager/framework/python/bin/python3
import sys
import json
import requests
from datetime import datetime

# 1. Получение аргументов от wazuh-integratord
# [1] Путь к JSON-файлу алерта, [2] API Key (Chat ID), [3] Hook URL
alert_file_path = sys.argv[1]
chat_id = sys.argv[2]
hook_url = sys.argv[3]

# 2. Чтение и парсинг алерта
try:
    with open(alert_file_path, 'r') as f:
        alert_json = json.load(f)
except Exception as e:
    sys.exit(1)

# 3. Извлечение данных (формат Wazuh 5.x)
rule_id = alert_json.get('rule', {}).get('id', 'N/A')
level = alert_json.get('rule', {}).get('level', 0)
description = alert_json.get('rule', {}).get('description', 'Unknown')
agent_name = alert_json.get('agent', {}).get('name', 'Manager')
src_ip = alert_json.get('data', {}).get('srcip', 'N/A')

# 4. Формирование сообщения (Markdown)
message = (
    f"*Wazuh Alert (Level {level})*\n\n"
    f"*Rule:* {rule_id} - {description}\n"
    f"*Agent:* {agent_name}\n"
    f"*Source IP:* `{src_ip}`\n"
    f"*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)

# 5. Отправка в Telegram с обработкой ошибок
payload = {
    "chat_id": chat_id,
    "text": message,
    "parse_mode": "Markdown"
}

try:
    response = requests.post(hook_url, json=payload, timeout=10)
    response.raise_for_status()
except Exception as e:
    # Запись ошибок в специализированный лог Wazuh
    with open('/var/wazuh-manager/logs/integrations.log', 'a') as log:
        log.write(f"{datetime.now()} [Error] custom-telegram: {str(e)}\n")
    sys.exit(1)

sys.exit(0)
```

### 3. Установка прав и запуск

Для корректной работы демона `integratord` необходимо строго соблюдать владельца и права доступа:

```bash
# Установка владельца (Wazuh 5.0 использует пользователя wazuh)
chown root:wazuh /var/wazuh-manager/integrations/custom-telegram

# Права на чтение и выполнение для группы wazuh
chmod 750 /var/wazuh-manager/integrations/custom-telegram

# Проверка конфигурации и перезапуск
/var/wazuh-manager/bin/wazuh-engine-check -t
systemctl restart wazuh-manager
```

## Дополнительная информация

### Обработка Rate Limit
Telegram Bot API ограничивает отправку до 30 сообщений в секунду. В высоконагруженных средах рекомендуется:
- Повышать `<level>` до 13–14.
- Группировать алерты на стороне Wazuh через правила корреляции (см. [wazuh-rules.md](./wazuh-rules.md)).
- Проверять `/var/wazuh-manager/logs/integrations.log` на наличие ошибок `429 Too Many Requests`.

### Логирование и отладка
Если сообщения не приходят:
1.  Проверьте статус демона: `ps aux | grep integratord`.
2.  Изучите лог интеграций: `tail -n 50 /var/wazuh-manager/logs/integrations.log`.
3.  Запустите скрипт вручную для теста (подменив аргументы), используя `sudo -u wazuh`.

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Правила корреляции в Wazuh](./wazuh-rules.md) — оптимизация потока уведомлений.
- [Интеграция Wazuh и Zabbix](./zabbix-integration.md) — мониторинг через корпоративный стек.
