# Linux-администрирование для CI/CD-узлов

## Определения

- **Systemd unit** — файл описания службы/таймера в `/etc/systemd/system` (см. [Управление службами](../../Linux/Core/systemd/service_management.md)).
- **Journald** — системный журнал systemd (см. [journald](../../Linux/SystemAdministration/Logging/journald.md)).
- **cgroups** — механизм изоляции и лимитов ресурсов (CPU/память/IO) для процессов (см. [cgroups](../../Linux/Core/cgroups.md)).
- **ulimit / sysctl** — ограничения на дескрипторы, память, сеть на уровне оболочки и ядра.
- **LVM / файловая система** — управление томами и монтирование (иноды, noatime).
- **OOM (Out-Of-Memory)** — исчерпание памяти; OOM-killer завершает процессы (см. [Управление swap](../../Linux/Core/memory/swap_management.md)).
- **DNS / resolv** — разрешение имён; сбои проявляются как таймауты реестра/прокси.

## Основные концепции

### Systemd для раннеров и реестра

Раннеры, реестры, прокси запускаются как systemd-юниты: автозапуск, перезапуск при падении (`Restart=on-failure`), изоляция через `User=`, лимиты через `[Service]` директивы. Периодические задачи (очистка реестра, синхронизация) — через `timers` вместо cron. Структура юнита — в [Unit file structure](../../Linux/Core/systemd/systemd_unit_file_structure.md).

### Лимиты ресурсов под нагрузку

Высоконагруженные раннеры упираются в дефолтные лимиты: малое число открытых файлов (`nofile`), нехватка PID, переполнение сетевых портов. Решение — `ulimit -n` в юните и `sysctl` (`fs.file-max`, `net.core.somaxconn`, `vm.max_map_count`). Изоляция по памяти/CPU — через cgroups в юните (`MemoryMax=`, `CPUQuota=`).

### Диски и иноды для реестра/артeфактов

Реестр образов активно пишет слои: нехватка места или **инод** (тысячи мелких файлов) ломает пайплайн даже при свободном месте. Рекомендации: отдельный том, опции `noatime`, мониторинг `df -i`, своевременный GC реестра (см. [Обслуживание в изолированных средах](./air_gapped_environments.md)).

### Сеть: DNS, MTU, прокси, бастион

Раннеры в закрытом контуре ходят через прокси/бастион. Типичные сбои: не резолвится `registry.internal` (DNS), большой MTU рвёт пакеты через туннель, нет маршрута до прокси. База — в [Маршрутизации](../../Linux/SystemAdministration/routing.md) и [SSH-туннелях](./ci_cd_security_hardening.md).

### Память и OOM

Под давлением параллельных джоб память заканчивается → OOM-killer убивает реестр или раннер. Настройка swap и политики OOM (`oom_score_adj`) — в [Управлении памятью](../../Linux/Core/memory/performance_tuning.md).

### Логи и аудит

Все события раннеров/реестра — в journald; пересылка в центральное хранилище через `rsyslog`/`Vector`. Аудит действий (кто запустил деплой) — через `auditd`.

## Практические сценарии

### Сценарий 1: Systemd unit для gitlab-runner

```systemd
# /etc/systemd/system/gitlab-runner.service
[Unit]
Description=GitLab Runner
After=network.target

[Service]
User=gitlab-runner
ExecStart=/usr/bin/gitlab-runner run
Restart=on-failure
RestartSec=5
# Лимиты ресурсов через cgroups
MemoryMax=4G
CPUQuota=200%
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

### Сценарий 2: sysctl/ulimit для высокой нагрузки

```bash
# /etc/sysctl.d/99-ci.conf
fs.file-max = 2097152
net.core.somaxconn = 4096
vm.max_map_count = 262144
net.ipv4.tcp_tw_reuse = 1
# применить: sysctl --system
```

### Сценарий 3: Диск реестра (опции монтирования)

```bash
# /etc/fstab — отдельный том под /var/lib/registry
/dev/sdb1  /var/lib/registry  ext4  defaults,noatime,discard  0 2
# Мониторинг инод:
df -i /var/lib/registry
```

### Сценарий 4: nftables + SSH на бастионе

```bash
# Только прыжковый хост виден; раннеры недоступны извне
nft add rule inet filter input tcp dport 22 ip saddr 10.0.0.0/24 accept
nft add rule inet filter input drop
# Доступ к узлам через ProxyJump (см. SSH hardening)
```

## Дополнительная информация

### Типичные ошибки

- **Дефолтные лимиты FD** — при 100+ параллельных джоб раннер падает с `too many open files`.
- **Переполнение инод** реестра — свободное место есть, но запись невозможна.
- **OOM-killer убивает реестр** — нет `MemoryMax` и swap-политики.
- **DNS не резолвится в контуре** — раннеры «висят» на таймаутах pull/push.

### См. также

- [Изолированные среды](./air_gapped_environments.md) — прокси, бастион, очистка реестра.
- [Усиление безопасности CI/CD](./ci_cd_security_hardening.md) — SSH/firewall для узлов.
- [Управление службами systemd](../../Linux/Core/systemd/service_management.md) — команды и юниты.
