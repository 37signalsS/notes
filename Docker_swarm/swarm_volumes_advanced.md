# Docker Swarm: продвинутые решения для хранения данных

## Определения

**Container Storage Interface (CSI)** — открытый стандарт интерфейса, позволяющий Docker Swarm взаимодействовать с внешними системами хранения (AWS EBS, GCP Persistent Disk, Ceph, NetApp) унифицированным способом. Поддерживается в Swarm начиная с версии 23.0.

**Cluster Volume (Кластерный том)** — тип тома, управляемый через CSI-драйвер. В отличие от обычных томов, Swarm отслеживает состояние кластерных томов на уровне всего кластера, обеспечивая корректное планирование задач в зависимости от доступности тома и его топологии. Требует предварительного создания.

**Access Mode (Режим доступа)** — комбинация параметров `Scope` (один или несколько узлов) и `Sharing` (один или несколько сервисов/задач), определяющая, как том может быть примонтирован.
- **Single-Writer (RWO):** том примонтирован к одной задаче.
- **Multi-Writer (RWX):** одновременная запись с нескольких узлов (требует поддержки на уровне СХД).

**Accessibility / Topology (Топология)** — информация о физическом расположении (регион, зона доступности), используемая планировщиком Swarm для размещения контейнера там, где физически доступен диск.

**Distributed Storage (Распределенное хранилище)** — система (например, Ceph, GlusterFS, Portworx), объединяющая диски нескольких узлов в единый пул с репликацией данных.

## Базовые концепции

### Эволюция хранения в Swarm

1. **Legacy (плагины Docker):** Использование драйверов вроде RexRay или Cloudstor. Большинство признаны устаревшими и не рекомендуются для новых инсталляций.
2. **Shared FS (NFS/CIFS):** Монтирование общей сетевой папки. Просто в настройке, но создает единую точку отказа и задержки в производительности.
3. **Modern (CSI и Cluster Volumes):** Стандарт для Docker 23.0+. Swarm управляет полным жизненным циклом тома: `Create (на менеджере) -> Validate -> Attach -> Mount (на воркере)`.

### Жизненный цикл кластерного тома

В отличие от локальных томов, кластерные тома являются объектами первого класса в Swarm (как сервисы или секреты):
1. **Установка плагина:** CSI-плагин должен быть установлен на каждом узле кластера.
2. **Создание тома:** Выполняется один раз через CLI менеджера.
3. **Планирование:** При запуске сервиса SwarmKit проверяет `RequiredTopology` тома и `NodeLabels` узлов, выбирая подходящий узел.
4. **Управление состоянием:** `docker volume cluster inspect` показывает статус `Published` (на каком узле примонтирован) и `Pending` (в процессе переноса).

### Новое в Docker 27.0

- **Subpath support:** Возможность монтировать конкретную поддиректорию внутри CSI-тома (`volume.subpath` в CLI и Compose).
- **Улучшенная стабильность планировщика:** Исправлены ошибки «зависания» томов в состоянии `Shutdown` при быстрой перезагрузке сервисов.

## Практические сценарии

### Управление кластерными томами через CLI

Начиная с Docker 23.0, для работы с CSI-томами используется группа команд `docker volume cluster`.

#### Создание тома (например, AWS EBS)

```bash
docker volume create \
  --driver ebs.csi.aws.com \
  --type cluster \
  --availability active \
  --scope single-node \
  --sharing none \
  --limit size=20Gi \
  --required-topology region=us-east-1,zone=us-east-1a \
  pg_data_cluster
# → pg_data_cluster
```

#### Просмотр и инспекция

```bash
# Список только кластерных томов
docker volume cluster ls
# → ID            NAME               DRIVER              SCOPE        SHARING      STATUS
# → abc123def     pg_data_cluster    ebs.csi.aws.com     single-node  none         created

# Детальная информация и статус монтирования
docker volume cluster inspect pg_data_cluster
# → Находим секцию "PublishContext" с ID узла, где том активен
```

### Использование в Stack-файле (Compose 3.10+)

Для использования CSI-томов в `docker-compose.yml` необходимо указать `type: cluster` в секции монтирования сервиса.

```yaml
version: '3.10'

services:
  database:
    image: postgres:16-alpine
    volumes:
      - type: cluster
        source: pg_cluster_data
        target: /var/lib/postgresql/data
        # subpath: "data-v1"  # Доступно в Docker 27.0+
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.role == worker

volumes:
  pg_cluster_data:
    external: true # Если создан заранее через CLI
    # Или динамическое описание (если драйвер поддерживает):
    # cluster:
    #   spec:
    #     access_mode:
    #       scope: single
    #       sharing: none
```

### Резервное копирование и миграция

Для томов без нативной поддержки снапшотов используется "Sidecar-метод" или временные сервисы.

#### Бэкап кластерного тома через временный сервис

```bash
docker service create \
  --name backup_task \
  --restart-condition none \
  --mount type=cluster,src=pg_cluster_data,dst=/source,readonly \
  --mount type=bind,src=/mnt/backups,dst=/backup \
  alpine tar czf /backup/pg_data_$(date +%Y%m%d).tar.gz -C /source .
# → (Swarm сам найдет узел с томом и запустит там задачу бэкапа)
```

## Дополнительная информация

### Сравнение архитектур хранения

| Параметр | Cluster Volumes (CSI) | Распределенные ФС (Ceph/NFS) | Локальные тома |
| :--- | :--- | :--- | :--- |
| **Управление** | Нативное в Swarm | Внешнее монтирование | Автоматическое (на узле) |
| **Топология** | Учитывается планировщиком | Игнорируется (доступно везде) | Ограничено одним узлом |
| **Производительность** | Блочный доступ (Высокая) | Файловый/Сетевой (Средняя) | Максимальная (Direct I/O) |
| **Переносимость** | Автоматический переезд | Статичное монтирование | Ручной перенос данных |

### Устранение неисправностей

#### Том "завис" в состоянии монтирования (Published)

Если сервис не запускается, так как том считается занятым другим узлом:
1. Проверьте статус: `docker volume cluster inspect <name>`.
2. Если `NodeID` указывает на узел, который вышел из строя, Swarm может потребоваться до 2–5 минут для автоматического перехвата (timeout).
3. Принудительное освобождение (опасно!): `docker volume cluster update --availability drain <name>`, затем обратно в `active`.

#### Ошибка "CSI plugin not found"

```bash
# Убедитесь, что плагин включен на ВСЕХ узлах
docker plugin ls
# → ID            NAME             ENABLED
# → 123456789abc  csi-nfs:latest   true

# Проверьте логи демона на конкретном воркере
journalctl -u docker | grep -i "csi"
```

### Смотрите также

- **[Базовое управление томами в Swarm](./swarm_volumes.md)** — основы NFS и локальных томов.
- **[Docker Volumes (общее)](../Docker/Docker_fs/docker_volumes.md)** — архитектура хранилища Docker.
- **[Секреты и конфигурации](./swarm_secrets_configs.md)** — управление неперсистентными данными.
- **[Продвинутые возможности CSI в Kubernetes](../Kubernetes/Storage/CSI/csi_advanced.md)** — сравнение реализации.
