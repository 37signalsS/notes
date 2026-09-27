# Сбор логов (Logcollector) в Wazuh

## Определения

**Wazuh Logcollector** — высокопроизводительный компонент агента (в версии 5.0+ интегрирован в единый **Wazuh-Engine**), ответственный за сбор (ингестию), первичную фильтрацию и нормализацию данных телеметрии. Поддерживает работу с файлами, системными журналами, выводом команд и сетевыми протоколами.

**localfile** — блок конфигурации в `ossec.conf`, определяющий источник данных для Logcollector. Поддерживает файлы, системные журналы (journald, Eventchannel), команды и сетевые сокеты.

**YAML Configuration (Wazuh 5.x)** — современный стандарт описания источников данных, сосуществующий с классическим XML. Позволяет использовать иерархические структуры и динамически обновлять параметры сбора через REST API без перезагрузки процессов.

**ECS (Elastic Common Schema)** — стандарт именования полей, нативно поддерживаемый Logcollector 5.0. Модуль автоматически маппирует структурированные логи (JSON) в ECS, что обеспечивает кросс-платформенную корреляцию событий.

**wazuh-logtest** — утилита для валидации декодеров и конфигурации Logcollector без перезапуска менеджера. Позволяет проверить, как сырой лог будет обработан на всех этапах (pre-decoding → decoding → rule matching).

**PCRE2 Wildcard** — механизм ротации файлов в Logcollector на базе PCRE2. Позволяет мониторить группы файлов по маскам (например, `/var/log/nginx/*.log` или `/var/log/syslog*`). Лимит увеличен до 2000 файлов на блок в Wazuh 5.0.

## Основные концепции

### Архитектура потока логов

Поток данных от источника к хранилищу в Wazuh 5.0:

```
Источник события
    │
    ├─ Файловая система
    │     └─ localfile (localfile)
    │           └─ Logcollector (агент)
    │                 └─ Wazuh-Engine / analysisd
    │                       └─ Декодеры
    │                             └─ Правила (local_rules.xml)
    │                                   └─ Alert → Indexer → Dashboard
    │
    ├─ Системные журналы
    │     ├─ journald (Linux)
    │     └─ Eventchannel (Windows)
    │           └─ Logcollector
    │                 └─ Engine → Декодеры → Правила → Alert
    │
    ├─ Команды
    │     └─ wodle command (log_format: command/full_command)
    │           └─ Engine → Декодеры → Правила → Alert
    │
    └─ Сетевые сокеты
          └─ <socket> (TCP/UNIX)
                └─ Внешние инструменты / Python-анализаторы
```

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
5.  **Сетевые сокеты (Socket)**:
    *   Прием логов по TCP/UNIX сокету от внешних систем (например, Python-анализаторы, кастомные скрипты).

### XML vs YAML конфигурация Logcollector

| Аспект | XML (`ossec.conf`) | YAML (`wazuh.yaml` / Content Manager) |
| :--- | :--- | :--- |
| **Синтаксис** | Иерархические теги `<localfile>...</localfile>` | Списки в YAML-структуре |
| **Гибкость** | Требует перезапуск для применения | Динамическое обновление через REST API |
| **Валидация** | `xmllint` + `wazuh-logtest` | `yamllint` + API валидация |
| **Поддержка IDE** | Средняя (XML plugins) | Высокая (YAML LSP) |
| **Версия** | 4.x–5.x (legacy + current) | 5.0+ (рекомендуется) |

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
| **command** | Вывод команды без аргументов. | Для простых утилит (`who`, `uptime`). |
| **full_command** | Вывод команды с аргументами. | Для детального аудита (`w`, `ps aux`). |

### Параметры localfile (ossec.conf)

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `<location>` | Путь к файлу, канал событий или команда. | Используйте абсолютные пути. Для wildcards ограничьте маску (например, `/var/log/nginx/access*.log`). |
| `<log_format>` | Формат лога. | `json` для структурированных логов, `syslog` для классических, `multi-line-regex` для stacktrace. |
| `<frequency>` | Интервал опроса файла в секундах. | По умолчанию 10s. Для высоконагруженных систем увеличьте до 30–60s. |
| `<only-future-events>` | Читать только новые строки (`yes`) или весь файл (`no`). | `yes` для production. `no` только для initial seeding. |
| `<max-size>` | Максимальный размер файла для чтения (KB/MB). | Установите `10MB` для предотвращения загрузки гигантских логов при `only-future-events=no`. |
| `<age>` | Игнорировать файлы, не обновлявшиеся дольше срока. | `12h` для ротированных логов, чтобы не перечитывать старые файлы. |
| `<ignore>` | Пропускать строки, соответствующие PCRE2-паттерну. | Исключайте шумные DEBUG-сообщения. |
| `<restrict>` | Обрабатывать ТОЛЬКО строки, соответствующие паттерну. | Используйте для снижения шума (например, только ERROR/WARN). |
| `<out_format>` | Шаблон вывода для обогащения логов. | Нормализуйте под ECS при отправке в SIEM. |
| `<label>` | Дополнительные метаданные (ключ-значение). | Используйте для маршрутизации по среде (`<label key="env">prod</label>`). |
| `<filter>` | Фильтрация для journald по полям. | `field="_SYSTEMD_UNIT"` для ограничения юнитов. |
| `<query>` | XPath-запрос для Windows Eventchannel. | Исключайте шумные EventID. |

### Изменения в Wazuh 5.x для Logcollector

- **Wazuh-Engine**: Logcollector интегрирован в единый движок, обеспечивающий параллельную обработку без блокировки `analysisd`.
- **YAML-конфигурация**: Появилась поддержка YAML-блоков для Logcollector через Content Manager API. Динамическое обновление без перезапуска.
- **Нормализация путей**: Агент использует `/var/ossec/`, менеджер — `/var/wazuh-manager/`. При развертывании wodle на менеджере (agentless) используйте пути менеджера.
- **ECS-маппинг**: JSON-логи автоматически маппятся в поля Elastic Common Schema.
- **OTLP Receiver**: Агент может принимать логи напрямую от OpenTelemetry-инструментов без файлового посредника.
- **Блокировка `<options>`**: В `ossec.conf` для `localfile` и wodle появилась поддержка `<options>` для передачи дополнительных аргументов.

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

**Пример (нормаализация под ECS):**
```xml
<localfile>
  <location>/var/log/custom_app.log</location>
  <log_format>syslog</log_format>
  <out_format>{ "event.ingested": "$(timestamp %Y-%m-%dT%H:%M:%SZ)", "host.name": "$(hostname)", "log.file.path": "$(location)", "message": "$(json_escaped_log)" }</out_format>
</localfile>
```

### 6. Мониторинг системных журналов (syslog + auth)

Базовый сценарий сбора `/var/log/syslog` (Debian/Ubuntu) или `/var/log/secure` (RHEL/CentOS) с защитой от ротации.

```xml
<localfile>
  <location>/var/log/syslog</location>
  <log_format>syslog</log_format>
  <frequency>10</frequency>
  <only-future-events>yes</only-future-events>
  <max-size>10000</max-size>
  <age>24h</age>
  <label key="source">syslog</label>
</localfile>

<localfile>
  <location>/var/log/auth.log</location>
  <log_format>syslog</log_format>
  <frequency>10</frequency>
  <only-future-events>yes</only-future-events>
  <restrict>^(.*(failed|error|invalid|refused).*)$</restrict>
  <label key="source">auth</label>
</localfile>
```

### 7. Мониторинг логов Nginx/Apache с wildcard ротацией

Для высоконагруженных веб-серверов с ежедневной ротацией.

```xml
<!-- Nginx: мониторинг всех access-логов в директории -->
<localfile>
  <location>/var/log/nginx/*access*.log</location>
  <log_format>syslog</log_format>
  <frequency>30</frequency>
  <only-future-events>yes</only-future-events>
  <age>7d</age>
  <label key="source">nginx-access</label>
</localfile>

<!-- Apache: мониторинг error.log с фильтрацией -->
<localfile>
  <location>/var/log/apache2/error.log</location>
  <log_format>syslog</log_format>
  <frequency>30</frequency>
  <restrict>^(.*(PHP Fatal error|segfault|AH01215).*)$</restrict>
  <label key="source">apache-error</label>
</localfile>
```

### 8. Сбор многострочных логов (Java Stacktrace, Python Traceback)

Для приложений, записывающих stacktrace в несколько строк.

```xml
<localfile>
  <location>/var/log/java-app/app.log</location>
  <log_format>multi-line-regex</log_format>
  <multiline_regex>^(\d{4}-\d{2}-\d{2}|\[ERROR\]|Exception:)</multiline_regex>
  <frequency>30</frequency>
  <label key="source">java-app</label>
</localfile>

<localfile>
  <location>/var/log/python-app/errors.log</location>
  <log_format>multi-line-regex</log_format>
  <multiline_regex>^Traceback \(most recent call last\):</multiline_regex>
  <frequency>30</frequency>
  <label key="source">python-errors</label>
</localfile>
```

### 9. Валидация и тестирование конфигурации

Перед включением в production выполните проверку.

```bash
# Проверка синтаксиса ossec.conf
sudo /var/wazuh-manager/bin/wazuh-logtest -t alert -u 001 < /dev/null
# → Expected: "logtest started" без критических ошибок

# Интерактивная проверка локального файла
sudo /var/wazuh-manager/bin/wazuh-logtest
# Вставьте строку лога → проверьте Phase 1 (pre-decoding), Phase 2 (decoding), Phase 3 (rules)

# Проверка статуса wodle
sudo /var/ossec/bin/wazuh-control status | grep -i logcollector
# → Expected: logcollector active

# Тестовое событие: создание файла
echo "Test log entry $(date)" >> /var/log/syslog
sleep 15
# Проверка в alerts.log
sudo grep -i "Test log entry" /var/wazuh-manager/logs/alerts/alerts.log
```

### 10. Развертывание через Ansible

Пример плейбука для массового развертывания конфигурации Logcollector.

```yaml
---
- name: Deploy Wazuh Logcollector Configuration
  hosts: wazuh_agents
  become: yes
  vars:
    logcollector_configs:
      - name: "syslog monitoring"
        location: "/var/log/syslog"
        log_format: "syslog"
        frequency: 10
      - name: "nginx access logs"
        location: "/var/log/nginx/*access*.log"
        log_format: "syslog"
        frequency: 30
  tasks:
    - name: Deploy ossec.conf fragment
      ansible.builtin.copy:
        dest: "/var/ossec/etc/ossec.conf.d/logcollector-{{ item.name }}.xml"
        content: |
          <localfile>
            <location>{{ item.location }}</location>
            <log_format>{{ item.log_format }}</log_format>
            <frequency>{{ item.frequency }}</frequency>
            <only-future-events>yes</only-future-events>
            <label key="source">{{ item.name }}</label>
          </localfile>
        owner: root
        group: wazuh
        mode: '0640'
      loop: "{{ logcollector_configs }}"
      notify: restart wazuh-agent

  handlers:
    - name: restart wazuh-agent
      ansible.builtin.service:
        name: wazuh-agent
        state: restarted
```

### 11. CI/CD пайплайн для конфигурации Logcollector

Пример GitHub Actions workflow для валидации и деплоя.

```yaml
name: Logcollector Config CI/CD

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate XML syntax
        run: xmllint --noout ossec.conf.d/*.xml
      - name: Validate YAML syntax
        run: yamllint wazuh.yaml
      - name: Test logcollector config
        run: |
          docker run --rm -v $PWD:/config wazuh/wazuh-logtest:latest /config/test-logs/
      - name: Deploy to staging
        if: github.ref == 'refs/heads/main'
        run: ansible-playbook -i inventory/staging playbooks/deploy_logcollector.yml
```

### 12. Резервное копирование и восстановление

#### Что бэкапить

| Компонент | Путь | Важность |
| :--- | :--- | :--- |
| ossec.conf | `/var/ossec/etc/ossec.conf` (агент) | Critical |
| ossec.conf (менеджер) | `/var/wazuh-manager/etc/ossec.conf` | High |
| YAML-конфигурации | Через Content Manager API | High |
| Кастомные скрипты | `/var/ossec/custom-scripts/` | Medium |
| Правила | `/var/wazuh-manager/etc/rules/` | Medium |

#### Скрипт бэкапа

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/wazuh-logcollector-$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Агент
tar czf "$BACKUP_DIR/agent-ossec-conf.tar.gz" -C /var/ossec etc/ossec.conf
tar czf "$BACKUP_DIR/custom-scripts.tar.gz" -C /var/ossec custom-scripts/

# Менеджер (если применимо)
tar czf "$BACKUP_DIR/manager-ossec-conf.tar.gz" -C /var wazuh-manager/etc/ossec.conf

# YAML-декодеры через API
curl -sk -u admin:admin https://localhost:55000/content/decoders -o "$BACKUP_DIR/decoders-backup.json"

echo "Backup saved to $BACKUP_DIR"
```

#### Восстановление

```bash
# 1. Остановите агент/менеджер
sudo systemctl stop wazuh-agent

# 2. Восстановите файлы
tar xzf agent-ossec-conf.tar.gz -C /var

# 3. Проверьте права
sudo chown root:wazuh /var/ossec/etc/ossec.conf
sudo chmod 0640 /var/ossec/etc/ossec.conf

# 4. Валидация
sudo /var/wazuh-manager/bin/wazuh-logtest -t alert -u 001 < /dev/null

# 5. Запустите агент
sudo systemctl start wazuh-agent
```

### 13. Мониторинг и телеметрия Logcollector

Для отслеживания здоровья самого процесса сбора добавьте метрики.

```bash
# На агенте: скрипт /var/ossec/custom-scripts/logcollector_health.sh
#!/bin/sh
EVENT_COUNT=$(tail -n 100 /var/ossec/logs/ossec.log | grep -c "logcollector" || true)
ERROR_COUNT=$(tail -n 100 /var/ossec/logs/ossec.log | grep -c "logcollector.*error" || true)
FILE_COUNT=$(find /var/log -type f 2>/dev/null | wc -l)

printf '{"type":"logcollector_health","events":%s,"errors":%s,"files_monitored":%s}\n' \
  "$EVENT_COUNT" "$ERROR_COUNT" "$FILE_COUNT"
```

Конфигурация wodle:
```xml
<wodle name="command">
  <disabled>no</disabled>
  <tag>logcollector_health</tag>
  <command>/var/ossec/custom-scripts/logcollector_health.sh</command>
  <interval>5m</interval>
  <run_on_start>yes</run_on_start>
  <log_format>json</log_format>
</wodle>
```

## Дополнительная информация

### Управление жизненным циклом файлов

*   **`<age>`**: Игнорирование файлов, не обновлявшихся более срока (например, `12h`).
*   **`<ignore>`**: Пропуск строк, соответствующих паттерну (PCRE2).
*   **`<restrict>`**: Обработка ТОЛЬКО строк, соответствующих паттерну.
*   **`<only-future-events>`**: При `yes` (дефолт) агент читает только новые строки. При `no` — считывает весь файл с учетом `max-size`.
*   **`<ignore_binaries>`**: Автоматический пропуск бинарных данных для предотвращения сбоев декодера.
*   **`<max-size>`**: Максимальный размер файла для чтения. Важен при `only-future-events=no` для защиты от гигантских логов.

### Отладка и диагностика
Все события и ошибки Logcollector (права доступа, проблемы с OTLP, ошибки парсинга) фиксируются в:
*   Linux: `/var/wazuh-manager/logs/wazuh.log`
*   Windows: `C:\Program Files (x86)\ossec-agent\ossec.log`

### Performance и масштабирование

*   **Frequency**: Увеличьте `<frequency>` до 30–60s для сред с >10 000 файлами на агенте. Это снижает нагрузку на дисковую подсистему.
*   **Wildcard limit**: В Wazuh 5.0 лимит увеличен до 2000 файлов на блок. При большем количестве разделите на несколько `<localfile>` с разными масками.
*   **max-size**: Всегда устанавливайте `<max-size>` для wildcard-блоков, чтобы предотвратить чтение старых ротированных файлов.
*   **Буферы**: При высоких EPS (>5000) увеличьте `logcollector.entries` в `internal_options.conf`.
*   **Диски**: Используйте SSD/NVMe для хостов с активным Logcollector. HDD вызывает задержки при опросе тысяч файлов.

### Заметки по миграции (4.x → 5.0)

*   **Пути**: В 5.x агент использует `/var/ossec/`, менеджер — `/var/wazuh-manager/`. При развертывании wodle на менеджере (agentless) используйте пути менеджера.
*   **YAML-конфигурация**: В Wazuh 5.x появилась поддержка YAML для Logcollector через Content Manager API. XML (`ossec.conf`) остается рабочим.
*   **ECS-маппинг**: В 5.0 JSON-логи автоматически маппятся в ECS. При миграции проверьте, что имена полей в кастомных декодерах соответствуют WCS.
*   **wazuh-modulesd → integratord**: В 5.x управление wodle и интеграциями централизовано через `integratord`. Для диагностики:
  ```bash
  sudo /var/wazuh-manager/bin/wazuh-control status modules
  # → Expected: logcollector активен
  ```
*   **OTLP**: В 5.0 Logcollector может выступать как OTLP Receiver. При миграции на 5.x добавьте конфигурацию `telemetry` в `wazuh.yaml`, если требуется прямой прием телеметрии от приложений.

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Logcollector не читает файл** | Неправильные права доступа или SELinux блокирует чтение | Проверьте `sudo ls -la /var/log/syslog`, убедитесь что пользователь `wazuh` имеет права на чтение |
| **Нет событий в alerts.log** | `log_format` не совпадает с реальным форматом файла | Проверьте через `wazuh-logtest`, сравните с примерами в разделе форматов |
| **Дублирующиеся алерты** | Файл указан в нескольких `<localfile>` или в `ossec.conf` и `agent.conf` | Проверьте конфигурации на всех уровнях (менеджер, группа, агент) |
| **Высокий CPU на агенте** | Слишком частый `<frequency>` или большое количество wildcard-файлов | Увеличьте `<frequency>` до 30–60s, ограничьте маску wildcard |
| **Потеря логов при ротации** | `only-future-events=yes` и файл был ротирован между опросами | Используйте `only-future-events=no` с `<max-size>` для критичных логов |
| **Логи не маппятся в ECS** | Файл не в формате JSON или декодер не настроен | Убедитесь что `<log_format>json</log_format>` и JSON валиден |
| **Eventchannel не работает** | Windows Event Log не доступен или XPath неверен | Проверьте права на чтение Event Log, тестируйте XPath через `wazuh-logtest` |
| **Ошибка "too many open files"** | Превышен лимит файловых дескрипторов | Увеличьте `ulimit -n` для сервиса `wazuh-agent` (рекомендуется 65536) |

### Best Practices

1.  **Приоритет native форматов**: Используйте `journald` вместо `/var/log/syslog` на systemd-хостах. Это снижает задержки и дает доступ к метаданным (_SYSTEMD_UNIT, _PID).
2.  **Эarly filtering**: Применяйте `<restrict>` и `<ignore>` на уровне Logcollector, а не на уровне декодеров. Это снижает объем передаваемых данных.
3.  **Ограничение wildcard**: Не используйте `/var/log/*.log` на хостах с тысячами файлов. Ограничьте маску директории и объема.
4.  **max-size обязателен**: Всегда устанавливайте `<max-size>` для блоков с `only-future-events=no`, чтобы предотвратить чтение гигантских логов при старте.
5.  **Валидация перед деплоем**: Все изменения конфигурации Logcollector тестируйте через `wazuh-logtest` на эталонных логах перед применением в production.
6.  **Мониторинг самого сбора**: Добавьте health-check wodle (см. сценарий 13) для отслеживания количества собранных событий и ошибок Logcollector.
7.  **Version Control**: Храните конфигурации Logcollector в Git. Для YAML-конфигураций используйте Content Manager API для экспорта/импорта.
8.  **Separation of Concerns**: Разделяйте конфигурации по средам (prod/staging) и сервисам. Используйте `agent.conf` для групповой политики, а не редактируйте `ossec.conf` на каждом агенте вручную.

### Edge Cases и ограничения

*   **Ротация логов при stopped агенте**: Если агент был выключен во время ротации логов, он может пропустить часть строк. Используйте `only-future-events=no` с `<max-size>` для критичных источников.
*   **Симлинки**: Logcollector не преследует симлинки по умолчанию. Указывайте реальные пути к файлам.
*   **Бинарные данные**: Включите `<ignore_binaries>yes</ignore_binaries>` для логов, в которые могут попадать бинарные вставки (например, core dumps).
*   **Сетевые ФС**: Мониторинг NFS/CIFS может быть нестабильным. Для сетевых путей используйте `<interval>` с повышенным `<frequency>` и `only-future-events=yes`.
*   **Journald размер**: `journald` хранит логи в бинарном формате. При огромном объеме используйте `systemd-journal-remote` для отправки на центральный сервер и собирайте уже удаленно.
*   **Windows Eventchannel лимиты**: При фильтрации через XPath избегайте слишком широких запросов — это вызывает высокую нагрузку на Event Log API. Исключайте конкретные EventID, а не используйте IN-списки.

### Резервное копирование и версионирование

| Компонент | Путь | Важность |
| :--- | :--- | :--- |
| ossec.conf (агент) | `/var/ossec/etc/ossec.conf` | Critical |
| ossec.conf (менеджер) | `/var/wazuh-manager/etc/ossec.conf` | High |
| YAML-конфигурации | Экспорт через Content Manager API | High |
| Кастомные скрипты | `/var/ossec/custom-scripts/` | Medium |
| Декодеры | `/var/wazuh-manager/etc/decoders/` или Content Manager | High |

### См. также

- [Декодеры в Wazuh: кастомная настройка](./custom-decoders.md) — YAML-декодеры и PCRE2.
- [Wazuh: обзор SIEM](../wazuh.md)
