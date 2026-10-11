# Защита Docker API от DoS и злоупотреблений

**Актуально для:** Docker Engine 29.x, containerd 1.7.36+ / 2.x (2.0.13+, 2.2.9+, 2.3.6+); Docker Engine DoS: CVE-2026-32288 (sparse tar OOM), CVE-2026-93323 (oversized Dockerfile/LLB → OOM). containerd image-pull DoS: CVE-2026-53493 (crafted OCI index graph amplification); containerd runtime DoS: CVE-2026-47262 (unbounded group parsing). CRI-DoS: CVE-2025-64329 (goroutine leak в CRI Attach), CVE-2025-47291 (userns вне cgroup-иерархии), CVE-2026-53495 (goroutine leak в CRI ExecSync). Rate limits Docker Hub (registry-side) — описаны в [registry_api_v2.md](../Docker_registries/registry_api_v2.md). Общие методы DDoS-защиты и fail2ban — в [ddos_overview.md](../../Security/ApplicationSecurity/ddos_overview.md). Авторизация вызовов API — в [api_authorization.md](./api_authorization.md).

## Определения

**DoS на Docker API** — исчерпание ресурсов демона `dockerd` или рантайма `containerd` (CPU, RAM, file descriptors, процессы) через легитимные вызовы API или зловредные образы, приводящее к недоступности контейнерного рантайма на хосте.

**Rate limiting** — ограничение частоты запросов от одного клиента. Docker Engine **не имеет встроенного rate limiting** для API: документация dockerd рекомендует защищать демон либо встроенным HTTPS-сокетом, либо безопасным веб-прокси перед ним.

**Resource exhaustion через API** — атака, при которой злоумышленник с доступом к API создаёт контейнеры, образы или сети в цикле, исчерпывая ресурсы хоста.

**CVE-2026-47262** (GHSA-jpcc-p29g-p8mq, CWE-400, CVSS 5.5 MEDIUM; GHSA 2026-06-18, NVD 2026-07-01) — DoS в containerd через неограниченный разбор групп образа (unbounded group parsing): зловредный образ вызывает неограниченное потребление памяти при создании контейнера, OOM-killer завершает процесс containerd, делая недоступным runtime API и ломая рантайм на всём узле (Docker Engine и control-plane Kubernetes). Исправлена в containerd 1.7.33, 2.0.10, 2.1.9, 2.2.5, 2.3.2. Workaround до патча: только доверенные образы и только доверенным пользователям права на импорт образов и планирование подов.

## Базовые концепции

### Модель угроз Docker API

| Вектор | Механизм | Последствия | Контроль |
| :--- | :--- | :--- | :--- |
| Flood TCP-сокета (2375/2376) | Массовые запросы к API | CPU демона, отказ API | Firewall + rate limiting на прокси |
| Создание контейнеров в цикл | `POST /containers/create` | Исчерпание RAM/CPU/PIDs хоста | AuthZ-плагин с политикой лимитов |
| Pull образов в цикл | `POST /images/create` | Диск, сеть, память | Сканирование перед pull; лимиты на прокси |
| Pull crafted sparse tar archive | CVE-2026-32288 в Docker Engine | OOM демона | Патч Docker Engine; лимиты на прокси |
| Pull crafted OCI image index (deeply nested) | CVE-2026-53493 в containerd | unbounded CPU/memory | Патч containerd; лимиты на прокси |
| Oversized Dockerfile/.dockerignore/LLB | CVE-2026-93323 в BuildKit/Docker Engine | OOM демона | Патч BuildKit; валидация сборки |
| Зловредный образ | CVE-2026-47262 в containerd | OOM containerd, недоступность рантайма | Патч containerd; сканирование образов |
| Подписки `docker events` | Long-poll соединения | Исчерпание FD демона | Мониторинг FD; ограничение клиентов |

### Уровни защиты (обязательно внешние)

Docker Engine не предоставляет встроенного rate limiting, поэтому защита строится слоями:

1. **Сетевой:** TCP API не экспонировать вообще; если нужен — только в доверенной сети с firewall (iptables/nftables) по IP-адресам.
2. **Прокси:** nginx (или аналог) перед TCP API с `limit_req` / `limit_conn` — единственный способ rate limiting для API.
3. **Аутентификация:** mTLS на порту 2376 — доступ только клиентам с сертификатами (см. [api_authorization.md](./api_authorization.md#сценарий-4-tls-для-tcp-api-межхостовое-управление)).
4. **Авторизация:** AuthZ-плагин — запрет опасных операций и требование лимитов ресурсов при создании контейнеров.
 5. **Рантайм:** патчить containerd — DoS-CVE: CVE-2026-53493 (crafted OCI index graph amplification → unbounded CPU/memory при pull), CVE-2026-47262 (зловредный образ → OOM containerd); серия DoS в CRI: CVE-2025-64329 (goroutine leak в CRI Attach → исчерпание памяти хоста), CVE-2025-47291 (userns-контейнеры вне cgroup-иерархии Kubernetes → лимиты не применяются), CVE-2026-53495 (блокировка goroutine в CRI ExecSync при exec-пробах); патчить Docker Engine — DoS-CVE: CVE-2026-32288 (sparse tar → OOM при pull), CVE-2026-93323 (oversized Dockerfile/.dockerignore/LLB → OOM при build).
6. **Ресурсы:** cgroups-лимиты на контейнеры — даже при компрометации один контейнер не может исчерпать хост (см. [resource_limits.md](./resource_limits.md)).

**Важно отличать:** rate limits Docker Hub (100 pulls / 6 часов для неаутентифицированных клиентов) — это ограничение **реестра** на стороне registry-1.docker.io, оно не защищает локальный демон и не имеет отношения к защите `dockerd` API.

## Практические сценарии

### Сценарий 1: убедиться, что TCP API не экспонирован

```bash
# TCP API должен быть отключён (только Unix-сокет)
ss -tlnp | grep -E '2375|2376'
# → (пусто — TCP API не слушает)

# Endpoint текущего контекста клиента (tcp:// означает использование TCP API)
docker context ls
# → default *   unix:///var/run/docker.sock

# Валидация daemon.json без запуска демона
dockerd --validate
# → configuration OK

# Проверка systemd unit на наличие -H tcp://
systemctl cat docker | grep -E 'ExecStart.*-H'
# → ExecStart=/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock
```

Если TCP API всё же нужен (межхостовое управление) — только 2376 с mTLS и firewall по IP (см. [api_authorization.md](./api_authorization.md)).

### Сценарий 2: firewall — доступ к API только из доверенной сети

```bash
# iptables: только сеть управления, остальное — drop
iptables -A INPUT -p tcp --dport 2376 -s 10.0.0.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 2376 -j DROP

# nftables (аналог)
nft add rule inet filter input tcp dport 2376 ip saddr 10.0.0.0/24 accept
nft add rule inet filter input tcp dport 2376 drop

# Валидация: с недоверенного хоста
curl --connect-timeout 2 http://<docker-host>:2376/version
# → (timeout — соединение отброшено)
```

### Сценарий 3: nginx reverse proxy с rate limiting (если TCP API неизбежен)

Демон слушает только localhost, nginx терминирует TLS и ограничивает частоту:

```nginx
# /etc/nginx/conf.d/docker-api.conf
limit_req_zone $binary_remote_addr zone=dockerapi:10m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=dockerapi_conn:10m;

server {
    listen 2376 ssl;
    ssl_certificate     /etc/nginx/docker-api.crt;
    ssl_certificate_key /etc/nginx/docker-api.key;

    # mTLS на прокси: клиентский сертификат обязателен (нет сертификата — 496, ошибка верификации — 495)
    ssl_verify_client on;
    ssl_client_certificate /etc/nginx/docker-api-ca.crt;

    location / {
        limit_req zone=dockerapi burst=20 nodelay;
        limit_conn dockerapi_conn 5;
        proxy_pass http://127.0.0.1:2375;
    }
}
```

```bash
# dockerd: только localhost
# /etc/docker/daemon.json
{
  "hosts": ["unix:///var/run/docker.sock", "tcp://127.0.0.1:2375"]
}

# Валидация: flood запросов → 429/503 от nginx
for i in $(seq 1 100); do curl -sk https://localhost:2376/version -o /dev/null -w '%{http_code}\n'; done
# → 200 ... 200 429 429 429 (после исчерпания burst)
```

Конфигурация rate limiting nginx (`limit_req_zone`, `limit_req`, `limit_conn`) — стандартный механизм Nginx; детали настройки — в документации Nginx и разделах WebServers/Nginx. Без `ssl_verify_client` nginx терминирует TLS, но не проверяет клиентские сертификаты — mTLS фактически не выполняется (см. [api_authorization.md](./api_authorization.md#сценарий-4-tls-для-tcp-api-межхостовое-управление)).

Дополнительно — ограничить одновременные pull/push на стороне демона (значения по умолчанию: скачиваний — 3, загрузок — 5, попыток на pull — 5):

```json
// /etc/docker/daemon.json
{
  "max-concurrent-downloads": 3,
  "max-concurrent-uploads": 5,
  "max-download-attempts": 5
}
```

### Сценарий 4: защита от resource exhaustion через API

AuthZ-плагин (OPA) с политикой, требующей лимитов ресурсов при создании контейнера. Схема `input.Body.*` — для opa-docker-authz v2 (полный список полей и установка плагина — в [api_authorization.md](./api_authorization.md#сценарий-3-authorization-плагин-opaopenpolicyagent)):

```rego
package docker.authz

default allow = false

# Запрет привилегированных контейнеров и требование лимитов ресурсов
allow {
  not input.Body.HostConfig.Privileged
  input.Body.HostConfig.Memory > 0
  input.Body.HostConfig.NanoCpus > 0
}
```

Дополнительно — дефолтные ulimits для контейнеров и лимит FD для самого демона:

```json
// /etc/docker/daemon.json — default-ulimits применяются к контейнерам
{
  "default-ulimits": {
    "nofile": { "Name": "nofile", "Hard": 65536, "Soft": 65536 }
  }
}
```

```bash
# Лимит FD самого dockerd задаётся в systemd-юните (не в daemon.json)
# /etc/systemd/system/docker.service.d/limits.conf
[Service]
LimitNOFILE=65536
# → systemctl daemon-reload && systemctl restart docker
```

### Сценарий 5: containerd DoS (CVE-2026-47262) — детекция и фикс

**Симптом:** containerd рестартуется с OOM при создании контейнера из образа из недоверенного реестра; Docker API и kubelet (CRI) на узле недоступны.

```bash
# Версия containerd (должна быть ≥ 1.7.33 / 2.0.10 / 2.1.9 / 2.2.5 / 2.3.2)
containerd --version
# → containerd v1.7.33

# Детект: OOM-kills containerd в dmesg / journald
dmesg | grep -i 'oom.*containerd'
journalctl -u containerd | grep -i 'out of memory'

# Число рестартов containerd (рост без действий оператора — сигнал DoS)
systemctl show containerd -p NRestarts
# → NRestarts=12

# Корреляция: рестарты containerd с недавними pull из недоверенных реестров
docker events --filter 'event=pull' --since 1h
```

**Решение:** обновить containerd до исправленной версии; сканировать образы перед pull (Trivy, см. [vulnerability_scanning.md](./vulnerability_scanning.md)); не тянуть образы из недоверенных реестров. Workaround до патча (per GHSA-jpcc-p29g-p8mq): только доверенные образы и только доверенным пользователям права на импорт образов и планирование подов.

**Серия DoS в CRI** (не через образы — отдельный класс атак на kubelet-узлы):

| CVE | Механизм | Исправлена |
| :--- | :--- | :--- |
| CVE-2025-64329 (CVSS 6.9) | goroutine leak в CRI Attach → исчерпание памяти хоста | 1.7.29 / 2.0.7 / 2.1.5 / 2.2.1+ |
| CVE-2025-47291 (CVSS 4.6) | userns-контейнеры вне cgroup-иерархии Kubernetes → лимиты не применяются, DoS узла | 2.0.5 / 2.1.0+ |
| CVE-2026-53495 (CVSS 6.8) | блокировка drainExecSyncIO goroutine в CRI ExecSync при exec-пробах | 1.7.35 / 2.0.12 / 2.2.8 / 2.3.5 |

### Сценарий 6: Docker Engine DoS (CVE-2026-32288, CVE-2026-93323) — детекция и фикс

**Симптом:** `dockerd` завершается с OOM при pull образа (sparse tar archive) или при сборке образа с oversized Dockerfile/.dockerignore/nested LLB; API и kubelet (если используется встроенный containerd) становятся недоступны.

```bash
# Версия Docker Engine (должна быть 29.x, обновлённая)
docker version --format '{{.Server.Version}}'
# → 29.8.1

# Детект: OOM-kills dockerd в dmesg / journald
dmesg | grep -i 'oom.*dockerd'
journalctl -u docker | grep -i 'out of memory'

# Корреляция: OOM во время pull или build
docker events --filter 'event=pull' --since 30m
docker events --filter 'event=build' --since 30m
```

**Решение:** обновить Docker Engine до 29.x; обновить BuildKit до ≥ 0.33.1 (фикс CVE-2026-93323); ограничить размер Dockerfile/.dockerignore/LLB; не тянуть образы из недоверенных реестров.

**Дополнительно (containerd image-pull DoS):** CVE-2026-53493 — crafted OCI index с deeply nested или widely fanned-out descriptors → unbounded CPU/memory при `PullImage`. Исправлена в containerd 1.7.36 / 2.0.13 / 2.2.9 / 2.3.6 / 2.4.1. Симптом: долгие `ContainerCreating` и рост CPU/memory при pull. Фикс: обновить containerd; лимиты на прокси.

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| API не отвечает, CPU `dockerd` 100% | Flood запросов к TCP-сокету | `ss -tn state established '( dport = :2375 or dport = :2376 )'` — список клиентов; rate limiting на прокси; firewall по IP |
| dockerd OOM при pull | CVE-2026-32288 (sparse tar) / CVE-2026-53493 (deeply nested OCI index) | `dmesg \| grep oom`; обновить Docker Engine до 29.x / containerd; проверить источники образов |
| dockerd OOM при build | CVE-2026-93323 (oversized Dockerfile/.dockerignore/LLB) | `dmesg \| grep oom`; обновить BuildKit до ≥ 0.33.1; ограничить размер файлов сборки |
| containerd рестартует сам | CVE-2026-47262 (OOM от зловредного образа) | `dmesg \| grep oom`; обновить containerd; проверить источники образов |
| Масса `429` от прокси | `limit_req` сработал | Нормальное поведение при flood; настроить `burst`; проверить, что легитимные клиенты не попадают под лимит |
| nginx отдаёт `495`/`496` после включения mTLS | Нет клиентского сертификата (`496`) или ошибка верификации CA (`495`) | Проверить `ssl_client_certificate` (CA) и сертификаты клиентов; тест: `curl --cert client.crt --key client.key https://host:2376/version` |
| Много FD у `dockerd` | Подписки `docker events` / висящие клиенты | `lsof -p $(pidof dockerd) \| wc -l`; закрыть неиспользуемые клиенты и long-poll сессии |
| Контейнеры создаются без лимитов и грузят хост | Нет AuthZ-политики и дефолтных лимитов | Включить AuthZ-плагин; `default-ulimits`; лимиты в CI-шаблонах |

## Лучшие практики

1. **TCP API — только в доверенной сети или через SSH.** Никогда `0.0.0.0:2375`; для удалённого управления — `DOCKER_HOST=ssh://user@host`.
2. **Rate limiting — на прокси.** Docker Engine не имеет встроенного; nginx `limit_req`/`limit_conn` перед TCP API.
3. **mTLS + AuthZ-плагин** — минимизировать поверхность: только сертификаты, только разрешённые операции.
 4. **Патчить containerd и Docker Engine.** containerd DoS-CVE: CVE-2026-47262 (зловредный образ → OOM containerd) ломает рантайм на всём узле одним образом; CVE-2026-53493 (crafted OCI index → unbounded CPU/memory при pull); серия CRI-DoS (CVE-2025-64329, CVE-2025-47291, CVE-2026-53495) выводит из строя kubelet-узлы. Docker Engine DoS-CVE: CVE-2026-32288 (sparse tar → OOM при pull), CVE-2026-93323 (oversized Dockerfile/.dockerignore/LLB → OOM при build).
 5. **Лимиты ресурсов на контейнеры** — даже скомпрометированный контейнер не должен иметь возможности исчерпать хост.
6. **Мониторить:** `docker events`, OOM-kills containerd, число FD у `dockerd`, source IP доступа к API — в SIEM (см. [runtime_monitoring.md](./runtime_monitoring.md)). Метрики самого демона: `--metrics-addr 127.0.0.1:9323` (Prometheus-формат, порт 9323).
7. **Устойчивость к краху демона:** `"live-restore": true` в daemon.json — контейнеры продолжают работать при перезапуске `dockerd` (например, после OOM от flood).

## Дополнительная информация

**Связанные документы:**

- [Авторизация Docker API](./api_authorization.md) — AuthZ-плагины, mTLS, socket-proxy.
- [Защита хоста и демона](./host_daemon_hardening.md) — конфигурация демона, rootless.
- [Ресурсные лимиты](./resource_limits.md) — cgroups v2 лимиты.
- [Сетевая безопасность](./network_security.md) — DOCKER-USER, сегментация.
- [Сканирование уязвимостей](./vulnerability_scanning.md) — Trivy перед pull.
- [Rate limits Docker Hub](../Docker_registries/registry_api_v2.md) — ограничения реестра (не демона).
- [DDoS-обзор](../../Security/ApplicationSecurity/ddos_overview.md) — общие методы защиты, fail2ban.
- [Реагирование на инциденты](./incident_response.md) — сценарий «криптомайнер через открытый API».
- [Security advisories containerd](https://github.com/containerd/containerd/security/advisories) — официальные уведомления (CVE-2026-47262, GHSA-jpcc-p29g-p8mq).

**Инструменты:** `iptables`/`nftables` (firewall), nginx (`limit_req`, `limit_conn`), `ss`, `lsof`, `dmesg` (OOM-детект), Trivy (сканирование образов).
