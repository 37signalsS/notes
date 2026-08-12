# Сбор логов (Logcollector) в Wazuh

## Определения

**Wazuh Logcollector** — высокопроизводительный компонент агента (в версии 5.0+ интегрирован в единый **Wazuh-Engine**), ответственный за сбор (ингестию), первичную фильтрацию и нормализацию данных телеметрии. Поддерживает работу с файлами, системными журналами, выводом команд и сетевыми протоколами.

**YAML Configuration (Wazuh 5.x)** — современный стандарт описания источников данных, сосуществующий с классическим XML. Позволяет использовать иерархические структуры и динамически обновлять параметры сбора через REST API без перезагрузки процессов.

**ECS (Elastic Common Schema)** — стандарт именования полей, нативно поддерживаемый Logcollector 5.0. Модуль автоматически маппирует структурированные логи (JSON) в ECS, что обеспечивает кросс-платформенную корреляцию событий.

## Основные концепции

### Источники данных и механизмы сбора (2026)

В современных инфраструктурах Wazuh-Engine обеспечивает сбор сигналов через следующие механизмы:

1.  **Файловые источники (localfile)**:
    *   **Статичные пути**: Прямое указание файла (например, `/var/log/syslog`).
    *   **Ротация (Wildcards)**: Мониторинг групп файлов по маскам (PCRE2). Лимит увеличен до 2000 файлов на блок.
    *   **Динамические пути (strftime)**: Использование форматов даты (например, `/var/log/app-%Y-%m-%d.log`).
2.  **Системные журналы (Native)**:
    *   **Journald**: Нативное чтение бинарного журнала systemd с извлечением метаданных (`_SYSTEMD_UNIT`, `_PID`, `_COMM`, `_EXE`).
    *   **Eventchannel**: Сбор событий Windows через современный API (Vista+), позволяющий использовать XPath для фильтрации на источнике.
    *   **macOS Unified Logging**: Интеграция с системой журналов Apple.
3.  **OpenTelemetry (OTLP)**:
    *   Агент Wazuh 5.0 может выступать в роли **OTLP Receiver** (gRPC/HTTP), принимая логи и трейсы напрямую от инструментов инструментации приложений.
4.  **Командный сбор (Command)**:
    *   Сбор вывода системных утилит в виде логов. Требует `logcollector.remote_commands=1` в `internal_options`.

### Форматы логов (Log Format)

| Формат | Описание | Особенности 5.0 |
| :--- | :--- | :--- |
| **syslog** | RFC3164/5424. | Поддержка кастомных заголовков и временных зон. |
| **json** | Валидные JSON-объекты. | Автоматический маппинг в **ECS**. |
| **eventchannel** | Windows Event Log. | Передается как структурированный JSON с XML-метаданными. |
| **audit** | Linux Auditd. | Нативная сборка многострочных событий по `audit_id`. |
| **journald** | systemd journal. | Поддержка фильтрации по полям (Field-based filtering). |
| **multi-line** | Фиксированное число строк. | Полезно для старых приложений с жестким форматом. |
| **multi-line-regex** | Сборка по паттерну. | Оптимально для Java Stacktrace и многострочных логов Python. |
| **otlp** | OpenTelemetry signals. | Прямая ингестия без промежуточных файлов. |

## Практические сценарии

### 1. Мониторинг команд и метрик (YAML)

Пример мониторинга сетевого состояния и списка пользователей с использованием YAML-синтаксиса 5.0.

```yaml
logcollector:
  localfiles:
    # Проверка внешнего IP раз в сутки
    - command: curl -s https://ifconfig.me
      log_format: command
      alias: external_ip_check
      frequency: 86400
      labels:
        check_type: external_network
    
    # Мониторинг активных пользователей (многострочный вывод)
    - command: w
      log_format: full_command
      alias: active_users
      frequency: 300
```

### 2. Сложная фильтрация Windows (XPath Query)

Для снижения шума на Domain Controllers (DC) используйте исключение конкретных EventID.

```xml
<localfile>
    <location>Security</location>
    <log_format>eventchannel</log_format>
    <!-- Исключение шумных событий: 5145 (Network share access), 5156 (Filtering Platform Connection) и др. -->
    <query>Event/System[EventID != 5145 and EventID != 5156 and EventID != 5447 and
      EventID != 4656 and EventID != 4658 and EventID != 4663 and EventID != 4660 and
      EventID != 4670 and EventID != 4690 and EventID != 4703 and EventID != 4907 and
      EventID != 5152 and EventID != 5157 and EventID != 4634 and EventID != 4624 and
      EventID != 4672 and EventID != 4616 and EventID != 4755]</query>
</localfile>

<localfile>
    <location>System</location>
    <log_format>eventchannel</log_format>
    <query>Event/System[EventID != 5 (Access Denied) and EventID != 7040 (Service start type change)]</query>
</localfile>
```

### 3. Нативная фильтрация Journald

Сбор логов только для критических юнитов systemd.

```xml
<localfile>
    <location>journald</location>
    <log_format>journald</log_format>
    <filter field="_SYSTEMD_UNIT">^ssh.service$|^nginx.service$|^docker.service$</filter>
</localfile>
```

### 4. Редирект в сокет (Output Redirection)

Пересылка собранных логов в локальный сокет для внешних инструментов (например, локальный Python-анализатор).

```xml
<socket>
  <name>security_pipeline</name>
  <location>/var/wazuh-manager/run/security.sock</location>
  <mode>tcp</mode>
  <prefix>wazuh_data: </prefix>
</socket>
```

### 5. Расширенная кастомизация вывода (Out Format)

Использование плейсхолдеров для обогащения логов перед отправкой на менеджер.

| Плейсхолдер | Описание |
| :--- | :--- |
| `$(timestamp)` | Время сбора события. Поддерживает форматирование: `$(timestamp %H:%M:%S)`. |
| `$(hostname)` | Имя хоста, на котором работает агент. |
| `$(log)` | Оригинальная строка лога. |
| `$(json_escaped_log)` | Лог с экранированием для вставки в JSON. |
| `$(location)` | Путь к файлу или имя канала события. |

**Пример (нормализация под ECS):**
```xml
<localfile>
  <location>/var/log/custom_app.log</location>
  <log_format>syslog</log_format>
  <out_format>{ "event.ingested": "$(timestamp %Y-%m-%dT%H:%M:%SZ)", "host.name": "$(hostname)", "log.file.path": "$(location)", "message": "$(json_escaped_log)" }</out_format>
</localfile>
```

## Дополнительная информация

### Управление жизненным циклом файлов

*   **`<age>`**: Игнорирование файлов, не обновлявшихся более срока (например, `12h`).
*   **`<ignore>`**: Пропуск строк, соответствующих паттерну (PCRE2).
*   **`<restrict>`**: Обработка ТОЛЬКО строк, соответствующих паттерну.
*   **`<only-future-events>`**: При `yes` (дефолт) агент читает только новые строки. При `no` — считывает весь файл с учетом `max-size`.
*   **`<ignore_binaries>`**: Автоматический пропуск бинарных данных для предотвращения сбоев декодера.

### Отладка и диагностика
Все события и ошибки Logcollector (права доступа, проблемы с OTLP, ошибки парсинга) фиксируются в:
*   Linux: `/var/wazuh-manager/logs/wazuh.log`
*   Windows: `C:\Program Files (x86)\ossec-agent\ossec.log`

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Декодеры в Wazuh: кастомная настройка](./custom-decoders.md) — YAML-декодеры и PCRE2.
- [Открытая телеметрия (OpenTelemetry) в инфраструктуре](../../OpenTelemetry/opentelemetry_overview.md)
