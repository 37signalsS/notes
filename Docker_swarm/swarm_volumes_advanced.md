# Docker Swarm: Advanced Volumes

## Storage Plugins

### Portworx

Portworx — распределенное хранилище для контейнеров с поддержкой репликации и снимков.

#### Настройка Portworx

```sh
# Установить Portworx на все узлы
# (требует предварительной настройки дисков)

# Создать том через Portworx
docker volume create \
  --driver pxd \
  --opt size=20 \
  --opt repl=3 \
  postgres-data
```

**Параметры:**
- `size` — размер тома в GB
- `repl` — количество реплик (1–3)
- `io_profile` — профиль I/O (`db`, `cms`, `default`)

#### Использование в сервисе

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15
    volumes:
      - postgres-data:/var/lib/postgresql/data
    deploy:
      placement:
        constraints:
          - node.labels.db == true

volumes:
  postgres-data:
    external: true
```

**Преимущества:**
- Репликация данных (repl=3)
- Автоматическое восстановление
- Снимки (snapshots)
- Миграция между узлами

### RexRay

RexRay — универсальный драйвер для облачных провайдеров и локальных хранилищ.

#### Настройка RexRay

```sh
# Установить RexRay на все узлы
curl -sSL https://rexray.io/install | sh

# Настроить /etc/rexray/config.yml
storageDrivers:
  - ebs
EBS:
  region: us-east-1
```

#### Создание тома

```sh
docker volume create \
  --driver rexray/ebs \
  --name ebs-volume \
  --opt size=50
```

#### Использование в стеке

```yaml
version: '3.8'

services:
  database:
    image: postgres:15
    volumes:
      - ebs-volume:/var/lib/postgresql/data
    deploy:
      placement:
        constraints:
          - node.labels.region == us-east-1

volumes:
  ebs-volume:
    external: true
```

**Важно:** EBS-томы привязаны к AZ (Availability Zone). Ограничьте placement узлами в той же зоне.

## Cloud Storage Solutions

### AWS EBS

#### Требования

- EC2-инстансы с IAM-ролью для доступа к EBS
- RexRay или Docker Volume Plugin для EBS
- Все узлы в одном регионе (или одном AZ для томов)

#### Конфигурация

```yaml
version: '3.8'

services:
  db:
    image: postgres:15
    volumes:
      - ebs-data:/var/lib/postgresql/data
    deploy:
      placement:
        constraints:
          - node.labels.az == us-east-1a

volumes:
  ebs-data:
    driver: rexray/ebs
    driver_opts:
      size: 100
      type: gp3
      fsType: ext4
```

**Ограничения:**
- EBS-том может быть подключен только к одному узлу одновременно
- Для multi-attach используйте EFS (NFS-like)

### Azure Disk

#### Настройка

```sh
# Установить RexRay с Azure драйвером
curl -sSL https://rexray.io/install | sh -s -- --driver azure

# Настроить Azure credentials
export AZURE_TENANT_ID=<tenant>
export AZURE_CLIENT_ID=<client>
export AZURE_CLIENT_SECRET=<secret>
export AZURE_SUBSCRIPTION_ID=<subscription>
```

#### Использование

```yaml
volumes:
  azure-disk:
    driver: rexray/azure
    driver_opts:
      size: 50
      storageaccounttype: Premium_LRS
```

### Google Persistent Disk

```sh
# Установить RexRay с GCP драйвером
curl -sSL https://rexray.io/install | sh -s -- --driver gce

# Требуется service account с правами на Compute Engine
```

```yaml
volumes:
  gcp-disk:
    driver: rexray/gce
    driver_opts:
      size: 100
      type: pd-ssd
```

## Backup и восстановление

### Создание бэкапа

#### Через временный контейнер

```sh
# Бэкап NFS-тома
docker run --rm \
  -v nfs-content:/source:ro \
  -v /backup:/backup \
  alpine tar czf /backup/content-backup.tar.gz /source
```

#### Снимок Portworx

```sh
# Создать снимок
pxctl volume snapshot <volume-id> --name backup-$(date +%Y%m%d)

# Список снимков
pxctl volume snapshot list <volume-id>
```

### Восстановление из бэкапа

#### Из tar-архива

```sh
# Восстановить данные
docker run --rm \
  -v nfs-content:/target \
  -v /backup:/backup \
  alpine tar xzf /backup/content-backup.tar.gz -C /target
```

#### Из снимка Portworx

```sh
# Создать новый том из снимка
pxctl volume create --snapshot <snapshot-id> restored-volume
```

### Автоматизация бэкапов

```yaml
version: '3.8'

services:
  backup:
    image: alpine
    volumes:
      - db-data:/source:ro
      - backup-storage:/backup
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        tar czf /backup/db-backup-$(date +%Y%m%d).tar.gz /source
        find /backup -name "*.tar.gz" -mtime +7 -delete
    deploy:
      schedule: "0 2 * * *"  # Ежедневно в 02:00
```

## Troubleshooting

### Portworx проблемы

**Проверка статуса:**
```sh
# Статус кластера Portworx
pxctl status

# Информация о томе
pxctl volume inspect <volume-id>

# Логи Portworx
journalctl -u portworx
```

**Частые проблемы:**

| Проблема | Решение |
|---|---|
| Том не создается | Проверить доступные диски |
| Репликация не работает | Проверить сеть между узлами |
| Том не монтируется | Перезапустить Portworx |

### RexRay проблемы

**Проверка:**
```sh
# Проверить конфигурацию
rexray config view

# Проверить драйвер
docker volume ls --driver rexray/ebs

# Логи RexRay
journalctl -u rexray
```

### Cloud-specific issues

#### AWS EBS

| Проблема | Решение |
|---|---|
| Volume in use | EBS не поддерживает multi-attach (кроме io1/io2) |
| AZ mismatch | Том и узел должны быть в одном AZ |
| Permission denied | Проверить IAM-роль |

#### Azure Disk

| Проблема | Решение |
|---|---|
| Authentication failed | Проверить service account |
| Disk already attached | Azure Disk не поддерживает multi-attach |

## Сравнение решений

| Решение | Персистентность | HA | Сложность | Стоимость |
|---|---|---|---|---|
| **Portworx** | Да | Да | Высокая | Средняя |
| **RexRay EBS** | Да | Нет* | Средняя | Высокая |
| **RexRay Azure** | Да | Нет* | Средняя | Высокая |
| **NFS** | Да | Нет** | Низкая | Низкая |

*Требуется дополнительная настройка для HA
**Требуется HA-NFS кластер

## Связанные документы

- **Базовое управление томами** — **[swarm_volumes.md](./swarm_volumes.md)**
- **Docker Volumes** — **[../Docker/Docker_fs/docker_volumes.md](../Docker/Docker_fs/docker_volumes.md)**
- **Stack Deployment** — **[swarm_stack_deployment.md](./swarm_stack_deployment.md)**
