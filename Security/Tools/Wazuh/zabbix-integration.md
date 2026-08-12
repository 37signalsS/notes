# Интеграция Wazuh и Zabbix

## Определения

**Интеграция SIEM и мониторинга** — процесс автоматизированной передачи алертов безопасности из Wazuh в Zabbix. Это позволяет объединить экспертизу ИБ-отдела с отлаженными процессами реагирования ИТ-департамента (дежурные смены, эскалации, Telegram-оповещения).

**`history.push`** — метод Zabbix API (доступен с версии 7.0+), предназначенный для высокопроизводительной отправки данных во внутренние элементы (Trapper, HTTP Agent) напрямую через JSON-RPC, минуя утилиту `zabbix_sender`.

**`wazuh-integratord`** — фоновый процесс (демон) менеджера Wazuh, отвечающий за выполнение внешних скриптов интеграции при срабатывании правил определенного уровня или группы.

## Основные концепции

### Методы передачи данных

В современной инфраструктуре (актуальность 2026 г.) выделяют три подхода:

1.  **API Push (Рекомендуемый):** Использование метода `history.push`. Преимущества: поддержка современных API-токенов, передача нескольких метрик в одном HTTP-запросе, отсутствие зависимости от бинарных файлов на хосте.
2.  **Zabbix Sender (Legacy):** Использование одноименной утилиты. Подходит для систем, где использование API ограничено политиками или используются версии Zabbix ниже 7.0.
3.  **Buffered Ingestion (High Load):** Использование промежуточного звена (Fluentd/Logstash) для буферизации алертов при потоке более 10 событий в секунду, чтобы избежать блокировок `integratord`.

### Маппинг сущностей
Для корректной работы интеграции имя агента в Wazuh должно точно соответствовать **Host Name** в Zabbix. Это позволяет динамически распределять алерты по соответствующим узлам сети в мониторинге.

## Практические сценарии

### 1. Настройка Zabbix (7.0+)

1.  **API Токен:** Создайте выделенного пользователя (Service Account) и сгенерируйте API-токен с неограниченным сроком действия.
2.  **Шаблон:** Создайте шаблон `Template Security Wazuh` с элементами данных типа **Zabbix trapper**:
    *   Имя: `Wazuh Alert Level` | Ключ: `wazuh.level` | Тип: Числовой.
    *   Имя: `Wazuh Description` | Ключ: `wazuh.description` | Тип: Текст.
3.  **Безопасность:** В настройках Trapper-элементов укажите IP менеджера Wazuh в поле **Allowed hosts**.

### 2. Реализация через API history.push (Python)

Создайте скрипт `/var/ossec/integrations/custom-zabbix.py`:

```python
#!/usr/bin/env python3
import sys
import json
import requests

# Захват аргументов от Wazuh
alert_file = sys.argv[1]
api_token = sys.argv[2]
hook_url = sys.argv[3]

# Чтение алерта
with open(alert_file, 'r') as f:
    alert = json.load(f)

# Маппинг данных
zabbix_host = alert.get('agent', {}).get('name', 'WazuhManager')
level = alert.get('rule', {}).get('level')
description = alert.get('rule', {}).get('description')
rule_id = alert.get('rule', {}).get('id')

# Формирование JSON-RPC запроса
payload = {
    "jsonrpc": "2.0",
    "method": "history.push",
    "params": [
        {"host": zabbix_host, "key": "wazuh.level", "value": level},
        {"host": zabbix_host, "key": "wazuh.description", "value": f"ID:{rule_id} - {description}"}
    ],
    "auth": api_token,
    "id": 1
}

# Отправка в Zabbix
try:
    r = requests.post(hook_url, json=payload, timeout=5)
    r.raise_for_status()
except Exception as e:
    print(f"Error sending to Zabbix: {e}")
    sys.exit(1)
```

**Права доступа:** `chown root:wazuh /var/ossec/integrations/custom-zabbix.py && chmod 750 /var/ossec/integrations/custom-zabbix.py`.

### 3. Конфигурация Wazuh Manager (`ossec.conf`)

Активируйте интеграцию, ограничив ее критическими алертами для снижения нагрузки.

```xml
<ossec_config>
  <integration>
    <name>custom-zabbix.py</name>
    <hook_url>https://zabbix.example.com/api_jsonrpc.php</hook_url>
    <api_key>your_service_token_here</api_key>
    <level>10</level>
    <group>authentication_failed,virus,pci_dss_10.2.4</group>
    <alert_format>json</alert_format>
  </integration>
</ossec_config>
```

## Дополнительная информация

### Оптимизация и безопасность
*   **Rate Limiting:** Демон `integratord` работает в один поток. Если количество алертов превышает 5-7 в секунду, используйте `Fluentd` на стороне менеджера для батчинга событий перед отправкой в Zabbix API.
*   **Audit Log:** В Zabbix 7.0+ все действия `history.push` фиксируются в **Reports -> Audit Log**. Это основной инструмент для отладки прав доступа токена.
*   **HTTPS:** Всегда используйте TLS для взаимодействия с API, так как в теле запроса передается API-токен.

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Zabbix: трапперы и push-модель](../../../Zabbix/definitions_and_concepts.md#модели-сбора-данных)
- [Zabbix: установка и настройка](../../../Zabbix/installation.md) — детали развертывания Server и Proxy.
- [Интеграция Authentik и Wazuh](./authentik-sso-integration.md) — аудит событий доступа.
