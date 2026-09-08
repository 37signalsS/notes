# RGW (RADOS Gateway): S3-совместимое хранилище на базе Ceph

Документ охватывает развертывание, настройку и эксплуатацию Object Gateway (RGW) в кластере Ceph. RGW предоставляет S3-compatible и Swift-compatible API для объектного хранения. Является справочником для DevOps/SRE/sysadmin, работающих с объектными хранилищами в продуктовых средах. Актуально для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

---

## Определения

**RADOS Gateway (RGW)** — HTTP/HTTPS шлюз, предоставляющий S3-compatible и Swift-compatible API поверх объектного хранилища RADOS. Позволяет приложениям, использующим AWS S3 SDK, работать с Ceph без изменений кода.

**Bucket (Бакет)** — контейнер для объектов в S3-модели. Бакет привязан к пользователю и имеет глобально уникальное имя в пределах одного RGW-эндпоинта. Внутри бакета объекты хранятся как объекты RADOS в выделенном пуле.

**Object (Объект)** — базовая единица хранения в S3. Объект состоит из данных (body), метаданных (headers) и уникального ключа (key) внутри бакета. Максимальный размер объекта: 5 ТБ.

**User (Пользователь)** — учётная запись RGW с уникальным Access Key и Secret Key. Пользователь привязан к тенанту (tenant) и имеет квоты на количество бакетов и объём данных.

**Subuser (Подпользователь)** — учётная запись для доступа к Swift API. Привязывается к S3-пользователю и имеет собственные права доступа.

**Quota (Квота)** — ограничение на максимальный объём данных (max_bytes) и количество объектов (max_objects) для пользователя или бакета.

**Lifecycle (Жизненный цикл)** — политика автоматической очистки или перехода объектов между уровнями хранения по возрасту или другим условиям.

**Versioning (Версионирование)** — механизм хранения всех версий объекта. Позволяет восстанавливать удалённые или изменённые объекты.

**Replication (Репликация)** — синхронная или асинхронная репликация бакетов между кластерами RGW для отказоустойчивости и географического распределения.

---

## Базовые концепции

### Архитектура RGW

```
Клиент (S3 SDK / aws-cli / s3cmd)
        │ HTTPS (порт 7480/443)
        ▼
   RGW (RADOS Gateway)
        │ librados
        ▼
   RADOS (объектное хранилище)
        │
        ▼
   OSD (физические диски)
```

**Компоненты:**
- **RGW Daemon** — HTTP/HTTPS сервер, обрабатывающий запросы S3/Swift API
- **RGW Zone** — логическая единица в multisite-конфигурации (сайт)
- **RGW Zone Group** — группа зон в пределах одного региона
- **RGW Region** — географический регион, объединяющий несколько zone groups

### Пулы RGW

RGW автоматически создает несколько пулов для хранения данных:

| Пул | Назначение | Тип |
|-----|-----------|-----|
| `rgw.root` | Корневые метаданные | Replicated |
| `<zone>.rgw.meta` | Метаданные пользователей и бакетов | Replicated |
| `<zone>.rgw.log` | Журнал операций | Replicated |
| `<zone>.rgw.data` | Данные объектов | Replicated или EC |

> **Рекомендация:** Для данных RGW можно использовать EC-пулы (см. [Erasure Coding](./ceph_erasure_coding.md)) для экономии места при хранении холодных данных.

### S3 API Compatibility

RGW поддерживает большинство API S3:

| API | Поддержка | Примечание |
|-----|-----------|------------|
| Object CRUD (GET/PUT/DELETE) | Полная | Включая multipart upload |
| Bucket operations | Полная | Create, Delete, List, Head |
| Versioning | Полная | Все версии объектов |
| Lifecycle | Полная | Автоматическая очистка |
| CORS | Полная | Настройка правил |
| Notification | Базовая | MQTT, AMQP, HTTP |
| Replication | Полная | Синхронная/асинхронная |
| Encryption (SSE-S3, SSE-C) | Полная | Шифрование на стороне сервера |
| Object Lock (WORM) | Полная | Compliance mode |
| Select (S3 Select) | Базовая | SQL-запросы к объектам |

### Порт RGW

| Режим | Порт по умолчанию | Примечание |
|-------|-------------------|------------|
| HTTP | 7480 | Для development |
| HTTPS | 443 (или 7443) | Для production |
| Ingress (HA) | 80/443 | Keepalived + HAProxy |

---

## Практические сценарии

### 1. Развертывание RGW через cephadm

#### 1.1 Простой RGW (один экземпляр)

```bash
# Создание RGW-сервиса
ceph orch apply rgw default --placement="1 ceph-rgw1"

# Проверка
ceph orch ps --daemon-type rgw
ceph orch ls --service_type rgw
```

#### 1.2 HA RGW с Ingress (Keepalived + HAProxy)

```bash
# Шаг 1: Создание RGW-сервиса на нескольких узлах
ceph orch apply rgw myrgw --placement="3 ceph-rgw1 ceph-rgw2 ceph-rgw3"

# Шаг 2: Добавление Ingress (VIP + балансировка)
ceph orch apply ingress rgw.myrgw \
  --virtual-ip 10.0.0.100/24 \
  --frontend-port 80 \
  --backend-port 7480

# Проверка
ceph orch ps --service_type ingress
# → haproxy и keepalived демоны активны
```

#### 1.3 Декларативная спецификация (service spec)

```yaml
# rgw-spec.yaml
service_type: rgw
service_id: myrgw
placement:
  hosts:
    - ceph-rgw1
    - ceph-rgw2
    - ceph-rgw3
spec:
  frontend_port: 7480
  # Опционально: SSL
  # ssl_certificate: /etc/ceph/ssl/rgw.crt
  # ssl_key: /etc/ceph/ssl/rgw.key
```

```bash
ceph orch apply -i rgw-spec.yaml
```

### 2. Управление пользователями S3

#### 2.1 Создание пользователя

```bash
# Создание S3-пользователя
radosgw-admin user create \
  --uid="app-user" \
  --display-name="Application User" \
  --email="app@example.com"

# → Вывод включает:
# →   "user_id": "app-user"
# →   "access_key": "AKIAIOSFODNN7EXAMPLE"
# →   "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

# Создание с явным указанием ключей
radosgw-admin user create \
  --uid="backup-user" \
  --display-name="Backup Service" \
  --access-key="AKIAIOSFODNN7BACKUP" \
  --secret-key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYBACKUPKEY"
```

#### 2.2 Управление ключами

```bash
# Просмотр ключей пользователя
radosgw-admin user info --uid="app-user" | grep -A5 keys

# Создание нового ключа
radosgw-admin key create --uid="app-user" --key-type=s3

# Удаление ключа
radosgw-admin key rm --uid="app-user" --key="AKIAIOSFODNN7EXAMPLE"

# Сброс всех ключей
radosgw-admin user rm --uid="app-user" --purge-data
# → Danger! Пересоздать пользователя:
radosgw-admin user create --uid="app-user" --display-name="Application User"
```

#### 2.3 Управление правами доступа (caps)

```bash
# Просмотр прав
radosgw-admin user info --uid="app-user" | grep caps

# Добавление прав на чтение всех бакетов
radosgw-admin user modify --uid="app-user" \
  --caps="users=read"

# Ограничение доступа к конкретному бакету
radosgw-admin user modify --uid="app-user" \
  --caps="buckets=read,write"
```

### 3. Управление квотами

```bash
# Установка квоты на пользователя (10 ГБ, 1000 объектов)
radosgw-admin user modify --uid="app-user" \
  --max-bytes=10737418240 \
  --max-objects=1000

# Установка квоты на бакет
radosgw-admin bucket modify --bucket="my-bucket" \
  --max-bytes=5368709120

# Просмотр квоты пользователя
radosgw-admin user stats --uid="app-user" | grep -A5 quota

# Просмотр статистики бакета
radosgw-admin bucket stats --bucket="my-bucket"
```

### 4. Версионирование

```bash
# Включение версионирования на бакете
aws s3api put-bucket-versioning \
  --bucket my-bucket \
  --versioning-configuration Status=Enabled \
  --endpoint-url http://rgw-endpoint:7480

# Просмотр версий объекта
aws s3api list-object-versions \
  --bucket my-bucket \
  --prefix myfile.txt \
  --endpoint-url http://rgw-endpoint:7480

# Восстановление удалённой версии
aws s3api copy-object \
  --bucket my-bucket \
  --key myfile.txt \
  --copy-source "my-bucket/myfile.txt+version-id123" \
  --endpoint-url http://rgw-endpoint:7480
```

### 5. Lifecycle policies

```json
// lifecycle.json
{
  "Rules": [
    {
      "ID": "archive-old-logs",
      "Status": "Enabled",
      "Prefix": "logs/",
      "Expiration": {
        "Days": 30
      },
      "Transitions": [
        {
          "Days": 7,
          "StorageClass": "GLACIER"
        }
      ]
    }
  ]
}
```

```bash
# Применение политики
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-bucket \
  --lifecycle-configuration file://lifecycle.json \
  --endpoint-url http://rgw-endpoint:7480

# Просмотр политики
aws s3api get-bucket-lifecycle-configuration \
  --bucket my-bucket \
  --endpoint-url http://rgw-endpoint:7480
```

### 6. Тестирование S3 API

```bash
# Конфигурация aws-cli
aws configure set aws_access_key_id AKIAIOSFODNN7EXAMPLE
aws configure set aws_secret_access_key wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
aws configure set default.region us-east-1

# Создание бакета
aws s3 mb s3://my-test-bucket --endpoint-url http://rgw-endpoint:7480

# Загрузка файла
aws s3 cp myfile.txt s3://my-test-bucket/ --endpoint-url http://rgw-endpoint:7480

# Список объектов
aws s3 ls s3://my-test-bucket/ --endpoint-url http://rgw-endpoint:7480

# Загрузка директории
aws s3 sync ./my-data s3://my-test-bucket/data/ --endpoint-url http://rgw-endpoint:7480

# Удаление бакета
aws s3 rb s3://my-test-bucket --force --endpoint-url http://rgw-endpoint:7480
```

### 7. Мониторинг RGW

```bash
# Просмотр метрик RGW
curl -s http://localhost:9283/metrics | grep rgw

# Статистика по пользователю
radosgw-admin user stats --uid="app-user"

# Статистика по бакету
radosgw-admin bucket stats --bucket="my-bucket"

# Просмотр логов RGW
ceph orch logs --service=rgw.myrgw

# Активные подключения
radosgw-admin client list
```

### 8. Multisite репликация ( Disaster Recovery)

```bash
# Настройка master-зона
radosgw-admin zone create --rgw-zone=us-east-1 --rgw-zonegroup=us \
  --endpoints=http://rgw-master:7480 --master

radosgw-admin zonegroup modify --rgw-zonegroup=us --master

radosgw-admin period update --commit

# Настройка replica-зона (на втором кластере)
radosgw-admin zone create --rgw-zone=us-west-1 --rgw-zonegroup=us \
  --endpoints=http://rgw-replica:7480

# Синхронизация
radosgw-admin sync status
```

---

## Диагностика

| Проблема | Симптом | Причина | Решение |
|----------|---------|---------|---------|
| `403 Forbidden` | Доступ запрещён | Неверный ключ, нет прав | Проверить access_key/secret_key, caps |
| `404 Not Found` | Бакет/объект не найден | Несуществующий ключ илиbucket | Проверить имя, region, endpoint |
| `500 Internal Error` | Внутренняя ошибка сервера | OSD down, PG degraded | `ceph health detail`, проверить OSD |
| `RequestTimeout` | Таймаут запроса | Медленные OSD, сеть | `ceph osd perf`, проверить cluster_network |
| `Slow Ops` | RGW отвечает медленно | Перегрузка, recovery | `ceph -w`, ограничить recovery |
| `Quota Exceeded` | Квота превышена | Лимит объектов/байтов | `radosgw-admin user modify --max-bytes=...` |

---

## Дополнительная информация

### RGW vs MinIO vs AWS S3

| Критерий | Ceph RGW | MinIO | AWS S3 |
|----------|----------|-------|--------|
| **Хранение** | RADOS (распределённое) | Локальные диски | Облачное |
| **Масштабирование** | Горизонтальное (PB+) | Горизонтальное | Неограниченное |
| **S3 API** | Полная совместимость | Полная совместимость | Оригинал |
| **Erasure Coding** | Да (нативно) | Да | Нет (3AZ) |
| **Стоимость** | Открытый код | Открытый код | Pay-as-you-go |
| **Интеграция с K8s** | Rook-Ceph | MinIO Operator | AWS EKS |
| **Multisite** | Да (zones) | Да (replication) | да (CRR) |

### Лучшие практики

- **Всегда используйте HTTPS** для клиента RGW в production
- **Разделяйте пользователей** для разных приложений (минимальные привилегии)
- **Включайте версионирование** для критичных данных
- **Настраивайте квоты** для предотвращения заполнения кластера
- **Используйте lifecycle policies** для автоматической очистки старых данных
- **Мониторьте `radosgw-admin user stats`** для контроля использования
- **Для HA** разворачивайте минимум 2 RGW + Ingress (Keepalived + HAProxy)

### См. также

- [Обзор Ceph](./ceph_overview.md) — архитектура RADOS
- [Erasure Coding](./ceph_erasure_coding.md) — экономичное хранение для данных RGW
- [Администрирование Ceph](./Administration/index.md) — управление кластером
- [Операции Ceph](./Administration/operations.md) — создание сервисов RGW
- [Мониторинг Ceph](./Administration/monitoring.md) — метрики RGW
