# Linux-администрирование для CI/CD-узлов

## Определения

- **Systemd unit** — файл описания службы/таймера в `/etc/systemd/system` (см. [Управление службами](../../Linux/Core/systemd/service_management.md)).
- **Timer** — systemd-юнит для периодических задач; заменяет cron с поддержкой точного времени,ournald-логов и зависимостей.
- **Journald** — системный журнал systemd (см. [journald](../../Linux/SystemAdministration/Logging/journald.md)).
- **cgroups** — механизм изоляции и лимитов ресурсов (CPU/память/IO) для процессов (см. [cgroups](../../Linux/Core/cgroups.md)).
- **ulimit / sysctl** — ограничения на дескрипторы, память, сеть на уровне оболочки и ядра.
- **LVM / файловая система** — управление томами и монтирование (иноды, noatime).
- **OOM (Out-Of-Memory)** — исчерпание памяти; OOM-killer завершает процессы (см. [Управление swap](../../Linux/Core/memory/swap_management.md)).
- **DNS / resolv** — разрешение имён; сбои проявляются как таймауты реестра/прокси.
- **Rsyslog / Vector** — агенты пересылки логов из journald в центральное хранилище.
- **Auditd** — демон аудита Linux, фиксирующий системные вызовы и действия пользователей (кто запустил деплой, изменил конфиг).
- **nftables / iptables** — файрволы на уровне ядра; минимальный набор правил на реестре/бастионе.
- **Bastion (прыжковый хост)** — промежуточный сервер с контролируемым доступом к контуру; только он виден извне.
- **Registry** — OCI-реестр артефактов (Harbor, Nexus, Distribution); требует отдельного тома и мониторинга инодов.
- **Runner / Agent** — исполнитель пайплайна (GitLab Runner, Jenkins agent); запускается как systemd-юнит с лимитами.

## Основные концепции

### Systemd для раннеров, реестра и прокси

Все долгоживущие компоненты CI/CD-узлов (раннеры, реестры, прокси) запускаются как systemd-юниты:
- `Restart=on-failure` — автоматический перезапуск при падении.
- `User=` — изоляция от root.
- `LimitNOFILE=`, `MemoryMax=`, `CPUQuota=` — лимиты через cgroups.
- Периодические задачи (очистка реестра, синхронизация) — через `timers` вместо cron.

Структура юнита — в [Unit file structure](../../Linux/Core/systemd/systemd_unit_file_structure.md).

### Лимиты ресурсов под нагрузку

Высоконагруженные раннеры упираются в дефолтные лимиты:
- **Дескрипторы:** малое `nofile` → `Too many open files` при 100+ параллельных джоб.
- **PID:** нехватка PID для процессов.
- **Сеть:** переполнение очереди listen() → `somaxconn`.
- **Память/CPU:** изоляция через cgroups (`MemoryMax=`, `CPUQuota=`).

Решение — `ulimit -n` в юните и `sysctl` (`fs.file-max`, `net.core.somaxconn`, `vm.max_map_count`).

### Диски и иноды для реестра/артефактов

Реестр образов активно пишет слои: нехватка места или **инод** (тысячи мелких файлов) ломает пайплайн даже при свободном месте. Рекомендации: отдельный том, опции `noatime`, мониторинг `df -i`, своевременный GC реестра (см. [Обслуживание в изолированных средах](./air_gapped_environments.md)).

### Сеть: DNS, MTU, прокси, бастион

Раннеры в закрытом контуре ходят через прокси/бастион. Типичные сбои: не резолвится `registry.internal` (DNS), большой MTU рвёт пакеты через туннель, нет маршрута до прокси. База — в [Маршрутизации](../../Linux/SystemAdministration/routing.md) и [SSH-туннелях](./ci_cd_security_hardening.md).

На бастионе/реестре — минимальный набор правил (nftables/iptables): только нужные порты с нужных адресов (см. [Усиление безопасности CI/CD](./ci_cd_security_hardening.md)).

### Память и OOM

Под давлением параллельных джоб память заканчивается → OOM-killer убивает реестр или раннер. Настройка swap и политики OOM (`oom_score_adj`) — в [Управлении памятью](../../Linux/Core/memory/swap_management.md).

### Логи и аудит

Все события раннеров/реестра — в journald; пересылка в центральное хранилище через `rsyslog`/`Vector`. Аудит действий (кто запустил деплой) — через `auditd`.

### Роли и зоны ответственности

| Аспект | DevOps | SRE | Sysadmin |
| :--- | :--- | :--- | :--- |
| **Детекция** | Настройка алертов в пайплайне, связь DORA-метрик с инцидентами | Проектирование SLO/SLI, burn rate алерты, настройка Alertmanager | Мониторинг железа/сети/дисков, uptime sensor, watchdog |
| **Triage** | Оценка влияния на пайплайн и деплой | Оценка SEV по SLO/Error Budget, назначение IC | Оценка инфраструктурного влияния (диск, сеть, питание) |
| **Mitigation** | Откат деплоя, feature flag, canary pause | Автономный откат по SLO, judge engine, circuit breaker | Graceful shutdown, drain нод, переключение VIP/HAProxy |
| **Investigation** | Логи пайплайна, артефакты, Git history | Трассировка, Golden Signals, burn rate анализ | journald, syslog, сетевые дампы, tcpdump |
| **Postmortem** | Action items по пайплайну, SBOM, provenance | RCA, 5 почему, безвиновный разбор, action items | Action items по инфраструктуре (железо, сеть, бэкапы) |
| **Prevention** | Quality Gates, SAST/SCA, иммутабельные артефакты | Chaos Engineering, SLO-бюджет, автономная доставка | Золотой образ, Packer, immutable infrastructure |

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

**Валидация:** `systemctl daemon-reload && systemctl enable --now gitlab-runner && systemctl status gitlab-runner`

### Сценарий 2: sysctl/ulimit для высокой нагрузки

```bash
# /etc/sysctl.d/99-ci.conf
fs.file-max = 2097152
net.core.somaxconn = 4096
vm.max_map_count = 262144
net.ipv4.tcp_tw_reuse = 1
# применить: sysctl --system
```

**Валидация:** `sysctl -p /etc/sysctl.d/99-ci.conf && sysctl fs.file-max net.core.somaxconn`

### Сценарий 3: Диск реестра (опции монтирования)

```bash
# /etc/fstab — отдельный том под /var/lib/registry
/dev/sdb1  /var/lib/registry  ext4  defaults,noatime,discard  0 2
# Мониторинг инод:
df -i /var/lib/registry
```

**Валидация:** `mount -a && df -h /var/lib/registry && df -i /var/lib/registry`

### Сценарий 4: nftables + SSH на бастионе

```bash
# Только прыжковый хост виден; раннеры недоступны извне
nft add table inet filter
nft add rule inet filter input tcp dport 22 ip saddr 10.0.0.0/24 accept
nft add rule inet filter input tcp dport 443 accept
nft add rule inet filter input drop
# Доступ к узлам через ProxyJump (см. SSH hardening)
```

**Валидация:** `nft list ruleset && ssh -J bastion.internal runner-node01`

### Сценарий 5: Очистка реестра и артефактов

```bash
# Очистка неиспользуемых слоев и кеша
docker system prune -a -f
# → Total reclaimed space: 45.2GB

# Проверка инодов
df -i /var/lib/registry
# → Filesystem      Inodes  IUsed  IFree IUse% Mounted on
# → /dev/sdb1      1.3M    800K    500K   62% /var/lib/registry
```

**Валидация:** `docker system df && df -h /var/lib/registry`

### Сценарий 6: systemd-timer для регулярного GC реестра

```ini
# /etc/systemd/system/registry-gc.service
[Unit]
Description=Registry Garbage Collection
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/registry-gc.sh
```

```ini
# /etc/systemd/system/registry-gc.timer
[Unit]
Description=Daily registry GC at 03:00

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Активация таймера
systemctl daemon-reload
systemctl enable --now registry-gc.timer
# → Created symlink /etc/systemd/system/timers.target.wants/registry-gc.timer
```

**Валидация:** `systemctl list-timers registry-gc.timer && journalctl -u registry-gc.service`

### Сценарий 7: Аудит действий через auditd

```bash
# Правило: логировать все exec() в раннере
echo '-w /usr/bin/gitlab-runner -p x -k runner_exec' >> /etc/audit/rules.d/ci.rules
echo '-w /etc/systemd/system/gitlab-runner.service -p wa -k runner_config' >> /etc/audit/rules.d/ci.rules

# Применить правила
augenrules --load
# → No rules found to skip

# Поиск событий
ausearch -k runner_exec --start recent
# → time->Sun Sep 27 10:00:00 2026
# → type=EXECVE msg=audit(1727455200.123:456): argc=3 a0="gitlab-runner" a1="run" a2="--config"
```

**Валидация:** `auditctl -l && ausearch -k runner_exec -i | tail -20`

### Сценарий 8: Переключение на fallback registry

```bash
# Проверка доступности registry
curl -sSL https://registry.internal/v2/_catalog
# → {"repositories":[...]} или ошибка соединения

# Переключение на fallback registry
export CI_REGISTRY=fallback-registry.internal
```

**Валидация:** `curl -sSL $CI_REGISTRY/v2/_catalog | jq '.repositories | length'`

## Операции и команды

### Systemd — управление юнитами

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `systemctl daemon-reload` | Перечитать конфигурацию юнитов | `# →` (выход 0) |
| `systemctl enable --now gitlab-runner` | Включить автозапуск и запустить | `# → Created symlink /etc/systemd/system/multi-user.target.wants/gitlab-runner.service` |
| `systemctl status gitlab-runner` | Проверить статус и последние логи | `Active: active (running) since Sun 2026-09-27 08:00:00 UTC; 3h ago` |
| `systemctl show gitlab-runner -p LimitNOFILE,LimitNPROC,MemoryMax` | Проверить лимиты юнита | `LimitNOFILE=65536` |
| `systemctl list-timers` | Показать все активные таймеры | строка с `registry-gc.timer` и временем следующего запуска |
| `journalctl -u gitlab-runner --since "1 hour ago" -p err` | Ошибки юнита за последний час | список ERROR/WARNING записей с таймстемпами |

### Ресурсы — ulimit, sysctl, cgroups

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `ulimit -n` | Текущий лимит открытых файлов в shell | `65536` |
| `cat /proc/sys/fs/file-max` | Глобальный лимит файловых дескрипторов | `2097152` |
| `cat /proc/sys/net/core/somaxconn` | Глобальный лимит очереди listen() | `4096` |
| `cat /proc/sys/vm/max_map_count` | Лимит mmap-регионов | `262144` |
| `cat /sys/fs/cgroup/cpu.max` | Лимит CPU в cgroup v2 | `200000 100000` |
| `cat /sys/fs/cgroup/memory.max` | Лимит памяти в cgroup v2 | `4294967296` (4G) |
| `systemctl show gitlab-runner -p CPUQuota` | CPU квота systemd-юнита | `CPUQuota=200%` |
| `ss -s` | Сводка по сокетам: `inestab`, `mem` | `TCP: 1234 (estab 567, closed 123, orphaned 45, ...)` |

### Диски и иноды

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `df -h /var/lib/registry` | Свободное место на томе реестра | `Filesystem      Size  Used Avail Use% Mounted on` |
| `df -i /var/lib/registry` | Свободные иноды на томе реестра | `Inodes  IUsed  IFree IUse%` |
| `du -sh /var/lib/registry/* | sort -rh | head -10` | Топ-10 самых больших директорий реестра | `4.5G    /var/lib/registry/docker/registry/v2/blobs` |
| `docker system df` | Использование места Docker (образы, кеш, контейнеры) | `TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE` |
| `docker system prune -a -f` | Очистка неиспользуемых слоев и образов | `Total reclaimed space: 45.2GB` |

### Сеть и DNS

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `dig registry.internal +short` | Проверка разрешения DNS | `10.0.1.50` |
| `dig registry.internal +trace` | Трассировка разрешения DNS | цепочка `=>>` от корневых серверов к ответу |
| `resolvectl status` | Статус systemd-resolved (если используется) | `Link 2 (eth0) ... Current DNS Server: 10.0.0.1` |
| `cat /etc/resolv.conf` | Текущие DNS-серверы | `nameserver 10.0.0.1` |
| `ip route get 10.0.1.50` | Маршрут до registry | `10.0.1.50 via 10.0.0.1 dev eth0` |
| `curl -I --connect-timeout 5 https://registry.internal/v2/` | Доступность registry по HTTPS | `HTTP/2 200` или `curl: (28) Connection timed out` |
| `mtr -n -c 10 registry.internal` | Диагностика маршрута и потерь пакетов | таблица с loss% по хопам |

### Логи и аудит

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `journalctl -u gitlab-runner --since "1 hour ago" -p err` | Ошибки юнита за последний час | список ERROR/WARNING записей с таймстемпами |
| `journalctl -u gitlab-runner --since "2026-09-27 10:00" | grep -E "panic|fatal|segfault"` | Критические ошибки в окне времени | `2026-09-27T10:08:12Z panic: runtime error: invalid memory address` |
| `journalctl -u gitlab-runner --since "today" | awk '{print $3}' | sort \| uniq -c \| sort -rn` | Статистика по уровням логов | `15234 INFO`, `312 ERROR`, `12 WARNING` |
| `ausearch -k runner_exec -i --start recent` | События auditd по ключу `runner_exec` | `type=EXECVE msg=audit(...): argc=3 a0="gitlab-runner"` |
| `auditctl -l` | Текущие загруженные правила auditd | список правил с ключами и путями |

### Память и OOM

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `free -h` | Использование памяти и swap | `Mem: 32G 28G 1G ... Swap: 8G 0B 8G` |
| `swapon --show` | Активные swap-устройства/файлы | `/dev/sdb2 partition 8G 0B -2` |
| `cat /proc/sys/vm/overcommit_memory` | Политика выделения памяти | `0` (heuristic), `1` (always), `2` (strict) |
| `dmesg -T \| grep -i "oom\\|killed process"` | Сообщения ядра об OOM | `[Sun Sep 27 10:08:12 2026] Killed process 1234 (registry) total-vm:2048000kB` |
| `systemd-analyze blame` | Время загрузки сервисов при старте | `5min 12.345s gitlab-runner.service` |

### Registry — обслуживание и мониторинг

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `curl -sSL https://registry.internal/v2/_catalog` | Проверка доступности registry | `{"repositories":["library/nginx","app/api"]}` или ошибка соединения |
| `curl -sSL https://registry.internal/v2/<name>/tags/list` | Список тегов образа | `{"name":"library/nginx","tags":["1.25","1.26"]}` |
| `skopeo inspect docker://registry.internal/library/nginx:1.25` | Информация об образе без скачивания | `Digest: sha256:...`, `Size: 142MB` |
| `harborctl gc --start` | Запуск GC в Harbor (если используется) | `Garbage collection started, job ID: gc-20260927-1015` |

## Типичные ошибки и решения

| Симптом | Причина | Решение | Роль |
| :--- | :--- | :--- | :--- |
| **`Too many open files`** | Дефолтный `LimitNOFILE` исчерпан при 100+ параллельных джоб | Увеличить `LimitNOFILE=65536` в systemd-юните раннера | Sysadmin |
| **`OOMKilled`** | `MemoryMax` не установлен или слишком мал для задачи | Указать `MemoryMax` в systemd-юните или `limits.memory` в пода раннера | Sysadmin |
| **Раннер не берёт задачи в работу** | Неверный URL/токен регистрации, `concurrent=0` в `config.toml`, квота исчерпана | Проверить `gitlab-runner verify`, убедиться что `concurrent > 0` и есть свободные слоты | Sysadmin |
| **`No space left on device` при сборке** | Переполнение `/var/lib/docker` или инодов реестра | `docker system prune -f`, мониторинг `df -i /var/lib/registry`, настройка retention | Sysadmin |
| **Registry недоступен** | DNS не резолвится, диск переполнен, сервис упал | Проверить `dig registry.internal`, `df -h /var/lib/registry`, `systemctl status registry` | Sysadmin |
| **Падение джоба с `connection refused`** | Сеть: нет маршрута до registry, firewall блокирует порт | Проверить `ip route get registry.internal`, `nft list ruleset`, `curl -I registry.internal` | Sysadmin |
| **Деплой зависает на `pull image`** | MTU через туннель меньше, чем в контуре; пакеты рвутся | Уменьшить MTU на интерфейсе туннеля или включить фрагментацию | Sysadmin |
| **Периодический GC не срабатывает** | Timer отключён, юнит упал, `Persistent=false` и пропущен окно | `systemctl list-timers`, `journalctl -u registry-gc.service`, включить `Persistent=true` | Sysadmin |
| **Логи раннера не приходят в центральный storage** | rsyslog/Vector не запущен, неверный путь к journald | Проверить `systemctl status rsyslog`, конфиг Vector, права на `/var/log/journal` | Sysadmin |
| **Auditd не логирует события** | Правило не загружено, `auditd` остановлен, квота исчерпана | `auditctl -l`, `systemctl status auditd`, `ausearch -k runner_exec -i` | Sysadmin |
| **Слишком агрессивный `MemoryMax`** | Раннер убивается при пиковой нагрузке, хотя памяти достаточно | Увеличить `MemoryMax` или перейти на `MemoryHigh` с throttling вместо kill | Sysadmin |
| **Swap не используется** | `swapon --show` пуст, `vm.swappiness=0`, нет swap-файла/раздела | Создать swap-файл или включить существующий, настроить `swappiness` | Sysadmin |
| **Config drift после ручного фикса** | Инженер зашел на сервер и исправил конфиг вручную | Ввести rule: все изменения через IaC; drift-детекция ежедневно | Sysadmin / DevOps |

## Лучшие практики

### Infrastructure as Code и идемпотентность

1. **Все конфигурации в Git:** systemd-юниты, sysctl, nftables, auditd-правила — в репозитории, применяются через Ansible/Terraform. Исключает «снежинки» и drift.
2. **Immutable Runner Images:** Golden image (Packer) с предустановленными зависимостями; при изменении — rebuild образа, а не патч на живом узле.
3. **Right-sizing по метрикам:** `requests`/`limits` для раннеров на основе исторических данных DORA-метрик и observability; не резервировать 4 CPU для линтера.
4. **Ежедневный drift check:** `ansible-playbook --check --diff` для Bare Metal/VM; drift-детекция для конфигов breaker/timeout/pool.

### Лимиты и изоляция

5. **cgroups для всех сервисов:** `MemoryMax=`, `CPUQuota=`, `LimitNOFILE=` в systemd-юнитах; cgroup v2 для контейнеров (`cpu.max`, `memory.max`).
6. **Отдельный том для реестра:** `/var/lib/registry` на отдельном устройстве/томе с `noatime`, мониторинг `df -h` и `df -i`.
7. **GC по расписанию:** systemd-timer для регулярной очистки реестра; retention policy по возрасту/ветке/тегу.
8. **Swap с контролем:** swap-файл или раздел для защиты от OOM; `vm.swappiness=10` для раннеров, `vm.overcommit_memory=0` для реестра.

### Сеть и безопасность

9. **Бастион как единственная точка входа:** только `ProxyJump`, без паролей, без `PermitRootLogin`; минимальный набор правил nftables.
10. **DNS внутренний и кэширующий:** локальный resolver (Unbound/systemd-resolved) для контура; мониторинг TTL и % ответов из кэша.
11. **MTU согласован:** проверять `ip link show` на всех hops туннеля; для VPN/VXLAN — установить `mtu 1400` на интерфейсе.
12. **Аудит всех изменений:** `auditd` логирует exec() раннеров, изменения конфигов, доступ к секретам; логи централизованы через rsyslog/Vector.

### Наблюдаемость и логи

13. **Journald как источник правды:** все сервисы пишут в journald; пересылка в Loki/ELK через Vector с тегами `service`, `node`, `pipeline_id`.
14. **Structured logging:** раннеры и реестр используют JSON-логи; обогащение `trace_id`/`correlation_id` для построения таймлайна.
15. **Дашборды на узел:** node_exporter + cAdvisor на каждом узле; дашборд в Grafana с Golden Signals (latency, traffic, errors, saturation).
16. **Алерты на SLO, а не на ресурсы:** дежурный должен получать только actionnable алерты, связанные с пользовательским опытом или Error Budget.

### Резервное копирование и восстановление

17. **Golden image для быстрого подъёма:** образ реестра и конфигурации раннеров хранятся в immutable storage; DR drill раз в квартал.
18. **Бэкап метаданных реестра:** Harbor/Nexus метаданные + слои; проверка restore через smoke-пайплайн.
19. **Offsite-копия:** минимум 3 копии, 2 носителя, 1 offsite/air-gapped; sneakernet-бандл с подписью GPG/cosign.
20. **Автоматизация:** cron/systemd-таймер для регулярных бэкапов; алерты на провал job-ы в пайплайне.

### Связь с другими дисциплинами

21. **Load Shedding:** паттерн надёжности на границе сервиса; sysadmin-лимиты (`LimitNOFILE`, `somaxconn`) — часть инфраструктурного shedding. См. **[Сброс нагрузки (Load Shedding)](./load_shedding.md)**.
22. **Reliability Patterns:** Circuit Breaker, Bulkhead, Timeout, Graceful Degradation — паттерны, предотвращающие каскадные отказы. См. **[Паттерны надёжности](./reliability_patterns.md)**.
23. **Incident Response:** Постмортемы, runbook'ы, escalation matrix для CI/CD-инцидентов. См. **[Incident Response для CI/CD](../GitLab_CI/Advanced/incident_response_cicd.md)**.

## Дополнительная информация

### См. также

- [Изолированные среды](./air_gapped_environments.md) — прокси, бастион, очистка реестра.
- [Усиление безопасности CI/CD](./ci_cd_security_hardening.md) — SSH/firewall для узлов.
- [Управление службами systemd](../../Linux/Core/systemd/service_management.md) — команды и юниты.
