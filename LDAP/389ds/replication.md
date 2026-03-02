# Настройка репликации 389DS

## Репликация Multi-Master

Для обеспечения высокой доступности настраивается репликация между несколькими экземплярами 389DS. Рассматривается кластер из двух узлов (master-master).

### Предварительные требования

* Две машины с Docker/Podman
* Сетевая связность между машинами
* DNS-имена серверов (ldap01, ldap02)
* Директория для данных: `mkdir -p /data/ldap`

### Запуск контейнеров на обеих нодах

```bash
docker run -d \
  --name 389ds \
  -p 3389:3389 \
  -p 3636:3636 \
  -v /data/ldap:/data \
  --memory=2g \
  -e SUFFIX=dc=test,dc=local \
  -e DM_PASSWORD=password \
  -e DS_REINDEX=true \
  389ds/ds-container:latest
```

### Проверка статуса серверов

```bash
# На каждом сервере проверить список backends
docker exec 389ds dsconf backend suffix list
```

### Создание backend (выполнить на обеих нодах)

```bash
docker exec 389ds dsconf backend create \
  --suffix "dc=test,dc=local" \
  --be-name user-root \
  --create-suffix
```

### Включение репликации

#### На первом сервере (ldap01)

```bash
docker exec 389ds dsconf replica enable \
  --suffix "dc=test,dc=local" \
  --role supplier \
  --replica-id 1 \
  "cn=replication manager,cn=config" \
  --password password
```

#### На втором сервере (ldap02)

```bash
docker exec 389ds dsconf replica enable \
  --suffix "dc=test,dc=local" \
  --role supplier \
  --replica-id 2 \
  "cn=replication manager,cn=config" \
  --password password
```

### Создание replication agreement

#### На ldap01 (к ldap02)

```bash
docker exec 389ds dsconf repl-agmt create \
  --suffix "dc=test,dc=local" \
  --host-name ldap02 \
  --port 3389 \
  --bind-method simple \
  --bind-dn "cn=replication manager,cn=config" \
  --password password \
  me-to-ldap02
```

#### На ldap02 (к ldap01)

```bash
docker exec 389ds dsconf repl-agmt create \
  --suffix "dc=test,dc=local" \
  --host-name ldap01 \
  --port 3389 \
  --bind-method simple \
  --bind-dn "cn=replication manager,cn=config" \
  --password password \
  me-to-ldap01
```

### Инициализация репликации

```bash
# На любом сервере
docker exec 389ds dsconf repl-agmt init \
  --suffix "dc=test,dc=local" \
  me-to-ldap02
```

### Проверка статуса репликации

```bash
docker exec 389ds dsconf replication status \
  --suffix "dc=test,dc=local" \
  me-to-ldap02
```

Ключевые параметры:
* `Replication Enable` — репликация включена
* `Last Update` — время последней синхронизации
* `Replica Status` — статус синхронизации

> **Примечание:** Конфигурация серверов (cn=config) не реплицируется — каждый сервер имеет собственную конфигурацию.

> **Рекомендуемая последовательность:**
> 1. Запустить 389DS в Docker на отдельных машинах
> 2. Настроить кластер и репликацию
> 3. Перенести работающую конфигурацию в Kubernetes
> 4. Создать Helm chart для повторяемости
