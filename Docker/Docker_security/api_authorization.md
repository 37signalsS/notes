# Авторизация Docker API

**Актуально для:** Docker Engine 29.x. Защита сокета через docker-socket-proxy — SSoT в [docker_compose_security.md](../Docker_compose/docker_compose_security.md). Данный файл — механизм authorization-плагинов, TLS и контроль доступа к Docker API.

## Определения

**Docker API** — REST API демона (`/var/run/docker.sock` или TCP: 2375 — без шифрования, 2376 — с TLS). Полный доступ к API эквивалентен root на хосте: создание контейнеров с монтированием `/`, `--privileged`, доступ к секретам.

**Authorization-плагин** — внешний сервис, который Docker опрашивает перед выполнением вызова API: плагин возвращает allow/deny. Реализуется как HTTP-мидлвейр (`--authorization-plugin=<name>`; `<name>` — имя плагина или путь к spec-файлу; в `daemon.json` — массив `authorization-plugins`). Несколько плагинов работают цепочкой: запрос разрешён, только если все плагины в порядке разрешили его.

**docker-socket-proxy** — обратный прокси для Unix-сокета (HAProxy): whitelist эндпоинтов (например, только `GET /containers/json` для мониторинга).

**Mutual TLS (mTLS)** — двусторонняя аутентификация на TCP-сокете (порт 2376): клиент и сервер предъявляют сертификаты.

## Базовые концепции

### Модель угроз Docker API

| Вектор | Последствия | Контроль |
| :--- | :--- | :--- |
| TCP 2375 без TLS | Полный root-хост для любого в сети | Никогда не включать; только 2376 с mTLS |
| Сокет в контейнере (`-v /var/run/docker.sock:...`) | Побег: контейнер создаёт привилегированный контейнер | Не монтировать; socket-proxy с whitelist |
| Группа `docker` | Любой член группы = root-хост | Минимальный состав; sudo-правила вместо группы |
| Неограниченный API | `docker run --privileged`, чтение секретов | Authorization-плагин с политиками |

### Как работает authorization-плагин

1. Клиент вызывает Docker API (HTTP).
2. Демон **до выполнения** отправляет запрос плагину: пользователь, метод, URI (с версией API), заголовки, тело запроса.
3. Плагин возвращает `allow` или `deny` (с причиной). Плагин также может авторизовать **ответ** демона (`/AuthZPlugin.AuthZRes`) — например, для редакции полей в ответе.
4. При недоступности плагина или при `Allow: false` middleware демона **отказывает в запросе** (fail-closed). Плагин сам тоже должен fail-closed: если он не может уверенно оценить запрос — вернуть ошибку или `Allow: false`.

**Идентификация пользователя:** при включённом TLS на демоне поле `User` = CN клиентского сертификата (`AuthenticationMethod: TLS`). Без TLS `User` пуст — политики «по пользователю» не работают, остаются только метод, путь и тело.

**Ограничения (важно):**
- Плагины применяются **только к HTTP API**: gRPC-вызовы (в том числе upgrade через `POST /grpc`) не подпадают под AuthZ — containerd API напрямую не контролируется.
- Тела запросов/ответов видны плагину **только при `Content-Type: application/json`**; тела других типов демон обрабатывает, но плагин их не видит и не может по ним фильтровать.
- Для команд с HTTP Upgrade (`exec`, `attach`) плагин вызывается только на начальном запросе — потоки данных ему не передаются. Для chunked-ответов (`logs`, `events`) — только запрос. Буфер тела ответа — 64 KiB: на потоковых ответах редакция через плагин ненадёжна, фильтруйте в отдельном слое перед демоном.
- Плагины **не deprecated** (доступны в Docker 29), но имели bypass-уязвимости: CVE-2024-41110 (обход AuthZ: демон пересылал плагину запрос/ответ без тела; CVSS 9.9, исправлен в **27.1.1**) и CVE-2026-34040 (обход AuthZ, CVSS 8.8, исправлен в **29.3.1**) — держите Engine актуальным.
- opa-docker-authz **без настроенной политики или конфига fail-open** (разрешает всё): отсутствие конфигурации ≠ запрет.

## Практические сценарии

### Сценарий 1: защита Unix-сокета (минимум)

```bash
# Права: только root и группа docker
ls -l /var/run/docker.sock
# → srw-rw---- 1 root docker 0 ... /var/run/docker.sock

# Состав группы docker — минимальный
getent group docker
# → docker:x:998:deploy-user

# Проверка: API не слушает на TCP
ss -tlnp | grep -E '2375|2376'
# → (пусто — TCP API отключён)
```

**Правило:** членство в группе `docker` — привилегия root. Для операторов — sudo-правила на конкретные команды (`/usr/bin/docker ps`, `/usr/bin/docker logs`), а не группа.

### Сценарий 2: socket-proxy для инструментов (Portainer, CI, мониторинг)

Полный compose-пример с whitelist эндпоинтов — в [docker_compose_security.md](../Docker_compose/docker_compose_security.md). Суть:

```yaml
# docker-socket-proxy: доступны только read-only эндпоинты
services:
  socket-proxy:
    image: tecnativa/docker-socket-proxy
    environment:
      CONTAINERS: 1      # GET /containers/...
      IMAGES: 0            # запретить управление образами
      NETWORKS: 0
      VOLUMES: 0
      EXEC: 0              # запретить docker exec
      BUILD: 0
      POST: 0              # весь API в режим read-only (только GET/HEAD)
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

**Принцип:** инструмент получает только те эндпоинты, которые ему нужны; `EXEC`, `BUILD`, `POST`-методы отключаются. **`CONTAINERS: 1` без `POST: 0` открывает полный жизненный цикл контейнеров** (включая `POST /containers/create` и `DELETE /containers/{id}`) — единственный безопасный read-only режим: `POST: 0`. Прокси не поддерживает TLS — не публикуйте его порт наружу, доступ только с localhost или по внутренней Docker-сети. Полный compose-пример и нюансы (`ALLOW_START`, `ALLOW_STOP` и пр.) — в [docker_compose_security.md](../Docker_compose/docker_compose_security.md).

### Сценарий 3: authorization-плагин (OPA/OpenPolicyAgent)

**Предварительное требование:** TLS на демоне (см. сценарий 4) — иначе плагин не видит пользователя, и политики «по пользователю» неприменимы.

**Шаг 1 — установка плагина.** Upstream рекомендует managed plugin (рекомендуемый режим); политика или OPA-конфиг кладутся в `/etc/docker/...` и монтируются в `/opa`:

```bash
docker plugin install --alias opa-docker-authz \
  openpolicyagent/opa-docker-authz-v2:0.8 \
  opa-args="-config-file /opa/config/opa-conf.yaml"
docker plugin ls
# → ...  opa-docker-authz   true
```

Legacy-вариант (контейнер) — для совместимости; монтируется каталог discovery-плагинов, **не** docker.sock:

```bash
docker run -d --restart=always --name opa-docker-authz \
  -v /run/docker/plugins:/run/docker/plugins \
  -v /etc/opa/policies:/opa \
  openpolicyagent/opa-docker-authz:0.6 -policy-file /opa/authz.rego
```

**Не монтируйте `/var/run/docker.sock` в плагин** — это даёт ему полный root-хоста, тот самый вектор, от которого плагин должен защищать.

**Шаг 2 — политика (Rego).** Схема `input` в opa-docker-authz: `Method`, `Path` (с версией API, например `/v1.52/containers/create`), `PathPlain`, `Query`, `Body` (распарсенное тело запроса), `Headers` (включая `Authz-User`), `User`, `BindMounts` — массив `{Source, ReadOnly, Resolved}`, где `Resolved` — путь с разрешёнными symlink'ами (ловит обфускацию вида `ln -sf / root; -v /root:/mnt`). Пример: запрет `--privileged`, монтирования `/` и `seccomp=unconfined`:

```rego
package docker.authz

default allow := false

allow if {
  not privileged
  not host_root_mount
  not seccomp_unconfined
}

# POST /containers/create — тело запроса в input.Body
privileged if {
  glob.match("/**/containers/create", ["/"], input.Path)
  input.Body.HostConfig.Privileged
}

host_root_mount if {
  glob.match("/**/containers/create", ["/"], input.Path)
  some m in input.BindMounts
  m.Resolved == "/"
}

seccomp_unconfined if {
  glob.match("/**/containers/create", ["/"], input.Path)
  "seccomp=unconfined" in input.Body.HostConfig.SecurityOpt
}
```

`glob.match` нужен, потому что `Path` содержит версию API (`/v1.40/...`). Схема зависит от версии плагина — проверьте поля в документации плагина перед внедрением.

**Шаг 3 — включение в демоне:**

```json
// /etc/docker/daemon.json
{
  "authorization-plugins": ["openpolicyagent/opa-docker-authz-v2:0.8"]
}
```

```bash
# authorization-plugins — SIGHUP-перечитываемая опция, restart не обязателен
sudo systemctl reload docker

# Проверка: привилегированный запуск отклонён
docker run --privileged alpine
# → Error response from daemon: authorization denied by plugin openpolicyagent/opa-docker-authz-v2:0.8
```

**Шаг 4 — аудит:** решения OPA логируются в JSON (`decision_id`, `input`, `result`) — в логах демона для `-policy-file`, через decision-logging OPA (в т.ч. remote endpoint) для `-config-file`. Отклонённые вызовы содержат пользователя, метод и путь.

### Сценарий 4: TLS для TCP API (межхостовое управление)

Полная процедура генерации CA, серверных и клиентских сертификатов — в [Docker: Protect the Docker daemon socket with TLS](https://docs.docker.com/engine/security/https/). Упрощённо:

```bash
# Генерация CA и сертификатов (упрощённо)
openssl req -newkey rsa:4096 -nodes -x509 -days 365 \
  -keyout ca-key.pem -out ca.pem -subj "/CN=Docker CA"
# Сертификаты сервера (CN = IP/FQDN хоста) и клиента — по аналогии

# Демон: /etc/docker/daemon.json
{
  "tls": true,
  "tlscacert": "/etc/docker/ca.pem",
  "tlscert": "/etc/docker/server-cert.pem",
  "tlskey": "/etc/docker/server-key.pem",
  "tlsverify": true,
  "hosts": ["tcp://0.0.0.0:2376", "unix:///var/run/docker.sock"]
}

# Клиент
docker --tlsverify --tlscacert=ca.pem --tlscert=cert.pem --tlskey=key.pem \
  -H tcp://docker-host:2376 version
```

**Правило:** `tlsverify: true` требует клиентский сертификат (mTLS); без него — только `tls` (шифрование без аутентификации клиента) — недостаточно.

**Конфликт `hosts` на systemd (Debian/Ubuntu):** systemd передаёт dockerd флаг `-H fd://`, поэтому `hosts` в daemon.json вызовет ошибку запуска — сначала создайте drop-in, снимающий флаг; пошагово — в [docker_daemon_config.md](../docker_daemon_config.md) §7. Альтернатива без открытого TCP: `DOCKER_HOST=ssh://user@host` (поддерживается клиентом нативно, требует public-key auth).

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Все вызовы отклонены после включения плагина | Плагин недоступен (fail-closed) | Проверить доступность плагина: `curl http://127.0.0.1:8443/health`; логи плагина; `docker plugin ls` |
| Все вызовы разрешены после установки OPA-плагина | Плагин без policy/config fail-open | Указать `opa-args` (managed) или `-policy-file` (legacy); проверить логи плагина |
| Политика на пользователя не срабатывает | TLS не включён на демоне — `User` пуст | Включить TLS/mTLS (сценарий 4); `User` = CN клиентского сертификата |
| Плагин не вызывается для некоторых операций | gRPC-вызовы не проходят HTTP AuthZ | Контролировать containerd API отдельно (права на сокет containerd) |
| `docker run --privileged` прошёл | Плагин не блокирует поле или CVE bypass | Обновить Engine (CVE-2024-41110 fixed 27.1.1, CVE-2026-34040 fixed 29.3.1); проверить политику Rego (поле `input.Body.HostConfig.Privileged`) |
| Клиент не подключается по 2376 | Несовпадение CN сертификата или CA | `openssl s_client -connect host:2376`; CN сертификата = FQDN/IP хоста |
| API слушает на 2375 | Осталась конфигурация `-H tcp://0.0.0.0:2375` | Убрать из systemd unit / daemon.json; `ss -tlnp \| grep 2375` |

## Лучшие практики

1. **TCP API — только 2376 с mTLS.** Порт 2375 (без шифрования) никогда не включать.
2. **Сокет не монтировать в контейнеры.** Для инструментов — socket-proxy с whitelist эндпоинтов.
3. **Authorization-плагин для shared-окружений.** Политики: запрет `--privileged`, монтирования `/`, `docker exec` для не-администраторов.
4. **Fail-closed — осознанно.** Недоступность плагина блокирует API: мониторить доступность плагина.
5. **Группа `docker` — привилегия root.** Минимальный состав; sudo-правила для операторов.
6. **Патчить Engine.** AuthZ-плагины имели bypass-CVE: CVE-2024-41110 (fixed 27.1.1) и CVE-2026-34040 (fixed 29.3.1); бюллетени — в [Docker Security Advisories](https://docs.docker.com/security/security-announcements).
7. **Аудит вызовов API.** Логи плагина + `docker events` в SIEM; auditd-правило на сокет (`-w /var/run/docker.sock -p rwxa -k docker_socket`) — см. [runtime_monitoring.md](./runtime_monitoring.md).

## Дополнительная информация

**Связанные документы:**

- [docker-socket-proxy (compose)](../Docker_compose/docker_compose_security.md) — SSoT: whitelist эндпоинтов, compose-пример.
- [Укрепление хоста и демона](./host_daemon_hardening.md) — конфигурация демона, TLS.
- [CVE побегов из контейнеров](./container_escape_cves.md) — побеги через runc, containerd, BuildKit, ядро.
- [Реагирование на инциденты](./incident_response.md) — сценарий «криптомайнер через открытый API».
- [Compliance](./compliance_frameworks.md) — контроль доступа (PCI DSS Req. 7).

**Внешние ресурсы:**

- [Docker: Access authorization plugin](https://docs.docker.com/engine/extend/plugins_authorization/) — механизм плагинов, API `AuthZReq`/`AuthZRes`, fail-closed middleware.
- [Docker: Protect the daemon socket with TLS](https://docs.docker.com/engine/security/https/) — генерация CA и сертификатов для 2376.
- [OPA Docker AuthZ](https://github.com/open-policy-agent/opa-docker-authz) — пример плагина (managed и legacy режимы, схема `input`).
- [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) — прокси сокета.

**Инструменты:** `openssl` (mTLS), OPA (политики), docker-socket-proxy, `ss` (проверка портов).
