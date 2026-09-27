# Логирование в среде KVM: journald, rsyslog, централизованный сбор

Данный файл описывает настройку логирования для KVM-хостов и гостевых ВМ: системный journal (journald), пересылку логов (rsyslog/syslog-ng), централизованный сбор (Loki, ELK) и ротацию логов. Мониторинг метрик описан в [Мониторинг KVM](./kvm_monitoring.md).

## Определения

**systemd-journald** — системный демон логирования в Linux, собирающий логи из всех источников (ядра, systemd-юнитов, stdout/stderr процессов) в структурированном бинарном формате (journal). Хранит логи в `/var/log/journal/` (персистентный) или в `/run/log/journal/` (volatile).

**Persistent Journal** — режим journald, при котором логи сохраняются на диске между перезагрузками. Требует наличия директории `/var/log/journal/` и достаточного дискового пространства.

**Remote Logging** — пересылка логов с одного хоста на удалённый syslog-сервер для централизованного хранения и анализа.

**Log Rotation (Ротация логов)** — процесс удаления или сжатия старых лог-файлов для предотвращения заполнения диска. В journald реализована через параметры `SystemMaxUse`, `MaxRetentionSec`.

**rsyslog** — расширяемый системный демон логирования, поддерживающий пересылку по TCP/UDP, фильтрацию по шаблонам и интеграцию с удалёнными серверами.

**syslog-ng** — альтернатива rsyslog с расширенными возможностями корреляции,.destination-ами и обработкой событий.

**Structured Logging** — формат логов, при котором каждое сообщение содержит ключ-значение поля (PID, unit, priority, timestamp), что облегчает фильтрацию и поиск.

## Базовые концепции

### Архитектура логирования в KVM

```
┌─────────────────────────────────────────────────────┐
│  KVM Host                                           │
│  ├── journald (system)                              │
│  │   ├── ядро (dmesg)                               │
│  │   ├── libvirtd / qemu / virtlogd                  │
│  │   └── systemd-юниты                              │
│  ├── rsyslog/syslog-ng (опционально)                │
│  │   └── пересылка на syslog-сервер                  │
│  └── Гостевые ВМ (через qemu-guest-agent)           │
│      └── journald внутри ВМ                         │
└─────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────┐
│  Централизованное хранилище логов                   │
│  ├── Loki (для Prometheus/Grafana)                  │
│  ├── ELK Stack (Elasticsearch + Logstash + Kibana)  │
│  └── Syslog-сервер (rsyslog/syslog-ng)              │
└─────────────────────────────────────────────────────┘
```

### Настройка journald

**Конфигурация (`/etc/systemd/journald.conf`):**
```ini
[Journal]
# Хранение на диске (persistent)
Storage=persistent

# Максимальный размер логов
SystemMaxUse=500M
SystemMaxFileSize=50M

# Максимальное время хранения
MaxRetentionSec=30day

# Сжатие
Compress=yes

# Синхронизация при записи
RateLimitIntervalSec=30s
RateLimitBurst=10000

# Forwarding в sys侬 (если используется)
ForwardToSyslog=yes
```

**Применение:**
```bash
sudo systemctl restart systemd-journald

# Проверка размера journal
journalctl --disk-usage
# → Archived and active journals take up 256.0M in the file system.
```

### Чтение логов через journalctl

```bash
# Логи конкретного сервиса
journalctl -u libvirtd --since "1 hour ago"
journalctl -u qemu-guest-agent --since "today"

# Логи ядра (dmesg)
journalctl -k
journalctl -k --since "2026-09-17 12:00:00"

# Логи конкретной ВМ (через unit name)
journalctl -u "libvirt-qemu\\x2dweb-server-01"

# Фильтрация по приоритету
journalctl -p err   # Только ошибки
journalctl -p warning  # Предупреждения и выше

# Непрерывный мониторинг
journalctl -f -u libvirtd

# Вывод в JSON
journalctl -u libvirtd -o json-pretty

# Просмотр последних 100 строк
journalctl -u libvirtd -n 100
```

### Настройка rsyslog для пересылки

**На KVM-хосте (отправитель):**
```bash
# /etc/rsyslog.d/remote.conf
# Пересылка всех логов level>info на удалённый сервер
*.* @@192.168.1.50:514    # TCP
# *.* @192.168.1.50:514     # UDP

# Или фильтрованная пересылка
:programname, isequal, "libvirtd" @@192.168.1.50:514
:programname, isequal, "qemu-system" @@192.168.1.50:514
```

**На syslog-сервере (получатель):**
```bash
# /etc/rsyslog.d/remote.conf
# Приём TCP-соединений
module(load="imtcp")
input(type="imtcp" port="514")

# Сохранение в файлы по хостам
template(name="RemoteLog" type="string"
  string="/var/log/remote/%HOSTNAME%/%PROGRAMNAME%.log")

if $fromhost-ip != '127.0.0.1' then {
  action(type="omfile" dynaFile="RemoteLog")
  stop
}
```

### Централизованное логирование через Loki

**Установка Promtail на KVM-хосте:**
```yaml
# /etc/promtail/config.yml
server:
  http_listen_port: 9080

positions:
  filename: /var/lib/promtail/positions.yaml

clients:
  - url: http://loki-server:3100/loki/api/v1/push

scrape_configs:
  - job_name: journald
    journal:
      max_age: 12h
      labels:
        job: kvm-host
        host: kvm-host-01
    relabel_configs:
      - source_labels: ['__journal__systemd_unit']
        target_label: 'unit'
      - source_labels: ['__journal__hostname']
        target_label: 'hostname'

  - job_name: libvirtd
    static_configs:
      - targets:
          - localhost
        labels:
          job: libvirtd
          host: kvm-host-01
          __path__: /var/log/libvirt/*.log
```

**Запуск Promtail:**
```bash
sudo systemctl enable --now promtail
```

### Настройка логов libvirt

Libvirt хранит логи qemu в `/var/log/libvirt/qemu/`:

```bash
# Просмотр логов ВМ
tail -f /var/log/libvirt/qemu/web-server-01.log

# Логи virtlogd (демон логирования QEMU)
journalctl -u virtlogd

# Настройка level логирования QEMU
# В XML-конфигурации ВМ:
# <domain type='kvm'>
#   <devices>
#     <serial type='pty'>
#       <target port='0'/>
#     </serial>
#     <console type='pty'>
#       <target type='serial' port='0'/>
#     </console>
#   </devices>
# </domain>
```

### Ротация логов

**Через logrotate:**
```bash
# /etc/logrotate.d/libvirt
/var/log/libvirt/qemu/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 root root
    sharedscripts
    postrotate
        systemctl reload rsyslog > /dev/null 2>&1 || true
    endscript
}
```

**Через journald (автоматически):**
```bash
# Проверка текущих лимитов
journalctl --disk-usage
# → 256M

# Принудительная очистка старых логов
journalctl --vacuum-time=7d
journalctl --vacuum-size=100M
```

## Практические сценарии

### Сценарий 1: Настройка journald с persistent storage

```bash
# Создание директории для persistent journal
sudo mkdir -p /var/log/journal

# Настройка размера
cat <<EOF | sudo tee /etc/systemd/journald.conf.d/size.conf
[Journal]
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=60day
Compress=yes
EOF

# Перезапуск
sudo systemctl restart systemd-journald

# Проверка
journalctl --disk-usage
ls -la /var/log/journal/
```

### Сценарий 2: Мониторинг логов KVM в реальном времени

```bash
# Мониторинг всех событий KVM
journalctl -f -u libvirtd -u virtlogd -u qemu-guest-agent

# Мониторинг ошибок
journalctl -p err -f --no-pager

# Мониторинг конкретной ВМ
VM_NAME="web-server-01"
journalctl -f | grep -i "$VM_NAME"

# Логи ядра (для диагностики KVM)
journalctl -k -f | grep -iE "kvm|kvm_intel|kvm_amd|vfio"
```

### Сценарий 3: Настройка rsyslog для отправки в Loki

```bash
# Установка rsyslog с поддержкой OMHTTP
sudo apt install -y rsyslog rsyslog-mmexternal

# Конфигурация для отправки в Loki через HTTP
cat <<'EOF' | sudo tee /etc/rsyslog.d/loki.conf
module(load="mmexternal")
module(load="imuxsock")

template(name="loki-format" type="string"
  string="{\"streams\":[{\"stream\":{\"job\":\"kvm-host\",\"hostname\":\"%HOSTNAME%\"},\"values\":[[%TIMESTAMP:::date-rfc3339%,\"%msg%\"]]}]}")

action(type="mmexternal"
  binary="/usr/local/bin/rsyslog-to-loki"
  template="loki-format")
EOF
```

### Сценарий 4: Аудит изменений конфигурации ВМ

```bash
# Мониторинг изменений XML-конфигурации ВМ
journalctl -u libvirtd | grep -i "xml\|config\|define\|undefine"

# Аудит через auditd
sudo auditctl -w /etc/libvirt/qemu/ -p wa -k vm-config-change
sudo ausearch -k vm-config-change --start today
```

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **journalctl пустой** | Storage=volatile (по умолчанию) | Установить `Storage=persistent` в journald.conf |
| **Логи заполняют диск** | Нет ротации | Настроить `SystemMaxUse` или logrotate |
| **rsyslog не пересылает** | Порт 514 закрыт firewall | Открыть TCP/UDP 514 |
| **Loki не получает логи** | Promtail не запущен | `systemctl status promtail` |
| **Логи ВМ не видны** | virtlogd не работает | `systemctl status virtlogd` |

## Дополнительная информация

- [Мониторинг KVM](./kvm_monitoring.md) — Prometheus, Grafana, kvm_stat.
- [Подкаст KVM](./kvm_ha.md) — Pacemaker, DRBD.
- [Loki: официальная документация](https://grafana.com/docs/loki/) — архитектура, Promtail, LogQL.
- [Podman: логирование](../../Podman/podman_logging.md) — journald driver, dual logging.
- [Vector: обзор](../../Vector/vector_overview.md) — альтернатива Promtail для сбора логов.
