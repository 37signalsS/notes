# Правила корреляции и обнаружения в Wazuh

## Определения

**Корреляция событий (Event Correlation)** — процесс сопоставления и анализа потока событий в режиме реального времени для выявления логических связей и сложных атак, которые невозможно обнаружить при анализе одиночных событий. В **Wazuh 5.0+** корреляция трансформирована в систему генерации находок (**Findings**), обогащенную данными из глобальной базы угроз.

**Движок детектирования (Detection Engine 5.0)** — гибридная система Wazuh, поддерживающая как классический XML-синтаксис правил, так и нативный формат **Sigma (YAML)** для описания логики обнаружения угроз.

**Маппинг MITRE ATT&CK** — процесс автоматического сопоставления правил с тактиками и техниками атак. В 2026 году Wazuh обеспечивает нативную поддержку **MITRE ATT&CK v16+** с автоматическим обновлением через облачный сервис **Wazuh CTI**.

## Основные концепции

### Эволюция правил в Wazuh 5.0 (2026)

Версия 5.0 привносит фундаментальные изменения в процесс описания и обработки угроз:

1.  **Нативная поддержка Sigma**: Wazuh теперь напрямую выполняет правила в формате Sigma (`.yml`). Это позволяет использовать общемировое сообщество правил обнаружения без предварительной конвертации в XML.
2.  **YAML-декодеры**: На смену сложным XML-декодерам пришли иерархические YAML-конфигурации, которые проще в поддержке и поддерживают высокопроизводительный парсинг через регулярные выражения **PCRE2**.
3.  **Findings вместо Alerts**: Правила теперь генерируют структурированные объекты безопасности. События без алертов ("Non-alerted events") остаются видимыми в системе по умолчанию, что упрощает ретроспективный анализ и поиск угроз (**Threat Hunting**).
4.  **Wazuh CTI Streaming**: Правила могут ссылаться на динамические списки индикаторов компрометации (IP, домены, хеши), которые доставляются в менеджер в реальном времени из облака Wazuh.

### Типы условий и корреляции

*   **Частота (`frequency`)**: Количество срабатываний за интервал времени (`timeframe`).
*   **Логическое сопоставление**:
    *   `same_source_ip` / `same_user`: Идентификация атак от одного субъекта.
    *   `same_field`: Совпадение любого кастомного поля (например, `client_id` или `request_id`).
*   **Sigma Logic (NEW)**: Возможность использования сложной булевой логики (`selection`, `condition`, `filter`) непосредственно в YAML-правилах.

### Структура и расположение файлов

С переходом на Wazuh 5.0 пути нормализованы:
*   **Стандартные (Ruleset)**: `/var/wazuh-manager/ruleset/rules/` — системные правила, обновляемые через CTI.
*   **Пользовательские (Local)**: `/var/wazuh-manager/etc/rules/local_rules.xml` — приоритетное место для XML-правил.
*   **Sigma-правила**: `/var/wazuh-manager/etc/rules/sigma/` — директория для YAML-правил обнаружения.

## Практические сценарии

### 1. Иерархия правил (на примере SSH)

Логика обнаружения часто строится каскадно:

**Шаг А: Группировка (уровень 0)**
Фильтрует все события от конкретного сервиса (`sshd`).
```xml
<rule id="5700" level="0" noalert="1">
  <decoded_as>sshd</decoded_as>
  <description>SSHD messages grouped.</description>
</rule>
```

**Шаг Б: Одиночное событие (уровень 5)**
Детектирует факт неудачной аутентификации, ссылаясь на родительскую группу и подтехнику MITRE.
```xml
<rule id="5716" level="5">
  <if_sid>5700</if_sid>
  <match>^Failed|^error: PAM: Authentication</match>
  <description>sshd: authentication failed.</description>
  <mitre>
    <id>T1110.001</id> <!-- Brute Force: Password Guessing -->
  </mitre>
</rule>
```

**Шаг В: Корреляция по частоте (уровень 10)**
Генерирует критический алерт (Finding) при 5 неудачных попытках с одного IP за 360 секунд.
```xml
<rule id="5720" level="10" frequency="5" timeframe="360">
  <if_matched_sid>5716</if_matched_sid>
  <same_source_ip />
  <description>sshd: Multiple authentication failures.</description>
</rule>
```

### 2. Пример Sigma-правила (YAML)

В Wazuh 5.0 Sigma-правила позволяют описывать логику, которую сложно реализовать в XML (например, проверку нескольких полей с оператором `OR`).

**Файл:** `/var/wazuh-manager/etc/rules/sigma/suspicious_powershell.yml`
```yaml
title: Suspicious PowerShell Download
status: experimental
description: Detects PowerShell downloading content via Net.WebClient
logsource:
    product: windows
    service: powershell
detection:
    selection:
        EventID: 4104
        ScriptBlockText|contains:
            - 'Net.WebClient'
            - 'DownloadFile'
            - 'DownloadString'
    condition: selection
falsepositives:
    - Administrative scripts
level: high
```

### 3. Переопределение (Overwrite) правил

В Wazuh 5.0 при переопределении стандартных правил используйте тег `overwrite="yes"`. Помните, что пути к системным правилам теперь содержат `wazuh-manager`.

1.  Скопируйте оригинал из `/var/wazuh-manager/ruleset/rules/` в `/var/wazuh-manager/etc/rules/local_rules.xml`.
2.  Добавьте атрибут `overwrite="yes"`.

**Сценарий: Повышение уровня серьезности для Brute-force**
```xml
<rule id="5760" level="13" overwrite="yes">
  <if_sid>5700,5716</if_sid>
  <match>Failed password|Failed keyboard|authentication error</match>
  <description>sshd: authentication failed. Critical alert for Telegram/Zabbix.</description>
</rule>
```

### 4. Использование same_field для облачных логов

Для корреляции событий по идентификаторам запросов в JSON-логах (например, AWS CloudTrail):
```xml
<rule id="100002" level="10" frequency="10" timeframe="60">
  <if_matched_sid>100001</if_matched_sid>
  <same_field>aws.requestID</same_field>
  <description>Rate limit exceeded for a specific AWS Request ID</description>
</rule>
```

## Дополнительная информация

### Управление и отладка (Wazuh 5.0)

В 2026 году процессы тестирования и применения правил оптимизированы для поддержки гибридных форматов:
*   **Валидация XML**: Используйте `/var/wazuh-manager/bin/wazuh-logtest` для проверки логики срабатывания XML-правил и декодеров.
*   **Валидация Sigma**: Для проверки YAML-правил используйте встроенную утилиту `/var/wazuh-manager/bin/sigma-checker`. Она проверяет синтаксис и маппинг полей на схему данных Wazuh.
*   **Применение**: Требуется перезапуск менеджера для перечитывания конфигурации: `systemctl restart wazuh-manager`.
*   **Мониторинг FP**: Используйте дашборд "Detection Quality" для идентификации правил с аномально высокой частотой срабатываний (False Positives).

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Декодеры в Wazuh: кастомная настройка](./custom-decoders.md) — YAML-декодеры и PCRE2.
- [Автоматизация Wazuh через Ansible](./ansible-automation-per-agent.md) — управление Detection as Code.
