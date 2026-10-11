# Samba: SIEM-интеграция и комплаенс

## Определения

**SIEM (Security Information and Event Management)** — система централизованного сбора, нормализации и корреляции событий безопасности. Примеры: Wazuh, ELK Stack (Elasticsearch + Logstash + Kibana), Graylog, Splunk.

**Audit Trail (Аудиторский след)** — последовательность событий, документирующих действия пользователей и систем. Требуется для соответствия стандартам безопасности (PCI DSS, HIPAA, ГОСТ).

**Wazuh** — open-source платформа XDR и SIEM, объединяющая HIDS, мониторинг логов и реагирование на инциденты. Содержит готовые правила для Samba.

**Log Parsing (Парсинг логов)** — процесс преобразования текстовых логов в структурированные данные (JSON) для индексации и анализа в SIEM.

**Correlation Rule (Корреляционное правило)** — правило, связывающее события из разных источников для обнаружения сложных атак (например: брутфорс + неудачный вход + подозрительный IP).

**Compliance (Комплаенс)** — соответствие нормативным требованиям (PCI DSS, HIPAA, ГОСТ Р 57580.1). Для файловых серверов это включает аудит доступа, шифрование, ротацию логов.

**Log Retention (Хранение логов)** — политика хранения логов в соответствии с требованиями. PCI DSS требует минимум 1 год хранения, из них 3 месяца — в доступном виде.

**Sigma Rules** — формат описания правил обнаружения угроз, совместимый с большинством SIEM. Позволяет писать правила один раз и использовать в разных системах.

## Базовые концепции

### Источники событий Samba для SIEM

| Источник | Тип событий | Формат | Приоритет |
| :--- | :--- | :--- | :--- |
| **smbd** | Аутентификация, доступ к файлам | Text/JSON | Высокий |
| **winbindd** | Маппинг SID/UID, Kerberos | Text | Средний |
| **VFS full_audit** | Операции CRUD, удаление, изменение прав | Text | Критичный |
| **journalctl** | Ошибки сервисов | Structured | Средний |
| **audit.log** | Аудит операций (syslog) | Text/JSON | Высокий |

### Нормализация событий

Samba логи не являются JSON по умолчанию. Для SIEM требуется нормализация:

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `timestamp` | Время события | `2026-09-15T10:30:00Z` |
| `src_ip` | IP клиента | `192.168.1.100` |
| `username` | Имя пользователя | `DOMAIN\user` |
| `share` | Имя шары | `data` |
| `operation` | Тип операции | `open`, `close`, `unlink` |
| `status` | Результат | `OK`, `ACCESS_DENIED` |
| `file_path` | Путь к файлу | `/srv/samba/data/file.txt` |

### Требования стандартов

| Стандарт | Требования для Samba |
| :--- | :--- |
| **PCI DSS** | Аудит доступа, ротация логов, шифрование трафика |
| **HIPAA** | Контроль доступа к PHI, аудит изменений |
| **ГОСТ Р 57580.1** | Аудит операций, хранение логов ≥ 1 год |
| **SOC 2** | Мониторинг доступа, реагирование на инциденты |

## Практические сценарии

### 1. Настройка аудита через VFS full_audit

```ini
# /etc/samba/smb.conf
[global]
   #Syslog для аудита
   syslog only = yes
   syslog = 0

[AuditShare]
   path = /srv/samba/audit
   vfs objects = full_audit
   full_audit:prefix = %u|%I|%m|%S|%t
   full_audit:success = open create close read write rename unlink chmod chown mkdir rmdir
   full_audit:failure = connect disconnect
   full_audit:facility = LOCAL7
   full_audit:priority = NOTICE
   full_audit:log loglevel = 1
```

### 2. Настройка rsyslog для аудита Samba

```bash
# /etc/rsyslog.d/30-samba-audit.conf
# Аудит Samba в отдельный файл
if $programname == 'smbd_audit' then /var/log/samba/audit.log
& stop

# Критические ошибки в отдельный файл
if $programname == 'smbd' and $syslogseverity <= 3 then /var/log/samba/security.log
& stop
```

```bash
sudo systemctl restart rsyslog
```

### 3. Парсинг логов для Wazuh (JSON)

```python
#!/usr/bin/env python3
"""
/usr/local/bin/samba_log_parser.py
Преобразует текстовые логи Samba в JSON для Wazuh.
"""
import re
import json
import sys
from datetime import datetime

LOG_PATTERN = re.compile(
    r'(?P<user>\w+) (?P<ip>[\d.]+) (?P<share>\w+) (?P<time>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) (?P<operation>\w+)(?: (?P<result>\w+))?'
)

def parse_line(line):
    match = LOG_PATTERN.match(line.strip())
    if not match:
        return None

    data = match.groupdict()
    return {
        "timestamp": datetime.strptime(data['time'], '%Y/%m/%d %H:%M:%S').isoformat(),
        "src_ip": data['ip'],
        "username": data['user'],
        "share": data['share'],
        "operation": data['operation'],
        "status": data.get('result', 'OK'),
        "log_source": "samba_audit",
        "service": "smbd"
    }

if __name__ == '__main__':
    for line in sys.stdin:
        event = parse_line(line)
        if event:
            print(json.dumps(event))
```

### 4. Интеграция с Wazuh

```yaml
# /var/ossec/etc/rules/local_rules.xml (Wazuh)
<group name="samba,">
  <!-- Брутфорс Samba -->
  <rule id="100100" level="10">
    <if_sid>18101</if_sid>
    <field name="program_name">smbd</field>
    <description>Samba brute force attempt detected</description>
    <group>authentication_failures,pci_dss_10.2.4,</group>
  </rule>

  <!-- Доступ к чувствительным шарам -->
  <rule id="100101" level="8">
    <field name="program_name">smbd_audit</field>
    <field name="operation">unlink|chmod|chown</field>
    <description>Sensitive file operation on Samba share</description>
    <group>file_integrity,pci_dss_11.5,</group>
  </rule>

  <!-- Неудачная аутентификация -->
  <rule id="100102" level="5">
    <if_sid>18101</if_sid>
    <field name="program_name">smbd</field>
    <match>NT_STATUS_LOGON_FAILURE</match>
    <description>Failed Samba login attempt</description>
    <group>authentication_failures,</group>
  </rule>
</group>
```

### 5. Сбор логов через Filebeat → Logstash → Elasticsearch

```yaml
# /etc/filebeat/inputs.d/samba.yml
- type: log
  enabled: true
  paths:
    - /var/log/samba/audit.log
  fields:
    log_type: samba_audit
  fields_under_root: true
  multiline.pattern: '^\d{4}/\d{2}/\d{2}'
  multiline.negate: true
  multiline.match: after
```

```ruby
# /etc/logstash/conf.d/samba.conf
input {
  beats {
    port => 5044
  }
}

filter {
  if [log_type] == "samba_audit" {
    grok {
      match => {
        "message" => '%{USER:user} %{IP:src_ip} %{WORD:share} %{TIMESTAMP_ISO8601:timestamp} %{WORD:operation}(?: %{WORD:status})?'
      }
    }

    date {
      match => ["timestamp", "yyyy/MM/dd HH:mm:ss"]
      target => "@timestamp"
    }

    mutate {
      add_field => {
        "service" => "samba"
        "environment" => "production"
      }
    }
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "samba-audit-%{{yyyy.MM.dd}}"
  }
}
```

### 6. Sigma-правила для Samba

```yaml
# samba_bruteforce.yml
title: Samba Brute Force
id: 100100
status: experimental
description: Обнаружение брутфорс-атаки на Samba
references:
  - https://www.samba.org/samba/docs/
logsource:
  product: samba
  service: smbd
detection:
  selection:
    event_id: 'NT_STATUS_LOGON_FAILURE'
  condition: selection
  timeframe: 5m
  count(username) by src_ip > 5
level: high
tags:
  - attack.credential_access
  - attack.t1110
  - pci_dss.10.2.4
```

```yaml
# samba_sensitive_file_access.yml
title: Sensitive File Access on Samba
id: 100101
status: experimental
description: Доступ к конфиденциальным файлам
logsource:
  product: samba
  service: smbd
detection:
  selection:
    operation:
      - unlink
      - chmod
      - chown
  filter:
    share:
      - 'admin*'
      - 'confidential*'
  condition: selection and filter
level: medium
tags:
  - attack.credential_access
  - attack.t1003
```

### 7. Алертинг в ELK (ElastAlert)

```yaml
# /etc/elastalert/rules/samba_bruteforce.yaml
name: "Samba Brute Force"
type: frequency
index: "samba-audit-*"
num_events: 5
timeframe:
  minutes: 5
query_key: "src_ip"
filter:
  - query:
      query_string:
        query: "operation: 'logon' AND status: 'ACCESS_DENIED'"
alert:
  - "telegram"
telegram_bot_token: "YOUR_TOKEN"
telegram_chat_id: "-1001234567890"
alert_text: "Samba brute force from {0}"
alert_text_args:
  - src_ip
```

### 8. Централизованное логирование через syslog-ng

```bash
# /etc/syslog-ng/conf.d/samba.conf
destination d_samba_audit {
    file("/var/log/samba/audit.log"
        template("${ISODATE} ${HOST} ${PROGRAM}[${PID}]: ${MSG}\n")
        create_dirs(yes)
    );
};

destination d_siem {
    network("siem.example.com" port(514)
        transport("tcp")
        template("$(format-json --key *.*)\n")
    );
};

source s_samba {
    file("/var/log/samba/audit.log");
};

log {
    source(s_samba);
    destination(d_samba_audit);
    destination(d_siem);
};
```

### 9. Политика ротации логов

```bash
# /etc/logrotate.d/samba
/var/log/samba/*.log {
    daily
    rotate 365
    compress
    delaycompress
    missingok
    notifempty
    create 640 root adm
    sharedscripts
    postrotate
        /usr/bin/systemctl reload smbd > /dev/null 2>&1 || true
    endscript
}

/var/log/samba/audit.log {
    daily
    rotate 365
    compress
    delaycompress
    missingok
    notifempty
    create 640 root adm
    # PCI DSS: хранить минимум 1 год
}
```

### 10. Поиск в SIEM (примеры запросов)

**Wazuh (Kibana):**
```
# Брутфорс за последние 5 минут
rule.id: 100100 AND timestamp: [now-5m TO now]

# Операции с файлами на определенной шаре
data.share: "confidential" AND data.operation: (unlink OR chmod)

# Неудачные входы с определенного IP
data.src_ip: "192.168.1.100" AND data.status: "ACCESS_DENIED"
```

**Elasticsearch (KQL):**
```kql
# Все аудит-события за час
service: "samba" AND @timestamp >= now-1h

# Удаление файлов
operation: "unlink" AND share: "admin*"

# Брутфорс
event_type: "authentication" AND outcome: "failure" AND src_ip: *
```

## Мониторинг и диагностика

### Проверка работы аудита

```bash
# Проверка наличия записей в audit.log
tail -f /var/log/samba/audit.log

# Проверка формата логов
head -5 /var/log/samba/audit.log
# → user1 192.168.1.10 data 2026/09/15 10:30:00 open OK

# Проверка интеграции с rsyslog
logger -t smbd_audit "test user 192.168.1.1 test 2026/09/15 10:00:00 open OK"
```

### Диагностика SIEM-интеграции

```bash
# Проверка доставки в Wazuh
/var/ossec/bin/agent_control -r -a

# Проверка Elasticsearch
curl -s "localhost:9200/samba-audit-*/_count?pretty"

# Проверка Logstash
journalctl -u logstash -f | grep samba
```

## Типовые ошибки SIEM-интеграции

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Логи не парсятся | Неверный grok-паттерн | Проверьте формат логов |
| Дубли событий | Несколько collectors | Проверьте filebeat/syslog-ng |
| Пропущенные события | Фильтр в SIEM | Проверьте query |
| Высокая нагрузка | Слишком детальный audit | Уменьшите `full_audit:success` |

## Дополнительная информация

- [Безопасность и VFS](./samba_security.md) — настройка аудита.
- [Устранение неполадок](./samba_troubleshooting.md) — анализ логов.

## См. также

- [Wazuh: Обзор](../../../../Security/Tools/wazuh.md) — платформа SIEM.
- [ELK Stack](../../../../ELK_Stack/elk_stack_overview.md) — стек для логов.
- [Syslog: Настройка](../../../../Networking/Protocols/syslog.md) — сбор логов.
- [Auditd: Аудит системы](../../../../Linux/SystemAdministration/Logging/auditd.md) — аудит Linux.
