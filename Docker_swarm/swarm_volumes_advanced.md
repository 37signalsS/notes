# Docker Swarm: продвинутые решения для хранения данных

## Определения

**Container Storage Interface (CSI)** — открытый стандарт интерфейса, позволяющий Docker Swarm взаимодействовать с внешними системами хранения (AWS EBS, GCP Persistent Disk, Ceph, NetApp) унифицированным способом. Поддерживается в Swarm начиная с версии 23.0.

**Cluster Volume (Кластерный том)** — тип тома, управляемый через CSI-драйвер. В отличие от обычных томов, Swarm отслеживает состояние кластерных томов на уровне всего кластера, обеспечивая корректное монтирование к узлам в зависимости от их доступности и топологии.

**Distributed Storage (Распределенное хранилище)** — система (например, Ceph, GlusterFS, Portworx), которая объединяет физические диски нескольких узлов в единый логический пул данных с репликацией.

**Storage Topology (Топология хранения)** — информация о физическом расположении узлов и дисков (например, зона доступности в облаке), которую Swarm учитывает при планировании задач для обеспечения доступа к данным.

## Базовые концепции

### Эволюция хранения в Swarm

1. **Legacy (RexRay, Cloudstor):** использование проприетарных плагинов Docker. Большинство из них заброшены или не поддерживают современные версии Docker Engine.
2. **Shared FS (NFS, GlusterFS):** монтирование общей файловой системы. Просто, но создает узкое место по производительности и единую точку отказа.
3. **Modern (CSI):** использование стандартных драйверов. Swarm управляет жизненным циклом тома: `Create -> Validate -> Attach -> Mount`.

### Типы доступа к данным

При использовании продвинутых драйверов (CSI) важно понимать режимы доступа:
- **Single-Writer:** том может быть примонтирован только к одной задаче одновременно.
- **Multi-Writer:** том поддерживает одновременную запись с нескольких узлов (требует распределенной ФС, например CephFS).

### Жизненный цикл кластерного тома

В Swarm Engine 23+ кластерные тома имеют расширенный набор состояний. Команда `docker volume inspect` для таких томов показывает информацию о том, на каком узле (`NodeID`) том примонтирован в данный момент и каков его статус в оркестраторе.

## Практические сценарии

### Использование распределенного хранилища Portworx

Portworx является одним из наиболее мощных решений для Swarm, обеспечивая репликацию на уровне блоков.

#### Создание тома с репликацией

```bash
# Создание тома с тройной репликацией и оптимизацией под БД
docker volume create \
  --driver pxd \
  --opt size=20 \
  --opt repl=3 \
  --opt io_profile=db \
  pg_cluster_data
# → pg_cluster_data
```

#### Использование в Stack-файле

```yaml
version: '3.9'

services:
  database:
    image: postgres:16-alpine
    volumes:
      - pg_cluster_data:/var/lib/postgresql/data
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.labels.storage == portworx

volumes:
  pg_cluster_data:
    external: true
```

### Настройка блочного хранилища через CSI (AWS EBS)

Для работы требуется установленный и настроенный CSI-плагин для конкретного провайдера.

#### Развертывание кластерного тома

В файле `docker-compose.yml` тип тома указывается как `cluster`:

```yaml
version: '3.9'

services:
  app:
    image: nginx:latest
    volumes:
      - type: cluster
        source: cloud_disk
        target: /data
    deploy:
      placement:
        constraints:
          # Привязка к зоне, где создан диск
          - node.labels.topology.ebs.csi.aws.com/zone == us-east-1a

volumes:
  cloud_disk:
    external: true
```

### Резервное копирование и миграция

Для томов, не поддерживающих нативные снапшоты (snapshots) на уровне драйвера, используется метод "Sidecar-контейнера".

#### Создание бэкапа (Backup)

```bash
# Запуск временного контейнера для упаковки данных тома
docker run --rm \
  -v app_persistent_data:/source:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/data_$(date +%Y%m%d).tar.gz -C /source .
# → (создает архив в локальной папке backups)
```

#### Восстановление (Restore)

```bash
# Распаковка данных в новый подготовленный том
docker run --rm \
  -v new_volume:/target \
  -v $(pwd)/backups:/backup \
  alpine sh -c "tar xzf /backup/data_backup.tar.gz -C /target"
# → (данные восстановлены в new_volume)
```

## Дополнительная информация

### Сравнение архитектур хранения

| Параметр | Portworx / Ceph | CSI (Cloud Block) | NFS / GlusterFS |
| :--- | :--- | :--- | :--- |
| **Репликация** | Блочная (синхронная) | На уровне провайдера | Файловая |
| **Производительность** | Очень высокая | Высокая | Средняя/Низкая |
| **RWX (Multi-node)** | Да (Portworx/CephFS) | Обычно нет (RWO) | Да |
| **Сложность** | Высокая | Средняя | Низкая |

### Устранение неисправностей

#### Статус "Volume in use"

Если диск не переключается между узлами:
1. Проверьте состояние задачи: `docker stack ps <stack_name>`.
2. Если старая задача зависла в `Shutdown`, Swarm не сможет примонтировать диск к новой.
3. Используйте `docker volume inspect <volume_name>`, чтобы увидеть, за каким узлом закреплен диск.

#### Проблемы с CSI-драйвером

```bash
# Проверка установленных плагинов
docker plugin ls
# → ID            NAME                          DESCRIPTION                ENABLED
# → abc123def456  aws-ebs-csi-driver:latest     AWS EBS CSI Driver         true

# Проверка системных логов при ошибках монтирования
journalctl -u docker --no-pager | grep -i csi
```

### Смотрите также

- **[Базовое управление томами в Swarm](./swarm_volumes.md)** — основы NFS и локальных томов.
- **[Docker Volumes (общее)](../Docker/Docker_fs/docker_volumes.md)** — архитектура хранилища Docker.
- **[Секреты и конфигурации](./swarm_secrets_configs.md)** — управление неперсистентными данными.
