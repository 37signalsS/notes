# Docker Swarm: Volumes Management

## Определения

**Local Volume** — стандартный Docker-том, данные которого хранятся на файловой системе одного конкретного узла Swarm. По умолчанию используется в Swarm-сервисах.

**Persistent Volume** — том, данные которого сохраняются при перемещении контейнеров между узлами кластера. Требует использования сетевых файловых систем или storage plugins.

**Storage Plugin** — плагин для интеграции Docker с внешними системами хранения (Ceph, Portworx, AWS EBS), обеспечивающий персистентность данных в распределенной среде.

## Базовые концепции

### Проблема персистентности в Swarm

По умолчанию тома в Docker Swarm являются **локальными**. Это создает проблему при перемещении задач между узлами:

```
[Узел 1] → [Том: /var/lib/docker/volumes/data]
    ↓ (миграция задачи)
[Узел 2] → [Том: ПУСТО]
```

Если задача сервиса переносится на другой узел (сбой, масштабирование), данные в локальном томе становятся недоступны. Это делает стандартные Docker-тома непригодными для stateful-приложений (БД, очереди) без дополнительных решений.

### Подходы к решению

#### Сетевые файловые системы (NFS)

**Принцип:** Монтирование общей NFS-шары на все узлы Swarm.

| Преимущества | Ограничения |
|---|---|
| Простота реализации | Низкая производительность для I/O-intensive workload |
| Подходит для конфигов, статического контента | Единая точка отказа (без HA-NFS) |
| Не требует дополнительных плагинов | Ручное управление вне Docker |

**Использование:**

```yaml
volumes:
  nfs-data:
    driver: local
    driver_opts:
      type: nfs
      o: addr=nfs-server.example.com,rw
      device: ":/path/to/share"
```

#### Storage Plugins (Volume Drivers)

**Принцип:** Использование плагинов для интеграции с распределенными системами хранения.

| Преимущества | Ограничения |
|---|---|
| Высокая доступность | Сложность настройки |
| Автоматическое управление томами | Накладные расходы |
| Устойчивость к отказам узлов | Требует инфраструктуру |
| Нативная интеграция с Docker | |

**Популярные решения:** Portworx, RexRay, Ceph RBD, AWS EBS, Azure Disk.

Подробнее о продвинутых решениях — в **[swarm_volumes_advanced.md](./swarm_volumes_advanced.md)**.

#### Bind Mounts

**Принцип:** Монтирование пути с хоста в контейнер.

**Ограничения в Swarm:**

- Путь должен существовать на **всех** узлах
- Не рекомендуется для production
- Подходит для конфигурационных файлов

```yaml
services:
  app:
    volumes:
      - /etc/app/config:/etc/app/config:ro
```

## Практические сценарии

### NFS для общих данных

#### Настройка NFS-тома

```yaml
version: '3.8'

services:
  web:
    image: nginx:1.26.3
    deploy:
      replicas: 3
    volumes:
      - nfs-content:/usr/share/nginx/html

volumes:
  nfs-content:
    driver: local
    driver_opts:
      type: nfs
      o: addr=nfs.example.com,rw,nfsvers=4.1
      device: ":/srv/docker/swarm/web-content"
```

**Требования:**

- NFS-сервер доступен со всех узлов Swarm
- Установлен NFS-клиент (`nfs-common` на Ubuntu/Debian)
- Открыты порты NFS (2049 TCP/UDP)

#### Проверка подключения

```sh
# Проверить монтирование на узле
mount | grep nfs

# Протестировать доступность
docker run --rm -v nfs-content:/data alpine ls /data
```

### Local Volume с placement constraints

Для приложений, где данные могут быть локальными:

```yaml
version: '3.8'

services:
  cache:
    image: redis:7
    volumes:
      - cache-data:/data
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.labels.cache-node == true

volumes:
  cache-data:
    driver: local
```

**Сценарий использования:** Кэширование, где потеря данных допустима.

**Установка метки:**

```sh
docker node update --label-add cache-node=true node-1
```

### Troubleshooting

#### Том не монтируется

**Проверка:**

```sh
# Проверить доступность NFS
showmount -e nfs-server.example.com

# Проверить драйвер тома
docker volume inspect nfs-content

# Проверить логи
docker service logs <service>
```

**Возможные причины:**

- NFS-сервер недоступен
- Неправильный путь (`device: ":/path"`)
- Firewall блокирует порты NFS

#### Данные не сохраняются

**Проверка:**

```sh
# Проверить монтирование внутри контейнера
docker exec <container> mount | grep data

# Проверить права доступа
docker exec <container> ls -la /data
```

**Возможные причины:**

- Неправильные права на NFS-шаре
- Том создан на другом узле
- Storage plugin не запущен

#### Ошибка "volume not found"

**Проверка:**

```sh
# Список томов на узле
docker volume ls

# Проверить external-том
docker volume inspect postgres-data
```

**Решение:** Для external-томов убедитесь, что том создан до развертывания стека.

## Дополнительная информация

### Сравнение решений

| Решение | Персистентность | Сложность | Стоимость | Use Case |
|---|---|---|---|---|
| **Local Volume** | Нет | Низкая | Бесплатно | Cache, temp data |
| **NFS** | Да | Средняя | Низкая | Configs, static content |
| **Storage Plugins** | Да | Высокая | Средняя/Высокая | Production БД |

### Лучшие практики

- **Stateful-приложения:** Используйте storage plugins или NFS с HA
- **Базы данных:** Требуют персистентных томов с репликацией
- **Кэши:** Допустимы local volumes с placement constraints
- **Бэкапы:** Регулярно создавайте снимки томов

### Связанные документы

- **Docker Volumes (общее)** — **[../Docker/Docker_fs/docker_volumes.md](../Docker/Docker_fs/docker_volumes.md)**
- **Data Storage в Dockerfile** — **[../Docker/Dockerfile/Instructions/data_storage.md](../Docker/Dockerfile/Instructions/data_storage.md)**
- **Stack Deployment** — **[swarm_stack_deployment.md](./swarm_stack_deployment.md)**
- **Продвинутые тома** — **[swarm_volumes_advanced.md](./swarm_volumes_advanced.md)**
