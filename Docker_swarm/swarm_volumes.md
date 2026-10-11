# Docker Swarm: управление томами

**Актуально для:** Docker Swarm 29.x

## Определения

**Local Volume (Локальный том)** — стандартный Docker-том, данные которого хранятся на файловой системе одного конкретного узла Swarm. По умолчанию используется в Swarm-сервисах. Жизненный цикл тома привязан к узлу: при перемещении задачи на другой узел данные становятся недоступны.

**Bind Mount (Примонтированная директория)** — монтирование конкретной директории или файла хоста напрямую в контейнер. Данные сохраняются на хосте, но управление полностью возложено на администратора (Docker не создаёт и не управляет директорией).

**Persistent Volume (Персистентный том)** — том, данные которого сохраняются при перемещении контейнеров между узлами кластера. В Swarm достигается через NFS/CIFS, распределённые файловые системы (Ceph, GlusterFS) или Cluster Volumes (CSI).

**Cluster Volume (Кластерный том / CSI)** — современный тип томов в Docker Swarm (начиная с версии 23.0), использующий интерфейс CSI для интеграции с внешними хранилищами. Swarm отслеживает состояние таких томов на уровне всего кластера, обеспечивая корректное планирование задач и автоматическое перемещение тома при сбое узла. Подробнее см. **[Продвинутые тома в Swarm](./swarm_volumes_advanced.md)**.

**Access Mode (Режим доступа)** — матрица параметров `Scope` (сколько узлов) и `Sharing` (сколько задач может писать), определяющая, как том может быть примонтирован:
- **RWO / Single-Writer:** доступ на запись только одной задачи. Аналог `scope=single`, `sharing=none` или `sharing=onewriter`.
- **RWX / Multi-Writer:** одновременная запись с нескольких узлов. Требует поддержки на уровне СХД. Аналог `scope=multi`, `sharing=all`.

**Accessibility Topology (Топология доступности)** — информация о физическом расположении (сегмент `rack`, `zone`, `region`), используемая планировщиком Swarm для размещения контейнера там, где физически доступен диск.

**Volume Group (Группа томов)** — метка, объединяющая интерchangеable тома. Swarm может использовать любой том из группы для задачи, что упрощает деплой stateful-сервисов с репликацией.

## Базовые концепции

### Проблема персистентности в Swarm

По умолчанию тома в Docker Swarm являются **локальными**. Это создаёт проблему при перемещении задач между узлами:

```
[Узел 1] → [Том: /var/lib/docker/volumes/data]
    ↓ (миграция задачи: сбой узла, масштабирование, rolling update)
[Узел 2] → [Том: ПУСТО]
```

Если задача сервиса переносится на другой узел, данные в локальном томе становятся недоступны. Это делает стандартные Docker-тома непригодными для stateful-приложений без использования распределённых хранилищ, сетевых ФС или Cluster Volumes.

### Архитектура хранения в Swarm

Swarm наследует архитектуру томов Docker Engine, но добавляет уровень кластерного планирования:

1. **Уровень Engine:** Docker Daemon управляет локальными томами на каждом узле независимо.
2. **Уровень Orchestrator:** SwarmKit знает о Cluster Volumes и использует их состояние при планировании.
3. **Уровень CSI-драйвера:** Внешний плагин, установленный на узлах, обеспечивает доступ к блочным устройствам или сетевому хранилищу.

### Режимы работы томов

| Тип | Сфера применения | Перенос между узлами | Управление |
|---|---|---|---|
| **Local (bind/volume)** | Кэш, временные файлы, логи, конфиги | Нет (привязан к узлу) | Автоматическое (Docker Engine) |
| **NFS / CIFS** | Конфигурации, статика, медиа, общие ресурсы | Да (через сетевое монтирование) | Внешнее (ядро Linux / сервер) |
| **Cluster (CSI)** | Базы данных, блочные устройства, высоконагруженные stateful-сервисы | Да (автоматически оркестратором) | Нативное в Swarm + CSI-драйвер |

### Топология и размещение (Topology Awareness)

Для Cluster Volumes Swarm учитывает топологию (например, сегменты `rack` или `zone`). Если том создан с topology `rack=rack-3`, Swarm автоматически запланирует запуск контейнера на узле с соответствующим label. Для локальных томов и NFS это поведение эмулируется через `placement constraints` и метки узлов.

## Практические сценарии

### Предварительные требования

- **Docker Engine:** 29.x на всех менеджерах и рабочих узлах. Для Cluster Volumes требуется API 1.42+ (Docker 23.0+).
- **CSI-плагин:** установлен на всех менеджерах и на тех рабочих узлах, где должны размещаться тома. На менеджерах плагин должен реализовывать интерфейс `docker.csicontroller/1.0`, на воркерах — `docker.csinode/1.0`.
- **Сетевая связность:** узлы кластера должны иметь доступ к хранилищу (NFS-сервер, SAN, Ceph cluster).
- **Метаданные:** для топологии на узлы должны быть назначены labels (`docker node update --label-add rack=rack-3 <node>`).

### Использование Cluster Volumes (CSI)

```yaml
version: '3.8'

services:
  db:
    image: postgres:16-alpine
    volumes:
      - type: cluster
        source: pg_data
        target: /var/lib/postgresql/data
        volume_options:
          cluster_options:
            group: "databases"
    deploy:
      replicas: 1

volumes:
  pg_data:
    external: true # Рекомендуется создавать заранее
```

**Создание тома через CLI:**
```bash
docker volume create --driver <driver-name> \
  --type mount \
  --availability active \
  --scope single \
  --sharing none \
  --group databases \
  pg_data
# → pg_data
```

**Валидация:**
```bash
docker volume ls --cluster
# → NAME      GROUP       DRIVER        AVAILABILITY   STATUS
# → pg_data   databases   <driver-name> active         created

docker volume inspect pg_data
# → В секции "ClusterVolume" указан NodeID, где том активен
```

### Настройка NFS для общих данных

При настройке NFS важно использовать параметр `nocopy`, чтобы Docker не пытался копировать содержимое целевой директории образа в сетевой том при первом запуске.

```yaml
version: '3.8'

services:
  web:
    image: nginx:1.27-alpine
    deploy:
      replicas: 3
    volumes:
      - type: volume
        source: nfs-content
        target: /usr/share/nginx/html
        volume:
          nocopy: true # Отключает копирование данных из образа в том

volumes:
  nfs-content:
    driver: local
    driver_opts:
      type: nfs
      o: addr=nfs.example.com,rw,nfsvers=4.1,nolock,soft
      device: ":/srv/docker/swarm/web-content"
```

**Валидация:**
```bash
showmount -e nfs.example.com
# → Export list for nfs.example.com:
# → /srv/docker/swarm/web-content *

mount -t nfs nfs.example.com:/srv/docker/swarm/web-content /mnt/test
# → проверка доступности с воркера
```

### Локальные тома с ограничениями размещения

Если данные могут быть локальными (например, кэш Redis), используйте placement constraints:

```yaml
services:
  cache:
    image: redis:7.4-alpine
    volumes:
      - cache-data:/data
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.labels.storage-type == fast-ssd

volumes:
  cache-data:
    driver: local
```

**Валидация:**
```bash
docker service ps cache --no-trunc
# → убедитесь, что задача запущена на узле с label storage-type=fast-ssd
```

### Резервное копирование и миграция

Для томов без нативной поддержки снапшотов используется "Sidecar-метод" или временные сервисы.

**Бэкап кластерного тома через временный сервис:**
```bash
docker service create \
  --name backup_task \
  --restart-condition none \
  --mount type=cluster,src=pg_data,dst=/source,readonly \
  --mount type=bind,src=/mnt/backups,dst=/backup \
  alpine tar czf /backup/pg_data_$(date +%Y%m%d).tar.gz -C /source .
# → Swarm сам найдёт узел с томом и запустит там задачу бэкапа
```

После завершения:
```bash
docker service rm backup_task
# → временный сервис удалён, бэкап остаётся на хосте /mnt/backups
```

## Безопасность и ограничения

### Ограничение прав доступа (Read-Only)

Если сервису не нужно изменять данные (например, конфиги или статика), монтируйте тома в режиме "только чтение":

```yaml
services:
  web:
    volumes:
      - type: volume
        source: static-assets
        target: /app/static
        read_only: true
```

### Управление владельцем данных

NFS и Bind Mounts часто вызывают проблемы с правами (UID/GID):
- Для NFS используйте опцию `all_squash` на стороне сервера или убедитесь, что UID пользователя внутри контейнера совпадает с владельцем директории на сервере.
- Для Cluster Volumes CSI-драйверы обычно управляют правами автоматически.
- Для bind mounts на RHEL-подобных системах с SELinux может потребоваться добавить контекст `:z`/`:Z`.

### Шифрование

Docker Swarm не шифрует данные внутри томов нативно. Шифрование должно обеспечиваться:
1. На уровне СХД (шифрование дисков на физических серверах или в хранилищах).
2. На уровне файловой системы (LUKS, fscrypt).
3. Приложениями (шифрование на уровне БД).

Подробнее: **[Шифрование томов](../Docker/Docker_fs/volume_encryption.md)**.

### Важно для Docker 29.x

Docker Engine 29.x вводит breaking changes для legacy (V1) volume plugins. Если кластер использует устаревшие плагины для NFS/iSCSI/SAN, перед обновлением:
1. Проверьте совместимость плагинов с API 1.42+.
2. Выполните обновление всех менеджеров последовательно, затем рабочих узлов.
3. При потере доступа к тому через плагин данные остаются на СХД — требуется перенастройка на `local` driver или миграция на V2 managed plugin.

## Обслуживание и мониторинг

### Очистка неиспользуемых томов

Команда `docker volume prune` работает только **локально** на том узле, где она запущена. Она не удаляет Cluster Volumes, которые видны на уровне всего кластера.

**Алгоритм очистки кластера:**
1. Выполнить `docker volume prune` на всех рабочих узлах (для локальных томов).
2. Использовать `docker volume rm <name>` для удаления Cluster Volumes (с менеджера).
3. Для принудительного освобождения занятого Cluster Volume: `docker volume update --availability drain <name>`, затем удалить.

### Инспекция томов

Для Cluster Volumes инспекция на менеджере даёт информацию о состоянии монтирования:

```bash
docker volume inspect pg_data
# → Ищите секцию "ClusterVolume" с информацией о NodeID и PublishContext
```

### Мониторинг состояния

```bash
docker volume ls --cluster
# → Список кластерных томов со статусом

docker volume inspect pg_data
# → Статус Published (на каком узле примонтирован) или Pending (в процессе переноса)
```

## Операции и команды

| Операция | Локальный том | NFS / CIFS | Cluster Volume (CSI) |
|---|---|---|---|
| **Создание** | `docker volume create --driver local` | `docker volume create --driver local --opt type=nfs ...` | `docker volume create --driver <csi-driver> --type mount ...` |
| **Список** | `docker volume ls` | `docker volume ls` | `docker volume ls --cluster` |
| **Инспекция** | `docker volume inspect <name>` | `docker volume inspect <name>` | `docker volume inspect <name>` |
| **Удаление** | `docker volume rm <name>` | `docker volume rm <name>` | `docker volume rm <name>` (только после `drain`) |
| **Очистка** | `docker volume prune` (на узле) | `docker volume prune` (на узле) | Нет нативного prune; удаление через `rm` |
| **Планирование** | `node.labels.*` constraints | `node.labels.*` constraints | Автоматически по топологии тома |
| **Доступ** | RWO (один контейнер на узле) | RWX (несколько узлов) | RWO / RWX (зависит от СХД) |

## Устранение неполадок

### Том не монтируется

**Проверка:**
1. Доступность сетевого ресурса: `showmount -e <server-ip>` (для NFS).
2. Состояние CSI-плагина: `docker plugin ls` (для Cluster Volumes).
3. Ошибки в логах Docker Engine: `journalctl -u docker -f`.
4. Для NFS: проверьте наличие пакета `nfs-common` (Debian/Ubuntu) или `nfs-utils` (RHEL/CentOS) на **всех** узлах.
5. Для Cluster Volumes: убедитесь, что плагин установлен на всех менеджерах и доступных воркерах.

### Ошибка "volume in use"

Часто возникает при переезде задачи, когда старый контейнер ещё не полностью освободил диск.
- Проверьте статус задач: `docker service ps <service-name>`.
- Убедитесь, что `stop_grace_period` сервиса достаточно для корректного завершения приложения.

### Том "завис" в состоянии Published

Если сервис не запускается, так как том считается занятым другим узлом:
1. Проверьте статус: `docker volume inspect <name>`.
2. Если `NodeID` указывает на узел, который вышел из строя, Swarm может потребоваться до 2–5 минут для автоматического перехвата (timeout).
3. Принудительное освобождение (опасно!): `docker volume update --availability drain <name>`, затем удалить и пересоздать.

### Ошибка "CSI plugin not found"

```bash
# Убедитесь, что плагин включен на ВСЕХ менеджерах
docker plugin ls
# → ID            NAME             ENABLED
# → 123456789abc  csi-nfs:latest   true

# Проверьте логи демона на конкретном воркере
journalctl -u docker | grep -i "csi"
```

### Legacy plugin отказ в Docker 29.x

При обновлении на Docker 29.x legacy (V1) плагины могут потерять доступ к хранилищу:
- Данные остаются на СХД, но Docker не может смонтировать том.
- Решения: downgrade до v26/v27, экспорт данных и перенастройка на `local` driver, или миграция на V2 managed plugin.

### Утечка ресурсов: orphaned тома

При удалении сервиса тома не удаляются автоматически. Проверяйте:
```bash
docker volume ls --filter "dangling=true"
docker volume rm <orphaned-volume>
```

## Дополнительная информация

### Сравнение решений

| Решение | Персистентность | Режим доступа | Сценарий (Use Case) |
|---|---|---|---|
| **Local Volume** | Нет | RWO | Кэш, временные данные, сессии |
| **Bind Mount** | Да (на хосте) | RWO | Разработка, конфиги хоста, логи |
| **NFS / CIFS** | Да | RWX | Общие конфиги, статический контент, медиа |
| **Cluster (CSI)** | Да | RWO / RWX | Базы данных, высоконагруженные stateful-сервисы |

### Лучшие практики

- **Версия Docker:** используйте **29.x** (последний patch release) для стабильной работы CSI и исправления известных багов планировщика.
- **Stateful-приложения:** для БД предпочитайте CSI с поддержкой топологии или привязку к узлу через метки. Используйте `stop_grace_period` для корректного завершения транзакций.
- **NFS:** всегда используйте `nfsvers=4.1` или выше. Добавьте `nolock,soft` для отказоустойчивости. Используйте `nocopy: true` в Compose.
- **Имена томов:** используйте префиксы для томов разных стеков (например, `prod_db_data`), чтобы избежать конфликтов.
- **Очистка:** назначайте ответственного за регулярный `docker volume prune` на рабочих узлах и удаление неиспользуемых Cluster Volumes.
- **Обновление Docker 29.x:** обновляйте менеджеров по одному, затем рабочих узлов. Проверяйте совместимость CSI-плагинов с API 1.42+.

### Смотрите также

- **[Продвинутые тома в Swarm](./swarm_volumes_advanced.md)** — глубокое погружение в CSI, Portworx и Ceph.
- **[Docker Volumes (общее)](../Docker/Docker_fs/docker_volumes.md)** — архитектура томов в Docker.
- **[Развертывание стека](./swarm_stack_deployment.md)** — использование томов в compose-файлах.
- **[Шифрование томов](../Docker/Docker_fs/volume_encryption.md)** — методы защиты данных.
- **[Секреты и конфигурации](./swarm_secrets_configs.md)** — управление неперсистентными чувствительными данными.
- **[Резервное копирование и восстановление](../Docker/Docker_fs/docker_backup_restore.md)** — стратегии бэкапа томов, образов и данных контейнеров.
