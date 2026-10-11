# Реагирование на инциденты Docker

**Актуально для:** Docker Engine 29.8.x (актуальный релиз — 29.8.2, октябрь 2026). Docker Engine 28.x и ранее достигли EOL (май 2026). containerd 1.7.36+ (1.7.x LTS) / 2.3.6+ (2.x), runc 1.2.8+. Общая теория IR-цикла — SSoT в [incident_response (Linux)](../../Linux/Security/Concepts/incident_response.md); Kubernetes-вариант — в [Kubernetes incident_response](../../Kubernetes/Security/incident_response.md). Данный файл — Docker-специфичный runbook: команды, порядок действий, ошибки.

## Определения

**Инцидент (Docker-контекст)** — событие, компрометирующее конфиденциальность, целостность или доступность контейнеров, образов, реестра или демона: побег из контейнера, зловредный образ, утечка секрета, криптомайнер, DoS ресурсов.

**Containment (сдерживание)** — изоляция инцидента без уничтожения доказательств. Для Docker — `docker pause`, а не `docker stop`: пауза сохраняет состояние памяти и ФС контейнера для форензики.

**Форензика контейнера** — сбор доказательств: `docker inspect` (конфигурация), `docker export` (ФС), `docker logs` (stdout/stderr), дамп памяти PID 1, auditd-логи хоста.

**Chain of Custody (цепь хранения)** — документированный процесс сбора, хранения и передачи цифровых доказательств для обеспечения их целостности и допустимости.

**IR-цикл** — подготовка → обнаружение → сдерживание → ликвидация → восстановление → анализ уроков.

## Предварительные требования

**Инструменты:**
- Docker Engine 29.8.x (29.8.2+); 28.x и ранее — EOL (май 2026).
- containerd 1.7.36+ (1.7.x LTS) или 2.3.6+ (2.x); runc 1.2.8+.
- Trivy 0.75+ или Grype — сканирование образов на EOL-пакеты и CVE.
- Falco 0.44+ / Tetragon — runtime-мониторинг и алертинг.
- `tcpdump`, `gcore` / `avml` — сбор сетевого трафика и дамп памяти.
- `jq`, `yq` — парсинг JSON/YAML выводов Docker API.
- `auditd` — аудит syscall и доступа к docker.sock.
- Доступ к хостовой ФС (`/var/lib/docker`, `/var/run/docker.sock`, audit-логи).

**Права и доступ:**
- Root илиsudo на хосте для дампа памяти, tcpdump, остановки контейнеров.
- CI runner / jump host с доступом к registry для проверки digest.
- Права на создание PR / issues в реестре (Harbor, ECR) для маркировки compromised-образов.
- Централизованный SIEM / log storage (Loki, ELK) с сохранением логов ≥90 дней.

**Подготовка до инцидента:**
- IR-кит: скрипт сбора доказательств (`inspect`, `export`, `logs`, `journalctl`, `tcpdump`), протестированный на staging.
- Runbook'и для каждого типа инцидента (побег, зловредный образ, криптомайнер, утечка секрета, DoS).
- Контакты: oncall, security team, registry admin, compliance officer.
- Резервные копии: образы, volumes, swarm/k8s манифесты — проверенные на восстановление.

## Базовые концепции

### Почему `docker stop` — ошибка на этапе сдерживания

`docker stop` посылает SIGTERM, затем SIGKILL: процесс завершается, память недоступна, временные файлы могут исчезнуть. `docker pause` замораживает cgroup: процессы остаются в памяти, ФС и сеть сохраняются — можно снять дамп памяти и ФС, при этом контейнер не может выполнять новые операции. Порядок: **pause → изолировать сеть → собрать доказательства → только потом stop/rm**.

### Что сохранять

| Артефакт | Команда | Что даёт |
| :--- | :--- | :--- |
| Конфигурация контейнера | `docker inspect <c>` | Образ, тома, сеть, capabilities, ENV, команда |
| Файловая система | `docker export <c> -o fs.tar` | Состояние ФС на момент инцидента |
| Логи приложения | `docker logs <c> > logs.txt 2>&1` | stdout/stderr контейнера |
| Логи демона | `journalctl -u docker --since "2 hours ago"` | Действия dockerd, ошибки |
| Процессы | `docker top <c>` | PID, cmdline процессов контейнера |
| Память | дамп PID 1 (gcore/avml) | Инъекции, скрытые процессы |
| Сеть | `tcpdump -i docker0 -w cap.pcap` | Эксфильтрация, C2-трафик |
| История образа | `docker history --no-trunc <image>` | Слои, команды сборки |

## Практические сценарии

### Сценарий 1: подозрение на побег из контейнера

**Признаки:** аномальные процессы на хосте от PID контейнера, изменение файлов хоста, срабатывания Falco (`shell_in_container`, `write below binary dir`), auditd-события на `/usr/bin/runc`.

**Действия:**

```bash
# 1. Сдерживание: заморозить, НЕ останавливать
docker pause <container>

# 2. Изолировать сеть (отключить от моста)
docker network disconnect <network> <container>

# 3. Доказательства
docker inspect <container> > inspect.json
docker export <container> -o /evidence/fs.tar
docker logs <container> > /evidence/logs.txt 2>&1
docker top <container>
journalctl -u docker --since "3 hours ago" > /evidence/dockerd.log

# 4. Проверить версии рантайма (CVE-каталог)
docker version --format '{{range .Server.Components}}{{.Name}} {{.Version}}{{"\n"}}{{end}}'
# → containerd 1.7.36 / runc 1.2.8

# 5. Дамп памяти PID 1 контейнера (с хоста)
PID=$(docker inspect --format '{{.State.Pid}}' <container>)
sudo gcore -o /evidence/core.$PID $PID
```

**Анализ:** сопоставить версии runc/containerd с [container_escape_cves.md](./container_escape_cves.md); проверить `docker history` образа на зловредные слои; искать модификации бинарников рантайма (`rpm -Va` / `debsums -c`).

### Сценарий 2: зловредный образ в реестре

**Признаки:** алерты сканера, аномальное поведение контейнеров из одного образа, неизвестные слои.

**Действия:**

```bash
# 1. Остановить развёртывание (не удалять образ!)
docker pull <registry>/<image>:<tag> 2>/dev/null; docker image inspect <image> --format '{{.Id}}'

# 2. Проанализировать образ
docker history --no-trunc <image>
# → слои с командами сборки: искать curl|sh, добавление SUID, запись в /etc
trivy image --severity CRITICAL,HIGH <image>

# 3. Проверить digest и сравнить с ожидаемым
docker image inspect <image> --format '{{index .RepoDigests 0}}'

# 4. Изолировать: запретить pull в CI, пометить тег как compromised в registry
```

**Ликвидация:** удалить образ из registry (Harbor: удаление артефакта + GC — в [Harbor usage](../Docker_registries/Harbor/usage.md)); пересобрать из доверенного источника; ротация секретов, доступных при сборке.

### Сценарий 3: криптомайнер / аномальное потребление ресурсов

```bash
# 1. Найти контейнер
docker stats --no-stream
# → CONTAINER ID  NAME   CPU %  MEM USAGE
# → a1b2c3d4e5f6  web    312%   1.2GiB

# 2. Заморозить и исследовать
docker pause a1b2c3d4e5f6
docker top a1b2c3d4e5f6
# → PID  COMMAND: 12345 /tmp/.xmrig --donate-level=1

# 3. Доказательства: export ФС, логи, tcpdump (пул C2)
docker export a1b2c3d4e5f6 -o /evidence/miner-fs.tar
sudo tcpdump -i docker0 -w /evidence/miner-net.pcap

# 4. Найти вектор: как запущен (docker inspect), откуда образ
docker inspect a1b2c3d4e5f6 --format '{{.Config.Image}} {{.HostConfig.Privileged}}'
```

**Типичные векторы:** открытый Docker API (TCP 2375 без TLS), зловредный образ из public registry, `--privileged` контейнер, утёкший API-ключ CI. Проверка: `ss -tlnp | grep 2375` (API не должен слушать на TCP).

### Сценарий 4: утечка секрета

**Признаки:** секрет в ENV контейнера (`docker inspect`), в логах, в слоях образа.

**Действия:**

```bash
# 1. Найти, где виден секрет
docker inspect <c> --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -i pass
docker history --no-trunc <image> | grep -i -E 'pass|token|key'

# 2. Срочно: ротация секрета (пока контейнер paused — он не может использовать утёкший секрет)

# 3. Убрать секрет из ENV: пересобрать образ без секретов (multi-stage, --secret)
docker build --secret id=mysecret,src=secret.txt .
```

**Правило:** секрет, попавший в слой образа или ENV, считается скомпрометированным — ротация обязательна, удаление из истории (`docker history`) не помогает: слой остаётся в registry.

### Сценарий 5: DoS / исчерпание ресурсов хоста

```bash
# 1. Определить виновника
docker stats --no-stream
df -h /var/lib/docker          # диск: логи, слои, volumes
docker system df               # распределение места

# 2. Сдерживание: ограничить контейнер
docker update --memory=512m --cpus=1 --pids-limit=100 <c>

# 3. Очистка (после сбора доказательств)
docker system prune -a --volumes   # ВНИМАНИЕ: удаляет неиспользуемые ресурсы
```

**Профилактика:** `--memory`, `--cpus`, `--pids-limit` на всех контейнерах (в [resource_limits.md](./resource_limits.md)); ротация логов (в [docker_log_rotation.md](../Docker_logs/docker_log_rotation.md)); GC registry (в [cleanup_gc_strategies](../Docker_fs/cleanup_gc_strategies.md)).

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `docker pause` не помогает | Контейнер уже exited или PID namespace не выделен | `docker inspect --format '{{.State.Status}}'`; если exited — `docker export` для ФС |
| Нет логов контейнера | Log-драйвер `none` или контейнер без TTY | `docker inspect --format '{{.HostConfig.LogConfig}}'`; включить `json-file` с ротацией |
| `docker export` пуст | Контейнер с `tmpfs`-only ФС или `--read-only` без mounted volumes | Проверить `--read-only` и `--tmpfs`; собирать тома отдельно через `docker run --volumes-from` |
| Не удаётся найти вектор | Образ пересобран/перетеган, registry GC удалил старый digest | Digest в `RepoDigests` + Harbor audit log / GCR access log |
| Инцидент повторяется | Вектор не устранён (открытый API, утёкший ключ) | `ss -tlnp \| grep 2375`; аудит CI-ключей; review `docker events` за 24ч |
| Открытый Docker API (TCP 2375) | bind mount 2375:2375 без TLS | Немедленно `iptables -I INPUT -p tcp --dport 2375 -j DROP`; перейти на TLS или socket proxy — в [api_authorization.md](./api_authorization.md) |
| `tcpdump` на docker0 не ловит трафик | CNI bridge без promisc или overlay vxlan | Использовать `-i any` или tcpdump на физическом интерфейсе; для overlay — захват на `cni0` |
| `gcore` / `avml` падает на paused-контейнере | Cgroup frozen / permissions | Дамп с хоста: `cat /proc/<PID>/maps` и `gcore` от root; avml предпочитается для production (меньше footprint) |
| Stale evidence (логи удалены) | Ротация логов docker / journalctl | Настроить `log-driver` с `max-size` / `max-file` ≥100M и ≥10 файлов; SIEM с хранением ≥90 дней |
| Rootless dockerd — нет доступа к docker.sock | `XDG_RUNTIME_DIR` не экспортирован в IR-кит | Собирать evidence из пользовательского namespace: `sudo nsenter -t <PID> -m` или настроить `DOCKER_HOST=unix:///run/user/1000/docker.sock` |

### Ограничения и граничные случаи

- **Rootless Docker:** `docker.sock` принадлежит пользователю; host-ский `auditd` не видит его. Используйте `sudo ausearch -f /run/user/*/docker.sock` или `journalctl --user -u docker`.
- **Swarm mode:** `docker pause` работает на уровне сервиса, но `docker inspect` возвращает только текущий task; собирайте evidence с каждого узла отдельно.
- ** containerd image store (новый в 29.x):** `docker history` и `docker inspect` показывают сокращённые размеры; для точного `Size` используйте `docker image inspect --format '{{.Size}}'` или `docker system df -v`.
- **Air-gapped хосты:** Trivy/Falco БД обновляются вручную; в IR-кит включите offline-сканер (`trivy image --skip-db-update`) и portable-копию `eol-scanner` embedded data.
- **Distroless / Wolfi / Chainguard:** нет `sh`, `bash`, `ps`, `top`. Для форензики используйте `docker exec --shm-size=256m --entrypoint /bin/sh <image> -c "..."` (если `sh` доступен) или debug-образ с утилитами.

## Лучшие практики

1. **IR-kit заранее:** скрипт сбора доказательств (inspect/export/logs/journalctl/tcpdump), доступный без Docker (хостовые утилиты).
2. **pause, не stop** — на этапе сдерживания; `docker rm` только после полного сбора артефактов.
3. **Логирование по умолчанию:** json-file с ротацией + централизация в SIEM; `docker events` в поток мониторинга.
4. **Мониторинг runtime:** Falco/Tetragon-правила (`shell_in_container`, `write below etc`, `docker socket opened`) — в [runtime_monitoring.md](./runtime_monitoring.md).
5. **Аудит демона:** auditd-правила на `/var/run/docker.sock`, `/usr/bin/docker`, `/usr/bin/runc` — в [auditd](../../Linux/SystemAdministration/Logging/auditd.md).
6. **Неизменяемая инфраструктура:** контейнеры пересоздаются из образов, а не патчатся in-place — восстановление = redeploy с чистым образом.
7. **Разбор уроков:** после инцидента — timeline, вектор, что сработало, что нет; обновить runbook и профили.
8. **Скорость обновления runtime:** containerd ≥ 1.7.36 / 2.3.6, runc ≥ 1.2.8 — обязательны для защиты от CVE-2026-53493 (DoS при pull) и CVE-2025-31133/52881/52565 (escape через `/proc`). Подписка на [Docker Security Advisories](https://docs.docker.com/security/security-announcements) и OSS-Security.
9. **Нет открытому Docker API:** TCP 2375 без TLS — критический риск. Используть TLS-клиентские сертификаты или proxy (docker-socket-proxy, IPA) — в [api_authorization.md](./api_authorization.md).
10. **Chain of Custody:** все артефакты (fs.tar, logs, core dump, pcap) хранятся с хешем, временной меткой и initials ответственного; несоблюдение — артефакт недопустим в суде/аудите.
11. **Ротация после инцидента:** секреты (ENV, docker secret, registry auth), ServiceAccount токены, CI-ключи — ротация обязательна даже при подозрении, а не только при подтверждении.
12. **Регулярные drills:** tabletop exercises раз в квартал; сценарии — container escape, compromised image, secret leak, DoS. Протестировать pause → isolate → collect → stop.

## Коммуникация при инциденте

### Уведомление команды (SEV-1/2)

```
[SEVERITY: P1/P2] Incident: <тип>

Affected systems: <хосты/контейнеры/образы>
Time detected: <UTC>
Current status: Investigating / Contained / Resolved

Impact: <сервисы, данные, пользователи>
Actions taken: <pause, isolate, collect evidence>
Next steps: <ликвидация, восстановление>
ETA: <ориентировочное время>
Incident lead: <имя/контакт>
```

### Эскалация руководству (SEV-1)

```
Кратко: <1-2 предложения>
Бизнес-влияние: <SLA, пользователи, данные, репутация>
Статус: <сдержано / в работе>
План: <следующие 3-5 шагов>
Сроки: <когда ожидаем разрешение>
Ресурсы: <нужна ли помощь>
```

## Шаблон постмортема (Post-Incident Review)

```
## Post-Incident Review: <Название>

### Метрики
- Time to detect (TTD): <время от начала до обнаружения>
- Time to contain (TTC): <время от обнаружения до сдерживания>
- Time to resolve (TTR): <время от начала до полного устранения>
- Влияние: <затронутые сервисы/пользователи>

### Хронология
| Время (UTC) | Событие |
| :--- | :--- |
| HH:MM | Обнаружение |
| HH:MM | Сдерживание |
| HH:MM | Устранение |
| HH:MM | Восстановление |

### Корневая причина
<описание + 5 Whys>

### Что сработало
- <список>

### Что нужно улучшить
- <список>

### Action Items
| Действие | Ответственный | Срок |
| :--- | :--- | :--- |
| <действие> | <имя> | <дата> |
```

### Стандарты и регуляторные требования

- **NIST SP 800-61r3** — реагирование на инциденты.
- **PCI DSS v4.0.1** — Req. 12.10: план IR, тестирование, документация.
- **ISO 27035** — управление инцидентами безопасности информации.
- **SOC 2 Type II (2026)** — CC7.1: мониторинг, обнаружение и реагирование.
- **GDPR / 152-ФЗ** — уведомление регулятора ≤72 часа с момента обнаружения.
- **EU CRA (2026)** — reporting obligation для vulnerabilities с impact на safety.

## Дополнительная информация

**Связанные документы:**

- [IR: общая теория](../../Linux/Security/Concepts/incident_response.md) — SSoT: IR-цикл, классификация.
- [IR: Kubernetes](../../Kubernetes/Security/incident_response.md) — k8s-вариант runbook.
- [journalctl: IR](../../Linux/Diagnostics/journalctl/journalctl_incident_response.md) — логи systemd.
- [CVE побегов из контейнеров](./container_escape_cves.md) — проверка версий рантайма.
- [Мониторинг в Runtime](./runtime_monitoring.md) — Falco/Tetragon.
- [Управление секретами](./secrets_management.md) — ротация.
- [Реестры: Harbor usage](../Docker_registries/Harbor/usage.md) — удаление артефактов, GC.

**Внешние ресурсы:**

- [Docker security incident response](https://docs.docker.com/security/) — официальные рекомендации.
- [NIST SP 800-61](https://csrc.nist.gov/pubs/sp/800/61/r3/final) — стандарт IR.

**Инструменты:** `docker` 29.8.x (`pause`, `export`, `inspect`, `top`, `logs`, `events`, `version`, `stats`, `update`, `system prune`), `containerd` 1.7.36+ / 2.3.6+, `runc` 1.2.8+, `trivy` 0.75+ (`image`, `vm`, `sbom`), `grype` (SCA), `falco` 0.44+, `tetragon`, `tcpdump`, `gcore` / `avml`, `auditd`, `jq`, `yq`, `eol-scanner` (endoflife.date), `ss` / `ip` / `iptables` / `nftables`.
