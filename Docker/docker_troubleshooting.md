## Доступ к контейнеру через `nsenter` (когда `docker exec` не работает)

**Проблема:** Контейнер завис, не отвечает или в нем отсутствует оболочка (`/bin/sh`), что делает `docker exec` бесполезным.

**Решение:** Использовать утилиту `nsenter` для входа в пространства имён (namespaces) контейнера напрямую, в обход стандартных команд Docker.

**Шаг 1: Узнайте PID процесса контейнера на хосте**

```bash
PID=$(docker inspect --format '{{.State.Pid}}' <container_id_or_name>)
```

**Шаг 2: Подключитесь к пространствам имён контейнера**

Эта команда "перенесет" вашу оболочку внутрь контейнера, используя его файловую систему, сеть, процессы и т.д.
```bash
# Выполняем команду входа во все ключевые namespaces
sudo nsenter --target $PID --mount --uts --ipc --net --pid
```

По умолчанию nsenter запустит оболочку, указанную в переменной окружения $SHELL пользователя, от которого вы выполняете nsenter. Теперь вы внутри окружения контейнера, как в обычном `chroot`. 


## Отладка контейнеров без shell (`distroless`)

`Distroless`-образы — лучшая практика безопасности, но стандартная отладка через `docker exec -it <container> /bin/sh` в них не работает.

### `docker exec` с другим пользователем

Если в образе есть shell, но он недоступен текущему пользователю, попробуйте зайти как `root`:
```sh
docker exec -it --user root <container_name> /bin/sh
```

### Эфемерный отладочный контейнер (рекомендуемый способ)

Запуск временного контейнера с полным набором утилит в пространствах имён целевого контейнера.

*   **Анализ сети:**
    ```sh
    # nicolaka/netshoot содержит множество сетевых утилит (ss, tcpdump и т.д.)
    docker run -it --rm --network=container:<target_container_name> nicolaka/netshoot
    ```
*   **Анализ процессов:**
    ```sh
    # Позволяет видеть процессы целевого контейнера (ps, top, strace)
    docker run -it --rm --pid=container:<target_container_name> alpine
    ```

### Копирование файлов с помощью `docker cp`

Для анализа логов или конфигураций просто скопируйте их на хост:
```sh
docker cp <container_name>:/path/to/file /local/path/
```

### Использование `docker debug`

Эта команда (доступна в Docker Desktop версии 4.27.0 и выше) является современным решением для отладки. Она создает копию контейнера, но с возможностью переопределить `entrypoint` или добавить инструменты.
```sh
# Создаст копию контейнера my-app и запустит в ней /bin/sh из образа alpine
docker debug my-app -it --image=alpine --entrypoint=/bin/sh
```

## Ошибка `file not found` в Alpine для скомпилированного бинарного файла

**Проблема:** Бинарный файл, скомпилированный в Ubuntu/Debian, не запускается в Alpine с ошибкой `file not found` или `error while loading shared libraries`.

**Причина:** Несовместимость стандартных библиотек C. В большинстве дистрибутивов используется `glibc`, а в Alpine — легковесная `musl libc`.

**Решение 1 (Лучшее):** Пересобрать приложение в `alpine`-образе, используя многоэтапную сборку.

**Решение 2 (Компромисс):** Установить `glibc` в Alpine.

```dockerfile
FROM alpine:3.22.1

ENV GLIBC_VERSION="2.35-r1"
RUN apk add --no-cache wget ca-certificates && \
    wget -q -O /etc/apk/keys/sgerrand.rsa.pub https://alpine-pkgs.sgerrand.com/sgerrand.rsa.pub && \
    wget "https://github.com/sgerrand/alpine-pkg-glibc/releases/download/${GLIBC_VERSION}/glibc-${GLIBC_VERSION}.apk" && \
    apk add --no-cache glibc-${GLIBC_VERSION}.apk && rm -f glibc-*.apk

# Теперь можно запускать glibc-совместимые приложения
COPY ./my-glibc-app /usr/local/bin/
CMD ["my-glibc-app"]
```

## Использование своих alias'ов в контейнере

**Проблема:** Ваши привычные alias'ы и функции из `~/.bashrc` не работают внутри контейнера.

**Решение:** Смонтировать `bashrc` с хоста в контейнер при запуске.
```sh
docker run -it \
  -v ~/.bashrc:/root/.bashrc \
  --env BASH_ENV=/root/.bashrc \
  ubuntu bash
```

## Анализ низкоуровневых событий с помощью docker events

**Проблема:** Контейнер постоянно перезапускается, но `docker logs` пуст, а `docker exec` не удается выполнить, так как контейнер "умирает" слишком быстро.

**Причина:** Проблема часто вызвана не самим приложением, а внешними действиями Docker-демона, которые не логируются внутри контейнера.

**Решение:** Использовать `docker events` для просмотра потока системных событий от демона Docker в реальном времени.

**Пример отладки перезапускающегося контейнера:**

```sh
# Фильтруем события по имени или ID конкретного контейнера
docker events --filter container=<your_container_id>
```

**Пример вывода, указывающий на проблему с Healthcheck:**

```
2025-10-03T18:20:01.123Z container create ...
2025-10-03T18:20:02.456Z container start ...
2025-10-03T18:20:03.789Z container health_status: unhealthy ...
2025-10-03T18:20:04.123Z container kill signal=SIGTERM actor.name=healthcheck
2025-10-03T18:20:04.456Z container die ...
2025-10-03T18:20:04.789Z container restart ...
```
Из этого вывода ясно, что контейнер был остановлен (`kill`) из-за проваленного `healthcheck`, после чего политика перезапуска (`restart`) вступила в силу. Эта информация отсутствует в логах самого приложения.

### Сценарии, где `docker events` незаменим:

-   **Проваленные Healthchecks:** Как в примере выше.
-   **OOM Kills:** Обнаружение контейнеров, убитых ядром из-за нехватки памяти (`oom-kill`).
-   **Проблемы с томами (Volumes):** События `mount` и `unmount`.
-   **Падающие init-контейнеры или сайдкары:** Отслеживание их жизненного цикла отдельно от основного контейнера.
-   **Общий аудит:** Просмотр всех действий в системе Docker (`image pull`, `network create` и т.д.) во время инцидента, убрав фильтр.

### Полезные флаги `docker events`:

| Флаг | Описание |
| :--- | :--- |
| `--filter <key>=<value>` | Фильтрует события (например, `container=...`, `event=start`, `image=...`). |
| `--since <timestamp>` | Показывает события, произошедшие *после* указанного времени (например, `30m`, `2025-10-03T18:00:00`). |
| `--until <timestamp>` | Показывает события, произошедшие *до* указанного времени. |
| `--format '{{json .}}'` | Выводит каждое событие как структурированную JSON-строку. |

---

## Низкая производительность Docker в CentOS/RHEL 7 (драйвер devicemapper)

В старых версиях Docker на CentOS 7 и RHEL 7 по умолчанию использовался драйвер хранения `devicemapper`. Без дополнительной настройки он работал в режиме `loopback` (`loop-lvm`), который **категорически не подходил для production-сред**.

**Симптомы:**
*   Крайне низкая производительность операций ввода-вывода (I/O) внутри контейнеров.
*   Постепенная деградация производительности файловой системы, вплоть до полной остановки.
*   Нестабильная работа и риск потери данных.
*   Вывод команды `docker info` показывал наличие `Data loop file` и `Metadata loop file`.

```
$ docker info
...
Storage Driver: devicemapper
 Pool Name: docker-thinpool
 Pool Blocksize: 65.54 kB
 Base Device Size: 10.74 GB
 Backing Filesystem: xfs
 Data file: /var/lib/docker/devicemapper/devicemapper/data
 Metadata file: /var/lib/docker/devicemapper/devicemapper/metadata
 Data loop file: /var/lib/docker/devicemapper/devicemapper/data
 Metadata loop file: /var/lib/docker/devicemapper/devicemapper/metadata
...
```

Причина в том, что режим `loopback` эмулирует блочное устройство через файлы на основной файловой системе, создавая несколько медленных слоев абстракции.

### Решение: Настройка `direct-lvm` Thin Pool

Правильным решением для production-среды было переключение `devicemapper` в режим `direct-lvm`. Этот режим работает напрямую с блочными устройствами LVM, что значительно быстрее и стабильнее.

**Общий план действий:**

1.  **Подготовить блочное устройство:** Выделить отдельный диск, раздел или LVM-том для Docker.
2.  **Создать LVM Thin Pool:**
    *   Создать физический том (`pvcreate`).
    *   Создать группу томов (`vgcreate`).
    *   Создать два логических тома (один для данных, другой для метаданных) и объединить их в `thin pool` с помощью `lvconvert`.
3.  **Настроить Docker:** Указать Docker использовать `devicemapper` с созданным `thin pool` через конфигурационный файл `/etc/docker/daemon.json`.

**Пример конфигурации `/etc/docker/daemon.json`:**

```json
{
    "storage-driver": "devicemapper",
    "storage-opts": [
        "dm.thinpooldev=/dev/mapper/vg-thinpool",
        "dm.use_deferred_removal=true",
        "dm.use_deferred_deletion=true"
    ]
}
```
После этого в `docker info` поля `Data loop file` и `Metadata loop file` должны исчезнуть.

Драйвер `devicemapper` считается устаревшим и был **удален в Docker 25.0**.

Современным, более производительным и простым в настройке драйвером для всех дистрибутивов Linux является **[`overlay2`](./docker_overlayfs.md)**. При возможности всегда следует использовать его.

