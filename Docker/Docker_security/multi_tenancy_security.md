# Multi-tenancy в Docker (standalone)

**Актуально для:** Docker Engine 29.x, gVisor (runsc). Kubernetes multi-tenancy — SSoT в [multi-tenancy.md](../../Kubernetes/Concepts/multi-tenancy.md). Данный файл — изоляция tenants в Docker без Kubernetes (single-host, Compose, Swarm).

## Определения

**Multi-tenancy** — совместное использование одной Docker-инфраструктуры (хоста, демона, реестра) несколькими tenants (командами, клиентами, проектами) с изоляцией их данных, процессов, сети и ресурсов.

**Noisy neighbor** — tenant, чья нагрузка или компрометация исчерпывает общие ресурсы (CPU, RAM, PIDs, диск, сеть) и degradает работу остальных tenants.

**Tenant isolation** — совокупность механизмов, предотвращающих пересечение tenants: namespaces, cgroups, LSM, сетевая сегментация, отдельные демоны.

## Базовые концепции

### Уровни изоляции (от слабого к сильному)

| Уровень | Механизм | Изоляция | Когда применять |
| :--- | :--- | :--- | :--- |
| 1. Разные пользователи ОС | Пользователи + группа `docker` | Слабая: член группы `docker` = root хоста | Не применять для tenants |
| 2. `userns-remap` | UID/GID mapping в демон | Контейнерный root ≠ хостовый root | Базовый уровень для всех |
| 3. Сетевая сегментация | Отдельные bridge-сети, `icc=false`, DOCKER-USER | Сетевая изоляция tenants | Минимум для shared-хоста |
| 4. Resource limits | cgroups v2: cpu, memory, pids, blkio | Защита от noisy neighbor | Всегда |
| 5. Отдельный демон на tenant | Rootless `dockerd` per user | Сильная: отдельный userns, сокет, cgroup-иерархия | Разные уровни доверия |
| 6. gVisor / Kata | Отдельное «ядро» (runsc) / VM | Максимальная: изоляция ядра | Недоверенные tenants |

### Noisy neighbor и защита ресурсов

Без лимитов один tenant может:
- исчерпать RAM хоста (OOM-killer убивает чужие контейнеры);
- забить CPU (`--cpus` не задан);
- исчерпать PIDs (`--pids-limit` не задан — fork-bomb влияет на хост);
- заполнить диск (логи, volumes);
- забить сеть (bandwidth — Docker не имеет встроенного лимита: через `tc`/iptables).

Контроль: cgroups v2 лимиты на каждый контейнер (см. [resource_limits.md](./resource_limits.md)), `pids-limit`, мониторинг `docker stats`.

**Важно:** изоляция на уровне 1–4 применяется внутри **одного демона** — компрометация демона (или группы `docker`) ломает все уровни. Уровень 5 (отдельный демон) — единственный, дающий независимость tenants при компрометации одного из демонов.

### Дополнительный слой: LSM-профили

Параллельно с namespaces и cgroups применяются Linux Security Modules:
- **AppArmor** — ограничивает доступ к файлам, сетевым сокетам, capabilities по именованному профилю (Docker использует `docker-default`).
- **seccomp** — фильтр syscall'ов; Docker по умолчанию применяет профиль, блокирующий ~44 syscall'а.
- **SELinux** — мандатное управление доступом (MAC); в RHEL/Fedora контейнеры получают метку `container_file_t`, что изолирует их от хостовых процессов.

Отключение LSM (`--security-opt apparmor=unconfined`, `--privileged`, `--security-opt seccomp=unconfined`) убирает этот слой. Детали — в [container_hardening.md](./container_hardening.md).

## Практические сценарии

### Сценарий 1: сетевая сегментация tenants

```bash
# Отдельная сеть на tenant; icc=false глобально (daemon.json)
docker network create --internal tenant-a-internal
docker network create tenant-a-net
docker network create tenant-b-net

# Запрет трафика между сетями tenants через DOCKER-USER
iptables -I DOCKER-USER -i tenant-a-net -o tenant-b-net -j DROP
iptables -I DOCKER-USER -i tenant-b-net -o tenant-a-net -j DROP

# Валидация: контейнер tenant A не достучится до tenant B
docker run --rm -it --network tenant-a-net alpine ping -c 1 <tenant-b-ip>
# → 100% packet loss
```

`--internal` блокирует egress; детали сетевой изоляции — в [network_security.md](./network_security.md) и [docker_network_policies.md](../Docker_network/docker_network_policies.md).

### Сценарий 2: resource limits per tenant

```bash
# Жёсткие лимиты: tenant не выходит за квоту
docker run -d --name tenant-a-app \
  --memory=512m --memory-swap=512m \
  --cpus=0.5 \
  --pids-limit=100 \
  --cap-drop=ALL \
  tenant-a/app:latest

# Проверка применения лимитов
docker stats --no-stream tenant-a-app
# → CONTAINER ID   NAME          CPU %     MEM USAGE / LIMIT
# → ...            tenant-a-app  2.10%     128MiB / 512MiB
```

Полная матрица лимитов (cpu, memory, blkio, pids) — в [resource_limits.md](./resource_limits.md).

### Сценарий 3: отдельный демон на tenant (rootless)

Сильная изоляция: каждый tenant — свой системный пользователь со своим rootless-демоном:

```bash
# На хосте: пользователи tenant-a, tenant-b
sudo useradd -m tenant-a
sudo useradd -m tenant-b

# Rootless Docker для каждого (dockerd-rootless-setuptool.sh)
sudo -u tenant-a dockerd-rootless-setuptool.sh install
sudo -u tenant-b dockerd-rootless-setuptool.sh install

# Сокеты демонов изолированы
ls /var/run/user/*/docker.sock
# → /var/run/user/1001/docker.sock (tenant-a)
# → /var/run/user/1002/docker.sock (tenant-b)

# Контейнеры tenant-a не видны tenant-b
sudo -u tenant-a docker ps
# → только контейнеры tenant-a
```

Rootless-режим требует cgroups v2 и делегирования; настройка — в [host_daemon_hardening.md](./host_daemon_hardening.md), безопасная передача ssh-agent — в [ssh-agent-rootless.md](./ssh-agent-rootless.md).

### Сценарий 4: gVisor для недоверенных tenants

```bash
# Установить runsc и зарегистрировать runtime
docker run --runtime=runsc --rm hello-world

# Проверка runtime контейнера
docker inspect --format '{{.HostConfig.Runtime}}' <container>
# → runsc
```

gVisor (runsc) реализует ядро в userspace — контейнер не обращается к ядру хоста напрямую. Теория и настройка — в [container_hardening.md](./container_hardening.md).

### Сценарий 5: запрет shared volumes между tenants

```bash
# Правило: volumes не шарятся между tenants
# Каждый tenant — свой namespace volumes (именование с префиксом)
docker volume create tenant-a-data
docker volume create tenant-b-data

# Read-only монтирование общих артефактов (если необходимо)
docker run -v tenant-a-data:/data:ro tenant-a/app:latest
```

При `userns-remap` UID 0 контейнера маппится на непривилегированный UID хоста — bind-mountы требуют согласования прав; предпочтительны Docker Volumes (см. [overview.md](./overview.md#дополнительная-информация)).

## Требования

- Docker Engine 29.x. Для rootless-режима — systemd cgroup delegation (`systemd --version` ≥ 245, cgroups v2).
- Ядро Linux ≥ 5.4 с включёнными namespaces (PID, NET, UTS, IPC, mount), cgroups v2, `CONFIG_USER_NS=y`, `CONFIG_SECCOMP=y`.
- Для gVisor — `runsc` ≥ 2026.x, совместимый с ядром хоста.
- Для AppArmor/SELinux — профили должны быть доступны в хостовой ОС (по умолчанию в Ubuntu/Debian/RHEL).

Если prerequisites не выполняются, механизмы изоляции могут работать в degraded-режиме или быть недоступны.

### Сценарий 6: жёсткие Security Opts

```bash
docker run -d --name tenant-a-app \
  --security-opt no-new-privileges \
  --security-opt seccomp=default \
  --read-only \
  --tmpfs /run:noexec,nosuid,size=64m \
  --cap-drop=ALL \
  --network tenant-a-net \
  --memory=512m --cpus=0.5 --pids-limit=100 \
  tenant-a/app:latest
```

Валидация:
```bash
docker inspect tenant-a-app --format '{{.HostConfig.SecurityOpt}}'
# → [no-new-privileges seccomp=default]
docker inspect tenant-a-app --format '{{.HostConfig.ReadonlyRootfs}}'
# → true
```

### Сценарий 7: защита Unix socket и rootless демона

Для rootless-демона права на сокет уже ограничены пользователем tenant:

```bash
ls -l /var/run/user/1001/docker.sock
# → srw-rw---- 1 tenant-a tenant-a ... docker.sock
```

Если требуется удалённый доступ — TLS на TCP-сокете в `daemon.json`:

```json
{
  "hosts": ["unix:///var/run/docker.sock"],
  "tls": true,
  "tlscacert": "/etc/docker/ca.pem",
  "tlscert": "/etc/docker/server.pem",
  "tlskey": "/etc/docker/server-key.pem",
  "tlsverify": true
}
```

Только клиенты с подписанным сертификатом получают доступ. Никогда не монтируйте `/var/run/docker.sock` в контейнеры tenants — это даёт полный контроль над демоном.

### Сценарий 8: запрет `--privileged` и shared PID/IPC namespace

```bash
# Разрешено:
docker run --userns-remap --network tenant-a-net --memory=512m tenant-a/app

# Запрещено для tenants:
docker run --privileged ...
docker run --pid=container:other-tenant ...
docker run --ipc=shareable ...
```

Дополнительные запреты можно реализовать через Policy Plugin или скрипты-обёртки.

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Контейнер tenant A видит tenant B | Общая bridge-сеть или `icc=true` | Отдельные сети; `{"icc": false}` в daemon.json; правила DOCKER-USER |
| Tenant исчерпал RAM хоста | Нет `--memory` | cgroups-лимиты; `docker stats`; OOM-score |
| Fork-bomb в контейнере влияет на хост | Нет `--pids-limit` | `--pids-limit=100`; cgroups pids controller |
| `userns-remap` ломает запись в bind-mount | UID mapping не согласован | Docker Volumes вместо bind-mounts; согласовать права на хосте |
| Rootless-демон не стартует | cgroups v2 не делегирован | `stat -fc %T /sys/fs/cgroup/` → `cgroup2fs`; делегирование systemd |
| Tenants видят чужие образы в реестре | Нет RBAC реестра | RBAC в Harbor/реестре (см. [registry_security.md](./registry_security.md)) |
| LSM-профиль не применяется | `--privileged` или `apparmor=unconfined` | Проверить `docker inspect --format '{{.HostConfig.SecurityOpt}}'` |
| Контейнер может управлять демоном | `/var/run/docker.sock` смонтирован | Никогда не монтировать socket в контейнер; rootless socket имеет права владельца |
| `no-new-privileges` не сработал | Отсутствует в `SecurityOpt` | Добавить `--security-opt no-new-privileges` при запуске |

## Валидация

Проверка изоляции tenant:

```bash
# 1. Проверить, что контейнер запущен с userns-remap
docker inspect tenant-a-app --format '{{.HostConfig.UsernsMode}}'
# → user:1001:1001

# 2. Проверить, что root внутри контейнера ≠ root хоста
docker exec tenant-a-app id -u
# → 1001 (не 0)

# 3. Проверить сетевую изоляцию
docker network inspect tenant-a-net
# → "Internal": false, "EnableIPv6": false
docker network inspect tenant-a-internal
# → "Internal": true

# 4. Проверить cgroups лимиты
systemd-cgtop -b -n 1 --order=memory
# или
cat /sys/fs/cgroup/.../memory.max

# 5. Проверить LSM-профиль
docker inspect tenant-a-app --format '{{.HostConfig.SecurityOpt}}'
# → [no-new-privileges seccomp=default]
```

## Очистка

Удаление ресурсов tenant:

```bash
# Остановить и удалить контейнеры
docker rm -f tenant-a-app tenant-b-app

# Удалить сети tenants
docker network rm tenant-a-net tenant-b-net tenant-a-internal

# Удалить volumes tenants
docker volume rm tenant-a-data tenant-b-data

# Остановить и отключить rootless-демон (опционально)
sudo -u tenant-a systemctl --user stop docker
sudo -u tenant-a systemctl --user disable docker
```

## Пограничные случаи

- **Userns-remap + bind-mount:** UID 0 контейнера маппится на непривилегированный UID хоста. Bind-mountы требуют согласования UID/GID на хосте. Если маппинг неизвестен — используйте Docker Volumes.
- **Rootless delegation:** `systemd-run --user --scope` требует делегирования `Delegate=yes` в юнит-файле. Без него cgroups-лимиты и `pids-limit` не работают.
- **cgroups v1 vs v2:** Docker Engine 29.x требует cgroups v2. На хостах с cgroups v1 rootless-режим и некоторые лимиты (blkio, io weight) недоступны.
- **Docker Swarm:** Service create поддерживает `--userns-remap` в Docker 29.x, но поддержка LSM-профилей через Compose v2 ограничена. Проверяйте `docker service inspect`.

## Лучшие практики

1. **Отдельный демон на tenant** — для разных уровней доверия; rootless `dockerd` per user.
2. **Сетевая сегментация — минимум:** отдельные bridge-сети, `icc=false`, DOCKER-USER rules.
3. **Resource limits — всегда:** memory, cpus, pids-limit на каждый контейнер.
4. **gVisor/Kata** — для недоверенных tenants и многопользовательских CI-раннеров.
5. **Не давать группу `docker` tenants** — это root хоста; sudo-правила на конкретные команды.
6. **RBAC реестра** — tenants видят только свои образы (см. [registry_security.md](./registry_security.md)).
7. **Жёсткие Security Opts по умолчанию:** `--security-opt no-new-privileges`, `--read-only`, `--cap-drop=ALL`, `--tmpfs` для временных каталогов.
8. **Никогда не монтировать `/var/run/docker.sock`** в контейнеры tenants — это даёт полный контроль над демоном.
9. **Аудит:** включить `auditd` (правила для `docker` бинарников), собирать `docker events`, логи systemd для `dockerd` и rootless-юнитов.
10. **Kubernetes** — для кластерной multi-tenancy используйте namespace/NetworkPolicy/RBAC (см. [multi-tenancy.md](../../Kubernetes/Concepts/multi-tenancy.md)).

## Дополнительная информация

**Связанные документы:**

- [Kubernetes multi-tenancy](../../Kubernetes/Concepts/multi-tenancy.md) — SSoT для K8s (namespaces, NetworkPolicy, RBAC).
- [Укрепление хоста и демона](./host_daemon_hardening.md) — userns-remap, rootless.
- [Ресурсные лимиты](./resource_limits.md) — cgroups v2.
- [Сетевая безопасность](./network_security.md) — ICC, DOCKER-USER.
- [Укрепление контейнеров](./container_hardening.md) — gVisor, capabilities.
- [Безопасность реестров](./registry_security.md) — RBAC, immutable tags.
- [Rootless Docker и ssh-agent](./ssh-agent-rootless.md).
- [Аудит и мониторинг Docker](./runtime_monitoring.md) — auditd, docker events, Falco.
- [Авторизация API демона](./api_authorization.md) — плагины OPA, защита сокета.

**Инструменты:** `docker network create`, `iptables` (DOCKER-USER), `docker stats`, `dockerd-rootless-setuptool.sh`, `auditd`, `docker events`, `docker inspect`, `systemd-cgtop`, `trivy`, `grype`, gVisor (`runsc`).
