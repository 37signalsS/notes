# Интеграция Wazuh и Zabbix

## Определения

**Интеграция SIEM и мониторинга** — процесс автоматизированной передачи алертов безопасности из Wazuh в Zabbix. Это позволяет объединить экспертизу ИБ-отдела с отлаженными процессами реагирования ИТ-департамента (дежурные смены, эскалации, Telegram-оповещения).

**`history.push`** — метод Zabbix API (доступен с версии 7.0+), предназначенный для высокопроизводительной отправки данных во внутренние элементы (Trapper, HTTP Agent) напрямую через JSON-RPC, минуя утилиту `zabbix_sender`.

**`wazuh-integratord`** — фоновый процесс (демон) менеджера Wazuh, отвечающий за выполнение внешних скриптов интеграции при срабатывании правил определенного уровня или группы. В Wazuh 5.0+ работает в многопоточном режиме с нормализованными путями `/var/wazuh-manager/integrations/`.

**Zabbix Trapper** — тип элемента данных (Item) в Zabbix, принимающий входящие значения по модели Push. Используется для приема данных от внешних систем через API или `zabbix_sender`.

**API-токен Zabbix** — строка авторизации (UUID), генерируемая в веб-интерфейсе Zabbix для доступа к JSON-RPC API без передачи логина и пароля.

**Архитектура интеграции Wazuh → Zabbix**:
```
Агент Wazuh → Менеджер (analysisd) → Правило сработало → wazuh-integratord → Скрипт интеграции → Zabbix API (history.push) → Trapper Item → Trigger → Alert
```

## Основные концепции

### Методы передачи данных

В современной инфраструктуре (актуальность 2026 г.) выделяют три подхода:

| Метод | Механизм | Преимущества | Недостатки | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **API Push (`history.push`)** | JSON-RPC через HTTP POST | Высокая производительность, батчинг, токены, нет зависимости от бинарных файлов | Требует Zabbix 7.0+ | **Рекомендуется** для новых инсталляций |
| **Zabbix Sender (Legacy)** | Утилита `zabbix_sender` через TCP | Работает на любых версиях Zabbix, стабильность | Нет батчинга, требует установки пакета на хосте | Для Zabbix < 7.0 |
| **Buffered Ingestion (High Load)** | Промежуточный буфер (Fluentd/Logstash) | Снижает пиковую нагрузку на `integratord`, обеспечивает durability | Усложняет архитектуру, добавляет hop | При >10 событий/сек |

### Маппинг сущностей

Для корректной работы интеграции имя агента в Wazuh должно точно соответствовать **Host Name** в Zabbix. Это позволяет динамически распределять алерты по соответствующим узлам сети в мониторинге.

**Важные правила маппинга:**
1. **Case-sensitive:** `web-01` ≠ `Web-01`. Убедитесь, что имя агента в Wazuh точно совпадает с `Host name` в Zabbix.
2. **Новые хосты:** При автоматическом добавлении агента в Wazuh создайте соответствующий хост в Zabbix или используйте LLD (Low-Level Discovery).
3. **Динамические хосты:** Для контейнеров/вм с динамическими именами используйте макросы `{#HOSTNAME}` и LLD-правила.

### Архитектура Wazuh 5.x для интеграций

В Wazuh 5.0+ архитектура интеграций изменилась:
1. **Параллельное выполнение:** Демон `wazuh-integratord` поддерживает параллельный запуск скриптов через пул воркеров (`max_workers`).
2. **Нормализация путей:** Все интеграции размещаются в `/var/wazuh-manager/integrations/`.
3. **Изолированное окружение:** Скрипты выполняются через встроенный Python: `/var/wazuh-manager/framework/python/bin/python3`.
4. **Расширенные опции:** Тег `<options>` позволяет передавать метаданные в скрипт без изменения кода.

## Практические сценарии

### Предварительные требования

- **Wazuh Manager** 4.9+ (рекомендуется 5.x).
- **Zabbix Server** 7.0+ для `history.push` или 6.0+ для `zabbix_sender`.
- Сеть: доступ из Wazuh Manager на порт 443 (HTTPS) Zabbix Frontend API.
- Права: сервисный аккаунт Zabbix с токеном доступа к API.
- TLS-сертификаты: для продакшена используйте проверенные сертификаты, а не самоподписанные.

### 1. Настройка Zabbix (7.0+)

1.  **API Токен:** Создайте выделенного пользователя (Service Account) с ролью "Super admin" или ограниченными правами на создание элементов данных. Сгенерируйте API-токен с неограниченным сроком действия.
2.  **Шаблон:** Создайте шаблон `Template Security Wazuh` с элементами данных типа **Zabbix trapper** или **HTTP Agent**:
    *   Имя: `Wazuh Alert Level` | Ключ: `wazuh.level` | Тип: Числовой.
    *   Имя: `Wazuh Description` | Ключ: `wazuh.description` | Тип: Текст.
    *   Имя: `Wazuh Agent Name` | Ключ: `wazuh.agent` | Тип: Текст.
3.  **Безопасность:** В настройках Trapper-элементов укажите IP менеджера Wazuh в поле **Allowed hosts**. Включите TLS для Frontend (`TLSFrontendAccept=cert`).

### 2. Реализация через API history.push (Python, Wazuh 5.x)

Создайте файл `/var/wazuh-manager/integrations/custom-zabbix`:

```python
#!/var/wazuh-manager/framework/python/bin/python3
import sys
import json
import requests
from datetime import datetime

# 1. Получение аргументов от wazuh-integratord
# [1] Путь к JSON-файлу алерта, [2] API Key (Chat ID/Token), [3] Hook URL
alert_file_path = sys.argv[1]
api_token = sys.argv[2]
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

# 4. Формирование JSON-RPC запроса (history.push)
payload = {
    "jsonrpc": "2.0",
    "method": "history.push",
    "params": [
        {"host": agent_name, "key": "wazuh.level", "value": level},
        {"host": agent_name, "key": "wazuh.description", "value": f"ID:{rule_id} - {description}"},
        {"host": agent_name, "key": "wazuh.agent", "value": agent_name}
    ],
    "auth": api_token,
    "id": 1
}

# 5. Отправка в Zabbix с обработкой ошибок
try:
    response = requests.post(hook_url, json=payload, timeout=10)
    response.raise_for_status()
    result = response.json()
    if 'error' in result:
        print(f"Zabbix API error: {result['error']}")
        sys.exit(1)
except Exception as e:
    # Запись ошибок в специализированный лог Wazuh
    with open('/var/wazuh-manager/logs/integrations.log', 'a') as log:
        log.write(f"{datetime.now()} [Error] custom-zabbix: {str(e)}\n")
    sys.exit(1)

sys.exit(0)
```

**Права доступа:**
```bash
chown root:wazuh /var/wazuh-manager/integrations/custom-zabbix
chmod 750 /var/wazuh-manager/integrations/custom-zabbix
```

### 3. Реализация через Zabbix Sender (Legacy, для Zabbix < 7.0)

Для старых версий Zabbix или ограниченных сред используйте `zabbix_sender`:

```bash
#!/bin/bash
# /var/wazuh-manager/integrations/custom-zabbix-sender
ALERT_FILE="$1"
ZBX_SERVER="$2"
ZBX_HOST="$3"

# Парсинг JSON
LEVEL=$(jq -r '.rule.level' "$ALERT_FILE")
DESCRIPTION=$(jq -r '.rule.description' "$ALERT_FILE")
AGENT=$(jq -r '.agent.name' "$ALERT_FILE")

# Отправка
zabbix_sender -z "$ZBX_SERVER" -s "$AGENT" -k wazuh.level -o "$LEVEL" 2>/dev/null
zabbix_sender -z "$ZBX_SERVER" -s "$AGENT" -k wazuh.description -o "$DESCRIPTION" 2>/dev/null
```

### 4. Конфигурация Wazuh Manager (`ossec.conf`)

Активируйте интеграцию, ограничив ее критическими алертами для снижения нагрузки:

```xml
<ossec_config>
  <integration>
    <name>custom-zabbix</name>
    <level>10</level>
    <group>authentication_failed,virus,pci_dss_10.2.4</group>
    <alert_format>json</alert_format>
    <hook_url>https://zabbix.example.com/api_jsonrpc.php</hook_url>
    <api_key>your_service_token_here</api_key>
    <options>{"environment": "production", "team": "soc"}</options>
  </integration>
</ossec_config>
```

**Валидация конфигурации:**
```bash
# Проверка синтаксиса ossec.conf
/var/wazuh-manager/bin/wazuh-engine-check -t

# Проверка статуса integratord
ps aux | grep integratord

# Тестовый запуск скрипта (подстановка аргументов)
echo '{"rule":{"level":10,"id":100001,"description":"Test"},"agent":{"name":"test-agent"}}' > /tmp/test_alert.json
sudo -u wazuh /var/wazuh-manager/integrations/custom-zabbix /tmp/test_alert.json TOKEN_URL
```

### 5. Настройка Zabbix Host и Template

1. **Создание хоста:** Добавьте хост в Zabbix с именем, точно соответствующим агенту Wazuh.
2. **Привязка шаблона:** Назначьте шаблон `Template Security Wazuh` хосту.
3. **Создание триггеров:** Пример триггера на критический уровень:
   - `Условие: ` `last(/Wazuh Agent/wazuh.level)>=12`
   - `Имя: ` `Wazuh Critical Alert on {HOST.NAME}`
4. **Действие:** Настройте эскалацию: уведомление в Telegram/Email при срабатывании триггера.

### 6. Автоматизация развертывания через Ansible

```yaml
- name: Deploy Zabbix integration script
  copy:
    src: files/custom-zabbix
    dest: /var/wazuh-manager/integrations/custom-zabbix
    owner: root
    group: wazuh
    mode: '0750'

- name: Configure Wazuh integration in ossec.conf
  xml:
    path: /var/wazuh-manager/etc/ossec.conf
    xpath: /ossec-config/integration[name='custom-zabbix']
    pretty_print: yes
    content: "{{ lookup('template', 'integration.xml.j2') }}"
  notify: restart wazuh-manager

- name: Create Zabbix host via API
  uri:
    url: https://zabbix.example.com/api_jsonrpc.php
    method: POST
    body_format: json
    headers:
      Authorization: "Bearer {{ zabbix_api_token }}"
    body:
      jsonrpc: "2.0"
      method: "host.create"
      params:
        host: "{{ inventory_hostname }}"
        groups:
          - name: "Linux servers"
        templates:
          - name: "Template Security Wazuh"
        interfaces:
          - type: 1
            main: 1
            useip: 1
            ip: "{{ ansible_host }}"
            dns: ""
            port: "10050"
      id: 1
  delegate_to: localhost
```

### 7. CI/CD пайплайн для политик интеграции

```yaml
name: Wazuh-Zabbix Integration CI/CD

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate XML syntax
        run: python3 scripts/validate_ossec_conf.py Security/Tools/Wazuh/ossec.conf
      - name: Lint Python integration script
        run: flake8 Security/Tools/Wazuh/custom-zabbix.py
      - name: Deploy to staging
        if: github.ref == 'refs/heads/main'
        run: ansible-playbook -i inventory/staging playbooks/deploy_zabbix_integration.yml
```

### 8. Бэкап и восстановление конфигурации

```bash
# Бэкап
BACKUP_DIR="/var/backups/wazuh-zabbix-$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/wazuh-zabbix-integration.tar.gz" \
  /var/wazuh-manager/integrations/custom-zabbix \
  /var/wazuh-manager/etc/ossec.conf \
  /etc/zabbix/zabbix_agentd.conf

# Восстановление
tar -xzf /var/backups/wazuh-zabbix-20250918.tar.gz -C /
chown root:wazuh /var/wazuh-manager/integrations/custom-zabbix
chmod 750 /var/wazuh-manager/integrations/custom-zabbix
/var/wazuh-manager/bin/wazuh-engine-check -t
systemctl restart wazuh-manager
```

## Дополнительная информация

### Оптимизация и безопасность

*   **Rate Limiting:** Демон `integratord` работает в один поток на скрипт. Если количество алертов превышает 5-7 в секунду, используйте `Fluentd` на стороне менеджера для батчинга событий перед отправкой в Zabbix API. В Wazuh 5.x настройте `<max_workers>` для параллелизации.
*   **Audit Log:** В Zabbix 7.0+ все действия `history.push` фиксируются в **Reports -> Audit Log**. Это основной инструмент для отладки прав доступа токена.
*   **HTTPS:** Всегда используйте TLS для взаимодействия с API, так как в теле запроса передается API-токен. Проверяйте сертификаты (`requests.post(..., verify=True)`).
*   **Ротация логов:** Мониторьте `/var/wazuh-manager/logs/integrations.log` на предмет ошибок `429 Too Many Requests` или таймаутов. Настройте `logrotate` для предотвращения заполнения диска.
*   **Сетевая сегментация:** Разместите Wazuh Manager и Zabbix Server в одной подсети или VPN для снижения задержек и упрощения firewall-правил.

### Телеметрия и мониторинг интеграции

```bash
# Проверка статуса демона integratord
ps aux | grep integratord

# Мониторинг логов интеграций
tail -n 50 /var/wazuh-manager/logs/integrations.log

# Проверка очереди integratord (если доступно)
/var/wazuh-manager/bin/wazuh-integratord -t
```

### Сравнение методов интеграции

| Критерий | API Push (`history.push`) | Zabbix Sender | Fluentd/Logstash |
| :--- | :--- | :--- | :--- |
| **Версия Zabbix** | 7.0+ | Любая | Любая |
| **Производительность** | Высокая (батчинг) | Средняя | Высокая (буферизация) |
| **Зависимости** | requests, HTTPS | zabbix_sender | Fluentd/Logstash |
| **Надежность** | Зависит от сети | Накопление на агенте | Высокая (persistent queue) |
| **Сложность** | Низкая | Низкая | Высокая |

### Миграционные заметки (4.x → 5.x)

- В Wazuh 5.x путь интеграций изменен: `/var/ossec/integrations/` → `/var/wazuh-manager/integrations/`.
- Демон переименован: `wazuh-integratord` остался, но теперь работает в многопоточном режиме.
- Используйте встроенный Python: `/var/wazuh-manager/framework/python/bin/python3` вместо системного.
- В `ossec.conf` тег `<integration>` остался без изменений, но добавлен тег `<options>` для метаданных.
- Права доступа: `chown root:wazuh` и `chmod 750` остаются обязательными.

### Best Practices

1.  **Фильтрация алертов:** Используйте `<level>` и `<group>` в `ossec.conf` для отправки только критических событий. Отправка всех алертов (level < 10) создает шум в Zabbix.
2.  **Батчинг:** Для высоконагруженных сред (>10 алертов/сек) используйте промежуточный буфер (Fluentd) или увеличьте `<max_workers>` в конфигурации integratord.
3.  **Таймауты:** Устанавливайте `timeout=5-10` в Python-скрипте для предотвращения зависаний integratord.
4.  **Валидация:** Всегда проверяйте конфигурацию через `wazuh-engine-check -t` перед перезапуском.
5.  **Безопасность:** Используйте TLS, ограничьте `Allowed hosts` в Zabbix, регулярно ротируйте API-токены.
6.  **Мониторинг:** Добавьте проверку работоспособности интеграции в Zabbix (например, триггер на отсутствие данных за 5 минут).

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Алерты не приходят в Zabbix** | Неверный `hook_url` или токен | Проверьте URL и токен в конфигурации; смотрите `integrations.log` |
| **Ошибка 401/403 в Zabbix** | Токен невалиден или истек | Перегенерируйте токен в Zabbix; проверьте права пользователя |
| ** integratord не запускает скрипт** | Неправильные права или владелец | `chown root:wazuh` и `chmod 750` на скрипт |
| **Высокая задержка доставки** | Очередь integratord переполнена | Увеличьте `max_workers` или добавьте Fluentd-буфер |
| **Дубль алертов в Zabbix** | Дублирование правил в Wazuh | Проверьте `<group>` и `<level>`; убедитесь, что правило срабатывает один раз |
| **Zabbix троттлит запросы** | Превышен лимит `history.push` | Увеличьте интервал или используйте батчинг через `history.push` с несколькими параметрами |
| **Ошибки SSL/TLS** | Сертификат не доверен | Добавьте сертификат в trust store или используйте `verify=False` только для тестов |

### Edge Cases и ограничения

- **Большие алерты:** Zabbix API имеет ограничение на размер тела запроса (обычно 64 KB). Если алерт содержит огромный `data` блок, обрежьте его в скрипте.
- **Сетевые разрывы:** При недоступности Zabbix алерты теряются (no persistence). Для критических сред используйте Fluentd с persistent queue.
- **Имя хоста с пробелами:** Zabbix не поддерживает пробелы в `Host Name`. Используйте `replace()` в Python для нормализации имен агентов.
- **Zabbix Proxy:** При использовании Proxy убедитесь, что он поддерживает `history.push` (требуется Zabbix 7.0+ на Proxy). Иначе используйте `zabbix_sender` на хосте с Wazuh Manager.
- **Ограничение integratord:** Даже в Wazuh 5.x `integratord` является single-threaded на один скрипт. Для тысяч алертов в секунду требуется архитектура с очередью.

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Zabbix: трапперы и push-модель](../../../Zabbix/definitions_and_concepts.md#модели-сбора-данных)
- [Zabbix: установка и настройка](../../../Zabbix/installation.md) — детали развертывания Server и Proxy.
- [Интеграция Authentik и Wazuh](./authentik-sso-integration.md) — аудит событий доступа.
