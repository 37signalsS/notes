# Настройка репликации 389DS

## Определения

**Multi-Master репликация** — архитектура, при которой несколько серверов 389DS содержат синхронизированные копии базы данных. Каждый сервер может принимать записи на изменение.

**Replica ID** — уникальный идентификатор реплики в топологии (1–65535).

**Replication Agreement** — настройка, определяющая параметры синхронизации между двумя серверами.

## Базовые концепции

### Типы репликации

| Тип | Описание | Сценарий |
| :--- | :--- | :--- |
| **Single-Master** | Один master (запись), остальные — consumers (чтение) | Простая HA |
| **Multi-Master** | Несколько master (запись/чтение на всех) | Active-Active HA |
| **Cascading** | Consumer сам становится master для других | Географическое распределение |

### Требования к репликации

* Сетевая связность между серверами (порт 3389/3636)
* DNS-имена или статические IP (ldap01, ldap02)
* Одинаковая версия 389DS на всех серверах
* Синхронизированное время (NTP/Chrony)

## Практические сценарии

### Подготовка серверов

На обоих серверах выполнить:

```bash
# Создать директорию для данных
mkdir -p /data/ldap

# Запустить контейнер
docker run -d \
  --name 389ds \
  -p 3389:3389 \
  -p 3636:3636 \
  -v /data/ldap:/data \
  --memory=2g \
  -e SUFFIX=dc=test,dc=local \
  -e DM_PASSWORD=password \
  -e DS_REINDEX=true \
  quay.io/389ds/ds-container:latest

# Проверить статус
docker logs -f 389ds
```

### Создание backend

На **каждом** сервере:

```bash
docker exec 389ds dsconf backend create \
  --suffix "dc=test,dc=local" \
  --be-name user-root \
  --create-suffix
```

Проверка:

```bash
docker exec 389ds dsconf backend suffix list
```

### Включение репликации

#### Сервер 1 (ldap01, Replica ID: 1)

```bash
docker exec 389ds dsconf replica enable \
  --suffix "dc=test,dc=local" \
  --role supplier \
  --replica-id 1 \
  "cn=replication manager,cn=config" \
  --password password
```

#### Сервер 2 (ldap02, Replica ID: 2)

```bash
docker exec 389ds dsconf replica enable \
  --suffix "dc=test,dc=local" \
  --role supplier \
  --replica-id 2 \
  "cn=replication manager,cn=config" \
  --password password
```

### Создание replication agreement

#### На ldap01 (агрейт на ldap02)

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

#### На ldap02 (агрейт на ldap01)

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

На любом сервере:

```bash
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

**Ключевые параметры:**

* `Replication Enabled` — репликация включена
* `Last Update` — время последней синхронизации
* `Replica Status` — статус (online/offline, ошибки)

## Дополнительная информация

### Troubleshooting

| Проблема | Решение |
| :--- | :--- |
| `Error: Can't contact LDAP server` | Проверить сеть, firewall, статус контейнера |
| `Replica not in sync` | Выполнить `dsconf repl-agmt init` |
| `Conflict DN` | Проверить логи репликации, использовать `dsconf repl-conflict` |

### Логи репликации

```bash
# Включить логирование репликации
docker exec 389ds dsconf config set \
  --add-nsslapd-errorlog-level "replication"

# Просмотр логов
docker exec 389ds tail -f /var/log/dirsrv/slapd-*/errors
```

### Best Practices

1. **Минимум 2 сервера** для HA
2. **Replica ID** должны быть уникальны в топологии
3. **Конфигурация (`cn=config`) не реплицируется** — настраивать на каждом сервере отдельно
4. **Мониторинг:** отслеживать `Last Update` и ошибки репликации
5. **Тестирование:** проверять репликацию изменений перед production

### Рекомендуемая последовательность развёртывания

1. Запустить 389DS в Docker на отдельных машинах
2. Настроить кластер и репликацию
3. Протестировать failover
4. Перенести конфигурацию в Kubernetes (опционально)
5. Создать Helm chart для повторяемости

### Связанные темы

* [Docker развёртывание](./docker.md)
* [Kubernetes развёртывание](./k8s_deploy/basic_concepts.md)
* [Плагины](./plugins.md)
* [Безопасность](./overview.md#Безопасность)
