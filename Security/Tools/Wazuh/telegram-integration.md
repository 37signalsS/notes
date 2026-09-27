# Интеграция Wazuh с Telegram

## Определения

**Интеграция с Telegram** — механизм оперативного оповещения администраторов безопасности о критических событиях в инфраструктуре через мессенджер Telegram. В версии **Wazuh 5.0+** интеграция базируется на модуле **Wazuh-Engine** и демоне `wazuh-integratord`, обеспечивающем передачу данных внешним обработчикам.

**`custom-telegram`** — пользовательский скрипт-интеграция, выполняющий парсинг JSON-алерта, его форматирование и доставку в Telegram Bot API. С 2026 года стандартом является использование встроенного Python-окружения Wazuh для минимизации зависимостей в системе.

**`wazuh-integratord`** — фоновый процесс (демон) менеджера Wazuh, отвечающий за выполнение внешних скриптов интеграции при срабатывании правил определенного уровня или группы. В Wazuh 5.0+ работает в многопоточном режиме с нормализованными путями `/var/wazuh-manager/integrations/`.

**Telegram Bot API** — HTTP-интерфейс Telegram для управления ботом (отправка сообщений, получение обновлений). Основной метод для интеграции — `sendMessage` на эндпоинте `https://api.telegram.org/bot<TOKEN>/sendMessage`.

**Chat ID** — уникальный идентификатор целевого чата, группы или канала в Telegram. Для личных чатов — положительное число, для групп — отрицательное (начинается с `-100`).

**Alert Format (JSON)** — формат обмена данными между Wazuh и скриптом интеграции. Алерт передается как JSON-файл через аргумент командной строки, что позволяет скрипту оставаться идемпотентным и отлаживаемым.

**Rate Limit (Telegram)** — ограничение Telegram Bot API на отправку до 30 сообщений в секунду для одного бота. При превышении возвращается ошибка `429 Too Many Requests` с полем `retry_after`.

**Webhook vs Polling** — в контексте Telegram существуют две модели получения обновлений. Для интеграции с Wazuh используется ** outgoing webhook** (скрипт сам вызывает Bot API), а не входящий webhook от Telegram, что упрощает архитектуру и исключает необходимость публичного IP.

## Основные концепции

### Архитектура потока алертов (Wazuh 5.x)

Поток данных от события до сообщения в Telegram:

```
Агент Wazuh
    │
    ▼
Менеджер (analysisd / Wazuh-Engine)
    │
    ▼
Правило сработало (rule level >= threshold)
    │
    ▼
wazuh-integratord (демон интеграций)
    │
    ▼
Скрипт /var/wazuh-manager/integrations/custom-telegram
    │  [аргументы: alert.json, CHAT_ID, HOOK_URL]
    ▼
Telegram Bot API (sendMessage)
    │
    ▼
Целевой чат / группа / канал
```

### Изменения в Wazuh 5.x для интеграций

С выходом Wazuh 5.0 процесс обработки внешних уведомлений претерпел изменения:

1.  **Многопоточность (Parallel Execution)**: Демон `wazuh-integratord` теперь поддерживает параллельный запуск нескольких экземпляров скрипта через пул воркеров (`max_workers`), что предотвращает задержки при «шторме» алертов.
2.  **Изолированное окружение**: Скрипты выполняются с использованием `/var/wazuh-manager/framework/python/bin/python3`, что гарантирует наличие необходимых библиотек (`requests`, `json`) без установки в основную ОС.
3.  **Нормализация путей**: Все компоненты интеграции перенесены в директорию `/var/wazuh-manager/integrations/`.
4.  **Расширенные опции**: Тег `<options>` в конфигурации позволяет передавать в скрипт произвольные параметры (например, приоритет или идентификатор проекта) без изменения исходного кода.

### Параметры настройки в ossec.conf

| Параметр | Описание | Рекомендация 2026 |
| :--- | :--- | :--- |
| **`<name>`** | Имя интеграции, определяющее скрипт в `/var/wazuh-manager/integrations/`. | `custom-telegram` |
| **`<level>`** | Порог срабатывания интеграции. | 12+ для критических инцидентов. |
| **`<hook_url>`** | URL эндпоинта Bot API. | `https://api.telegram.org/botTOKEN/sendMessage` |
| **`<api_key>`** | Chat ID целевого чата или группы. | Числовой ID, полученный через `@getidsbot` или `@userinfobot`. |
| **`<alert_format>`** | Формат передачи алерта скрипту. | `json` (рекомендуется) или `xml`. |
| **`<max_workers>`** | Количество потоков обработки в `integratord`. | 2–5 для высоконагруженных менеджеров. |
| **`<timeout>`** | Таймаут выполнения скрипта в секундах. | 10–30, зависит от задержки сети до Telegram. |
| **`<options>`** | JSON-строка с произвольными параметрами, передаваемыми в скрипт. | `{"environment": "production", "team": "soc"}` |

### Сравнение методов оповещения

| Критерий | Telegram | Email | Zabbix/Prometheus Alertmanager |
| :--- | :--- | :--- | :--- |
| **Скорость доставки** | < 2 сек | 10–60 сек | < 5 сек |
| **Надежность** | Зависит от доступности `api.telegram.org` | Высокая (SMTP resilient) | Высокая (если настроен HA) |
| **Форматирование** | Markdown/HTML | Ограниченное | Зависит от шаблонов |
| **Группировка** | Требует реализации в скрипте | Нет | Нативная (group_by, inhibit) |
| **История** | Ограничена в чате | В почтовом ящике | В базе мониторинга |
| **Рекомендация** | Для дежурных и быстрого реагирования | Для официальных отчетов | Для структурированных алертов |

## Практические сценарии

### Предварительные требования

- **Wazuh Manager** 4.9+ (рекомендуется 5.x).
- **Аккаунт Telegram** с созданным ботом через `@BotFather`.
- **Chat ID** целевого чата/группы/канала.
- Сеть: доступ из Wazuh Manager на `api.telegram.org:443`.
- Права: возможность создания и редактирования файлов в `/var/wazuh-manager/integrations/`.
- TLS: для production используйте проверенные сертификаты. Telegram API работает по HTTPS.

### 1. Конфигурация Wazuh Manager

Добавьте блок интеграции в `/var/wazuh-manager/etc/ossec.conf`. Рекомендуется использовать тег `<options>` для гибкого управления метаданными.

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

**Валидация конфигурации:**
```bash
# Проверка синтаксиса ossec.conf
/var/wazuh-manager/bin/wazuh-engine-check -t

# Проверка статуса integratord
ps aux | grep integratord

# Применение конфигурации
systemctl restart wazuh-manager
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

**Обработка 429 Too Many Requests (расширенная):**
```python
import time

def send_with_retry(payload, hook_url, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.post(hook_url, json=payload, timeout=10)
            if response.status_code == 429:
                retry_after = response.json().get('parameters', {}).get('retry_after', 5)
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return True
        except Exception as e:
            if attempt == max_retries - 1:
                with open('/var/wazuh-manager/logs/integrations.log', 'a') as log:
                    log.write(f"{datetime.now()} [Error] custom-telegram: {str(e)}\n")
                return False
    return False
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

**Валидация установки:**
```bash
# 1. Проверка статуса integratord
ps aux | grep integratord
# → root 12345 ... /var/wazuh-manager/bin/wazuh-integratord

# 2. Тестовый запуск скрипта вручную
echo '{"rule":{"level":12,"id":100001,"description":"Test alert"},"agent":{"name":"test-agent"},"data":{"srcip":"1.2.3.4"}}' > /tmp/test_alert.json
sudo -u wazuh /var/wazuh-manager/integrations/custom-telegram /tmp/test_alert.json "123456789" "https://api.telegram.org/botTOKEN/sendMessage"

# 3. Проверка логов
tail -n 50 /var/wazuh-manager/logs/integrations.log
```

### 4. Поддержка нескольких Chat ID и групп

Для отправки алертов в несколько чатов модифицируйте скрипт или `ossec.conf`:

**Вариант А: Несколько блоков `<integration>`**
```xml
<ossec_config>
  <integration>
    <name>custom-telegram</name>
    <level>12</level>
    <hook_url>https://api.telegram.org/botTOKEN/sendMessage</hook_url>
    <api_key>CHAT_ID_SOC</api_key>
    <alert_format>json</alert_format>
  </integration>
  <integration>
    <name>custom-telegram</name>
    <level>15</level>
    <hook_url>https://api.telegram.org/botTOKEN/sendMessage</hook_url>
    <api_key>CHAT_ID_CRITICAL</api_key>
    <alert_format>json</alert_format>
  </integration>
</ossec_config>
```

**Вариант Б: Рассылка из скрипта (массив в `<options>`)**
```xml
<options>{"chat_ids": ["-1001234567890", "123456789"], "environment": "production"}</options>
```

```python
import json

options_str = sys.argv[4] if len(sys.argv) > 4 else '{}'
options = json.loads(options_str)
chat_ids = options.get('chat_ids', [chat_id])

for cid in chat_ids:
    payload["chat_id"] = cid
    send_with_retry(payload, hook_url)
```

### 5. Развертывание через Ansible

Автоматизация развертывания скрипта и конфигурации:

```yaml
- name: Deploy Telegram integration script
  copy:
    src: files/custom-telegram
    dest: /var/wazuh-manager/integrations/custom-telegram
    owner: root
    group: wazuh
    mode: '0750'

- name: Configure Wazuh integration in ossec.conf
  xml:
    path: /var/wazuh-manager/etc/ossec.conf
    xpath: /ossec-config/integration[name='custom-telegram']
    pretty_print: yes
    content: "{{ lookup('template', 'integration.xml.j2') }}"
  notify: restart wazuh-manager

- name: Ensure Wazuh manager is running
  systemd:
    name: wazuh-manager
    state: started
    enabled: yes
```

### 6. CI/CD пайплайн для политик интеграции

```yaml
name: Wazuh Telegram Integration CI/CD

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate XML syntax
        run: python3 scripts/validate_ossec_conf.py Security/Tools/Wazuh/ossec.conf
      - name: Lint Python integration script
        run: flake8 Security/Tools/Wazuh/custom-telegram.py
      - name: Deploy to staging
        if: github.ref == 'refs/heads/main'
        run: ansible-playbook -i inventory/staging playbooks/deploy_telegram_integration.yml
```

### 7. Бэкап и восстановление конфигурации

```bash
# Бэкап
BACKUP_DIR="/var/backups/wazuh-telegram-$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/wazuh-telegram-integration.tar.gz" \
  /var/wazuh-manager/integrations/custom-telegram \
  /var/wazuh-manager/etc/ossec.conf

# Восстановление
tar -xzf /var/backups/wazuh-telegram-20250918.tar.gz -C /
chown root:wazuh /var/wazuh-manager/integrations/custom-telegram
chmod 750 /var/wazuh-manager/integrations/custom-telegram
/var/wazuh-manager/bin/wazuh-engine-check -t
systemctl restart wazuh-manager
```

### 8. Конфигурация через корпоративный прокси

Если Wazuh Manager находится в segmented network с выходом только через прокси:

```python
import os

proxies = {
    'http': os.getenv('HTTPS_PROXY', 'http://proxy.corp.local:8080'),
    'https': os.getenv('HTTPS_PROXY', 'http://proxy.corp.local:8080')
}

response = requests.post(hook_url, json=payload, timeout=10, proxies=proxies, verify='/etc/ssl/certs/ca-certificates.crt')
```

```xml
<ossec_config>
  <integration>
    <name>custom-telegram</name>
    <level>12</level>
    <hook_url>https://api.telegram.org/botTOKEN/sendMessage</hook_url>
    <api_key>CHAT_ID</api_key>
    <alert_format>json</alert_format>
    <options>{"proxy": "http://proxy.corp.local:8080", "ca_bundle": "/etc/ssl/certs/ca-certificates.crt"}</options>
  </integration>
</ossec_config>
```

## Дополнительная информация

### Оптимизация и безопасность

*   **Rate Limiting:** Telegram Bot API ограничивает отправку до 30 сообщений в секунду. В высоконагруженных средах рекомендуется:
    *   Повышать `<level>` до 13–14, отправляя только критичные алерты.
    *   Группировать алерты на стороне Wazuh через правила корреляции (см. [Правила корреляции в Wazuh](./wazuh-rules.md)).
    *   Реализовать батчинг в скрипте: отправлять одно сообщение с несколькими алертами через `\n\n---\n\n`.
    *   Проверять `/var/wazuh-manager/logs/integrations.log` на наличие ошибок `429 Too Many Requests`.
*   **Сетевые ACL:** Разместите Wazuh Manager и выход в Интернет в одной подсети. Настройте firewall для разрешения только `api.telegram.org:443`.
*   **Секреты:** Никогда не храните Bot Token в открытом виде в Git. Используйте переменные окружения, Ansible Vault или HashiCorp Vault. В `<hook_url>` допустимо указывать токен, так как `ossec.conf` защищен правами `root:wazuh`.
*   **Аудит:** Все попытки отправки фиксируются в `/var/wazuh-manager/logs/integrations.log`. Настройте ротацию через `logrotate` для предотвращения заполнения диска.
*   **Заглушка (silence):** Для плановых работ используйте временное повышение `<level>` до 16 (критический) и настройте в Telegram mute на 1–2 часа, или отключите интеграцию через `<disabled>yes</disabled>`.

### Телеметрия и мониторинг интеграции

```bash
# Проверка статуса демона integratord
ps aux | grep integratord
# → root 12345 ... /var/wazuh-manager/bin/wazuh-integratord

# Мониторинг логов интеграций в реальном времени
tail -f /var/wazuh-manager/logs/integrations.log

# Проверка очереди integratord
/var/wazuh-manager/bin/wazuh-integratord -t

# Проверка отправки: тестовый алерт
echo '{"rule":{"level":12,"id":999999,"description":"Telegram test"},"agent":{"name":"manager"},"data":{"srcip":"127.0.0.1"}}' > /tmp/test_alert.json
sudo -u wazuh /var/wazuh-manager/integrations/custom-telegram /tmp/test_alert.json "CHAT_ID" "https://api.telegram.org/botTOKEN/sendMessage"
```

### Миграционные заметки (4.x → 5.x)

- В Wazuh 5.x путь интеграций изменен: `/var/ossec/integrations/` → `/var/wazuh-manager/integrations/`.
- Демон переименован и получил многопоточность: `wazuh-integratord` теперь поддерживает `max_workers`.
- Используйте встроенный Python: `/var/wazuh-manager/framework/python/bin/python3` вместо системного.
- В `ossec.conf` тег `<integration>` остался без изменений, но добавлен тег `<options>` для метаданных.
- Права доступа: `chown root:wazuh` и `chmod 750` остаются обязательными.
- Проверка конфигурации: `/var/ossec/bin/ossec-control` → `/var/wazuh-manager/bin/wazuh-engine-check -t`.

### Best Practices

1.  **Фильтрация алертов:** Используйте `<level>` и `<group>` в `ossec.conf` для отправки только критических событий. Отправка всех алертов (level < 10) создает шум и риск блокировки бота.
2.  **Батчинг:** Для сред с высокой частотой алертов (>5/сек) группируйте сообщения в скрипте, используйте `time.sleep()` при получении 429, или увеличьте `<level>`.
3.  **Таймауты:** Устанавливайте `timeout=10` в `requests.post()` и `max_retries=3` с exponential backoff для предотвращения зависаний `integratord`.
4.  **Валидация:** Всегда проверяйте конфигурацию через `wazuh-engine-check -t` перед перезапуском. Тестируйте скрипт вручную через `sudo -u wazuh`.
5.  **Безопасность:** Используйте HTTPS, ограничьте сетевой доступ к `api.telegram.org`, регулярно ротируйте Bot Token через `@BotFather`.
6.  **Мониторинг:** Добавьте проверку работоспособности интеграции в корпоративный мониторинг (Zabbix/Prometheus) — триггер на отсутствие сообщений в чате за N минут.
7.  **Документация:** Документируйте назначение каждого Chat ID (SOC, Dev, Management) и уровень алертов, которые в него поступают.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Алерты не приходят в Telegram** | Неверный `hook_url` или токен | Проверьте URL и токен в конфигурации; смотрите `integrations.log` |
| **Ошибка 401/403** | Токен невалиден или истек | Перегенерируйте токен через `@BotFather`; проверьте права бота в группе |
| **Ошибка 429 Too Many Requests** | Превышен лимит Bot API | Увеличьте `level` порог, реализуйте retry с `retry_after` или батчинг |
| **integratord не запускает скрипт** | Неправильные права или владелец | `chown root:wazuh` и `chmod 750` на скрипт |
| **Высокая задержка доставки** | Очередь integratord переполнена | Увеличьте `max_workers` или добавьте промежуточный буфер |
| **Дубль алертов** | Несколько блоков `<integration>` с одинаковым `name` и `level` | Проверьте уникальность `name`/`level` или используйте `<group>` |
| **Ошибка SSL/TLS** | Сертификат не доверен или нет доступа к HTTPS | Проверьте trust store, используйте `verify=True` в `requests` |

### Edge Cases и ограничения

*   **Длина сообщения:** Telegram ограничивает `sendMessage` 4096 символами. При превышении возвращается `400 Bad Request`. В скрипте обрезайте `description` или используйте HTML-разметку.
*   **Размер алерта:** Если JSON-алерт содержит огромный `data` блок (например, полный вывод `syscheck`), ограничьте его в скрипте перед форматированием.
*   **Имена хостов с пробелами:** Telegram не экранирует пробелы в Markdown. Используйте `agent_name.replace(' ', '_')` в форматировании.
*   **Сетевые разрывы:** При недоступности `api.telegram.org` алерты теряются (no persistence). Для критических сред используйте промежуточный буфер (RabbitMQ/Redis) перед отправкой.
*   **Группы Telegram:** Бот должен быть добавлен в группу как администратор с правами отправки сообщений. `CHAT_ID` для групп начинается с `-100`.
*   **Ограничение integratord:** Даже в Wazuh 5.x `integratord` является single-threaded на один скрипт. Для тысяч алертов в секунду требуется архитектура с очередью (Fluentd/Redis).

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Правила корреляции в Wazuh](./wazuh-rules.md) — оптимизация потока уведомлений.
- [Интеграция Wazuh и Zabbix](./zabbix-integration.md) — мониторинг через корпоративный стек.
