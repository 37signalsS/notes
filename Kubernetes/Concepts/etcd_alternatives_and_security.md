# etcd: альтернативы и безопасность

## Определения

**Kine** (Kine Is Not etcd) — прослойка совместимости (shim), транслирующая вызовы API etcd v3 в SQL-запросы к реляционным базам данных. Это позволяет использовать стандартные СУБД (PostgreSQL, MySQL, SQLite) в качестве хранилища состояния кластера Kubernetes без изменения кода самого Control Plane.

**KMS v2** (Key Management Service) — стандарт Kubernetes для интеграции с внешними провайдерами ключей (AWS KMS, GCP KMS, Azure Key Vault, HashiCorp Vault). Начиная с версии 1.29 (GA), KMS v2 является рекомендуемым механизмом для реализации конвертного шифрования (Envelope Encryption) секретов.

**FoundationDB** — высокопроизводительная распределенная база данных, поддерживающая транзакции ACID. Через Kine она может использоваться как замена etcd для кластеров сверхбольшого размера, снимая ограничения на размер БД в 8 ГБ.

**Dqlite** (Distributed SQLite) — отказоустойчивая версия SQLite, использующая алгоритм Raft. Применяется в MicroK8s для создания компактных и надежных edge-кластеров.

**Encryption at Rest** — механизм Kubernetes, реализуемый на уровне `kube-apiserver`, который шифрует данные перед записью в etcd и расшифровывает их при чтении. Конфигурация шифрования задается объектом `EncryptionConfiguration`.

**Envelope Encryption** — схема шифрования, при которой данные шифруются ключом данных (DEK), который в свою очередь зашифрован ключом шифрования данных (KEK). KEK хранится во внешнем KMS, DEK — локально в памяти API-сервера.

---

## Предварительные требования

### Для Kine

*   **Kubernetes:** >= 1.24 (рекомендуется >= 1.28 для стабильного KMS v2)
*   **Kine:** последняя стабильная версия (https://github.com/k3s-io/kine)
*   **Бэкенд:**
    *   SQLite — не требует дополнительного ПО, файл `.db`
    *   PostgreSQL — >= 14 (для `NOTIFY`/`LISTEN`)
    *   MySQL / MariaDB — >= 8.0
*   **Доступ:** прямой доступ к API-серверу для настройки флагов `--storage-backend=kine`

### Для etcd Security

*   **etcd:** >= 3.5 (рекомендуется >= 3.7 для KMS v2 и встроенного шифрования)
*   **Сертификаты:** Собственный CA или интеграция с PKI-инфраструктурой
*   **Клиент:** `etcdctl` версии, совместимой с версией etcd (±1 минорная)
*   **HSM/Vault:** (опционально) для KMS v2 — внешний провайдер ключей

---

## Основные концепции

### Альтернативы etcd: Kine и распределенные БД

Использование Kine оправдано в сценариях, где стандартный etcd либо избыточен по ресурсам, либо не справляется с объемами данных.

| Бэкенд | Сценарий использования | Особенности производительности |
| :--- | :--- | :--- |
| **SQLite** | IoT, Edge (k3s), Local Dev | Минимальный RAM-footprint. Механизм `watch` эмулируется через polling, что неэффективно при >1000 подписок. |
| **PostgreSQL** | Крупные кластеры, vCluster | Масштабируемость до ТБ. Поддерживает нативные уведомления (`NOTIFY`) для эффективного `watch`. |
| **MySQL / MariaDB** | Существующая инфраструктура | Высокая доступность обеспечивается на уровне БД (Galera, Group Replication). |
| **FoundationDB** | Hyperscale (10k+ узлов) | Максимальная пропускная способность на запись. Используется в качестве бэкенда для KubeBrain. |

#### Сравнение Kine и etcd:

*   **Консенсус**: etcd требует кворума Raft (минимум 3 узла). Kine перекладывает задачу консенсуса и отказоустойчивости на саму БД.
*   **Обслуживание**: БД проще мониторить и бэкапить стандартными средствами (pg_dump, MySQL Workbench).
*   **Лимиты**: Kine снимает жесткий лимит etcd на размер файла базы данных, который по умолчанию составляет 2–8 ГБ.
*   **Watch**: etcd использует нативный streaming watch (эффективно). Kine эмулирует через polling (SQLite) или `NOTIFY`/`LISTEN` (PostgreSQL).
*   **Производительность**: etcd оптимизирован для мелких чтений/записей ключей. Kine добавляет оверхед SQL-слоя (10–30% в зависимости от бэкенда).

### Безопасность etcd и хранилищ данных

Защита «мозга» кластера строится на четырех уровнях: сетевом (In-Transit), физическом (At-Rest), прикладном (Audit) и управлении доступом (RBAC).

#### 1. Транспортная безопасность (mTLS)

Все компоненты Control Plane общаются с etcd через **mTLS**.

*   **Сертификаты**: Необходимы отдельные CA для Peer-соединений (между узлами etcd) и Server-соединений (для API Server).
*   **Изоляция**: Порт 2379 должен быть доступен только с IP-адресов Control Plane узлов через Firewall или NetworkPolicies.
*   **Ротация**: Сертификаты должны продлеваться до истечения. kubeadm автоматизирует ротацию через `kubeadm certs renew`.

#### 2. Шифрование на диске (Encryption at Rest)

Секреты в хранилище (etcd или SQL) должны быть зашифрованы, чтобы предотвратить утечку данных при компрометации диска или бэкапа.

**Преимущества KMS v2 (Kubernetes 1.29+):**
*   **Конвертное шифрование (Envelope Encryption)**: Главный ключ (KEK) хранится в HSM/Cloud KMS и шифрует локальные ключи данных (DEK).
*   **Эффективное кэширование**: KMS v2 кэширует зашифрованные DEK, что радикально снижает задержки при массовом чтении секретов.
*   **Статус ключей**: Позволяет проверять состояние ключей в KMS без перезагрузки API-сервера.
*   **Ротация**: Поддерживает автоматическую ротацию KEK. API-сервер прозрачно начинает использовать новый ключ для новых записей.

#### 3. RBAC на уровне etcd

Когда к etcd имеют доступ компоненты помимо `kube-apiserver` (например, Kubernetes Dashboard,TERNAL компоненты), необходимо включать RBAC внутри самого etcd.

*   **Флаги:** `--auth-token`, `--auth-token-cache-ttl`
*   **Роли:** `root` (полный доступ), `readwrite`, `readonly` — разграничение по префиксам ключей (`/registry/...`)
*   **Практика:** По умолчанию etcd доверяет всем клиентам с валидным клиентским сертификатом. В production необходимо явно включать авторизацию.

#### 4. Аудит (Audit Logging)

Kubernetes предоставляет возможность логировать все запросы к API-серверу, включая операции чтения/записи в etcd.

*   **Политика:** Файл `audit-policy.yaml` определяет, какие события логировать (Metadata, Request, RequestResponse).
*   **Бэкенды:** `Log` (файл), `Webhook` (внешний сервис), `BatchWebhook` (пакетная отправка).
*   **Важно:** Аудит затрагивает только запросы к API-серверу. Прямые запросы к etcd (обход API) не логируются — для их отслеживания используется RBAC на уровне etcd и сетевая изоляция.

---

## Практические сценарии

### Анализ состояния кластера через SQL (Kine)

В Kine все объекты хранятся в таблице `kine`. Это позволяет использовать мощь SQL для глубокого аудита, который крайне сложен в бинарном etcd.

```sql
-- Список всех секретов и их размер (если не зашифрованы на уровне API)
SELECT name, length(data) as size 
FROM kine 
WHERE name LIKE '/registry/secrets/%' 
AND deleted = 0 
ORDER BY size DESC;

-- Поиск "осиротевших" подов или ресурсов, созданных более 30 дней назад
SELECT name, created FROM kine 
WHERE deleted = 0 
AND created < (strftime('%s','now') - 2592000);

-- Количество объектов по типам ресурсов
SELECT 
  CASE 
    WHEN name LIKE '/registry/pods/%' THEN 'pods'
    WHEN name LIKE '/registry/services/%' THEN 'services'
    WHEN name LIKE '/registry/secrets/%' THEN 'secrets'
    WHEN name LIKE '/registry/configmaps/%' THEN 'configmaps'
    WHEN name LIKE '/registry/deployments/%' THEN 'deployments'
    ELSE 'other'
  END as resource_type,
  COUNT(*) as count
FROM kine 
WHERE deleted = 0 
GROUP BY resource_type
ORDER BY count DESC;

-- Размер базы данных и статистика
SELECT 
  COUNT(*) as total_keys,
  SUM(LENGTH(data)) as total_data_size,
  MAX(created) as latest_revision
FROM kine 
WHERE deleted = 0;
```

### Миграция с etcd на PostgreSQL через Kine

Пошаговая процедура миграции существующего кластера Kubernetes с etcd на PostgreSQL:

**Этап 1: Подготовка PostgreSQL**
```bash
# Создание базы данных и пользователя
sudo -u postgres psql -c "CREATE USER kine WITH PASSWORD 'secure_password';"
sudo -u postgres psql -c "CREATE DATABASE kine_db OWNER kine;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE kine_db TO kine;"

# Включение расширения pg_stat_statements (для мониторинга)
sudo -u postgres psql -d kine_db -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
```

**Этап 2: Запуск Kine**
```bash
# Пример запуска Kine с PostgreSQL
kine \
  --endpoint="postgres://kine:secure_password@localhost:5432/kine_db?sslmode=disable" \
  --listen-address="0.0.0.0:2379" \
  --tls-cert-file="/etc/etcd/pki/server.crt" \
  --tls-key-file="/etc/etcd/pki/server.key" \
  --client-ca-file="/etc/etcd/pki/ca.crt"
```

**Этап 3: Настройка API-сервера**
```yaml
# В манифесте kube-apiserver.yaml добавить:
--storage-backend=kine
--kine-endpoint="postgres://kine:secure_password@localhost:5432/kine_db?sslmode=disable"
# Убрать старые флаги:
# --etcd-servers=https://127.0.0.1:2379
# --etcd-cafile=...
# --etcd-certfile=...
# --etcd-keyfile=...
```

**Этап 4: Валидация**
```bash
# Проверка, что все объекты доступны
kubectl get pods --all-namespaces
kubectl get secrets --all-namespaces

# Проверка метрик Kine
curl -s http://localhost:2379/metrics | grep kine_api_call_latency
```

### Настройка KMS v2 для Production

Детальная конфигурация `EncryptionConfiguration` с провайдерами KMS v2, aescbc/aesgcm, процедура включения шифрования на работающем кластере, ротация ключей и шпаргалка по `etcdctl` — см. **[Хранение Secret в etcd](../Base/secrets/etcd_storage.md)** (SSoT).

### Резервное копирование и мониторинг

При использовании Kine стратегии обслуживания меняются:

1.  **Бэкап**: Вместо `etcdctl snapshot save` используются нативные инструменты БД:
    *   SQLite: Простое копирование файла `.db` (при использовании `VACUUM INTO` для консистентности).
    *   PostgreSQL: `pg_dump` или WAL-G для инкрементальных бэкапов.
    *   MySQL: `mysqldump` или `xtrabackup` для горячих бэкапов.
2.  **Мониторинг**: Ключевыми метриками становятся:
    *   `kine_api_call_latency_seconds` — задержка трансляции API.
    *   `kine_index_size` — размер индекса в БД.
    *   Задержка репликации на уровне используемой СУБД.

### Диагностика проблем с etcd и Kine

**Симптом: API-сервер не может подключиться к etcd/Kine**
```bash
# Проверка доступности etcd
etcdctl endpoint health --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/etcd/pki/ca.crt \
  --cert=/etc/etcd/pki/server.crt \
  --key=/etc/etcd/pki/server.key

# Проверка Kine (если используется SQL)
curl -s http://localhost:2379/health
# Или через PostgreSQL
psql -U kine -d kine_db -c "SELECT COUNT(*) FROM kine;"

# Проверка логов API-сервера
kubectl logs -n kube-system kube-apiserver-<master> | grep -i "etcd"
```

**Симптом: Высокая задержка чтения секретов (Kine)**
```bash
# Проверка метрик Kine
curl -s http://localhost:2379/metrics | grep kine_api_call_latency

# Проверка размера индекса
psql -U kine -d kine_db -c "SELECT COUNT(*) as keys, pg_size_pretty(pg_database_size('kine_db')) as db_size FROM kine WHERE deleted = 0;"

# Оптимизация SQLite
sqlite3 /var/lib/rancher/k3s/server/db/state.db "PRAGMA optimize; PRAGMA wal_checkpoint(TRUNCATE);"
```

**Симптом: etcd кластер не формирует кворум**
```bash
# Проверка статуса кластера
etcdctl endpoint status --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/etcd/pki/ca.crt \
  --cert=/etc/etcd/pki/server.crt \
  --key=/etc/etcd/pki/server.key --write-out=table

# Проверка member list
etcdctl member list --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/etcd/pki/ca.crt \
  --cert=/etc/etcd/pki/server.crt \
  --key=/etc/etcd/pki/server.key --write-out=table

# Если кластер раз.singleton, принудительное восстановление
etcdctl snapshot restore /backup/snapshot.db --data-dir=/var/lib/etcd-restore
```

### Мониторинг Kine через Prometheus

```yaml
# Пример ServiceMonitor для Kine
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kine-monitor
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: kine
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

---

## Диагностика и типовые ошибки

### Kine

**Ошибка: `watch` не работает корректно (SQLite)**
*   **Причина:** SQLite использует polling вместо нативного `watch`. При большом количестве подписок (>1000) это создает нагрузку.
*   **Решение:** Перейти на PostgreSQL с `NOTIFY`/`LISTEN` или увеличить интервал polling.

**Ошибка: Размер файла SQLite растет бесконтрольно**
*   **Причина:** SQLite не удаляет старые записи автоматически.
*   **Решение:** Настроить `VACUUM` по расписанию или перейти на PostgreSQL.

**Ошибка: Kine не может подключиться к PostgreSQL**
*   **Причина:** Неверный URL подключения, `pg_hba.conf` блокирует доступ, SSL-mode не совпадает.
*   **Решение:** Проверить `pg_hba.conf`, тестовое подключение `psql`, проверить SSL-mode.

### etcd Security

**Ошибка: `certificate has expired or is not yet valid`**
*   **Причина:** Сертификат клиента или сервера истек.
*   **Решение:** Продлить сертификаты через `kubeadm certs renew` или обновить вручную.

**Ошибка: `permission denied` при доступе к etcd**
*   **Причина:** RBAC включен, но клиентский сертификат не имеет необходимых прав.
*   **Решение:** Проверить `--auth-token` флаги, убедиться что сертификат имеет правильный CN/O.

**Ошибка: `key not found` при чтении секрета**
*   **Причина:** Ключ был удален или Encryption Configuration не совпадает с тем, что использовалось при записи.
*   **Решение:** Проверить `EncryptionConfiguration`, убедиться что DEK-провайдер доступен.

**Ошибка: `etcd cluster ID mismatch`**
*   **Причина:** Один из узлов был восстановлен из старого бэкапа с другим ID кластера.
*   **Решение:** Удалить данные на проблемном узле и перезапустить с синхронизацией с кворумом.

---

## Best Practices

### Kine

*   **PostgreSQL предпочтительнее SQLite** для production — нативный `watch`, масштабируемость, HA.
*   **Регулярные бэкапы** через `pg_dump`/`WAL-G` или `mysqldump`/`xtrabackup`.
*   **Мониторинг** через Prometheus: `kine_api_call_latency_seconds`, `kine_index_size`.
*   **Оптимизация SQLite:** `VACUUM` по расписанию, WAL mode для параллельного доступа.
*   **Тестирование миграции:** Перед миграцией production кластера протестировать на staging.

### etcd Security

*   **mTLS обязателен** — все соединения (peer и client) должны быть зашифрованы.
*   **Отдельные CA** для peer и client соединений — компрометация одного CA не влияет на другой.
*   **RBAC на уровне etcd** — включать, когда доступ имеют внешние компоненты.
*   **Сетевая изоляция** — порт 2379 доступен только с Control Plane узлов.
*   **Ротация сертификатов** — автоматическая через kubeadm или ручная до истечения.
*   **Encryption at Rest** — обязателен для секретов, рекомендуется для ConfigMap с чувствительными данными.
*   **KMS v2** — предпочтительнее статических ключей для production.

### Общее

*   **Не использовать etcd напрямую** — всегда через API-сервер или Kine.
*   **Регулярно проверять здоровье** — `etcdctl endpoint health` или SQL-запросы к Kine.
*   **Документировать процедуры** — восстановление из бэкапа, ротация ключей, миграция.
*   **Тестировать backup/restore** — бэкап бесполезен, если не проверено восстановление.

---

## Дополнительная информация

*   **[Обзор etcd в Kubernetes](./etcd_overview.md)** — концептуальная роль etcd в архитектуре.
*   **[Хранение секретов в etcd](../Base/secrets/etcd_storage.md)** — детали реализации иерархии ключей KEK/DEK.
*   **[Безопасность etcd: TLS, RBAC](../../etcd/security.md)** — практические настройки TLS-сертификатов и RBAC.
*   **[Кластеризация etcd](../../etcd/clustering_and_recovery.md)** — построение классического HA-кластера.
