# Yandex Storage

## Определения

**Object Storage** — S3-совместимое хранилище для неструктурированных данных: артефактов сборок, бэкапов, статики, логов, медиафайлов.

**Block Storage** — сетевые диски для виртуальных машин в Compute Cloud. Предоставляют блочный доступ с низкой задержкой.

**File Storage** — управляемое NFS-хранилище для общего доступа к файлам из нескольких ВМ.

---

## Основные концепции

### Сравнение типов хранилищ

| Тип | Интерфейс | Характеристики | Сценарии |
| :--- | :--- | :--- | :--- |
| **Object Storage** | S3 API (HTTP/REST) | Версионирование, lifecycle-политики, высокая доступность (99.999999999%) | Артефакты CI/CD, бэкапы, статика, логи, медиа |
| **Block Storage** | Блочное устройство (/dev/vdb) | Низкая задержка (<1 мс), снимки, онлайн-расширение | Загрузочные диски, БД, /var/lib/docker |
| **File Storage** | POSIX/NFS v4 | Общий доступ многим ВМ, POSIX-семантика | Общие тома приложений, медиа-библиотеки, профильные данные |

### Object Storage

**Ключевые возможности:**
- **S3-совместимость** — работа через aws-cli, boto3, s3cmd
- **Версионирование** — хранение всех версий объектов
- **Lifecycle-политики** — автоматическое удаление или переход в холодное хранение
- **Публичный доступ** — статические сайты, CDN
- **Шифрование** — на стороне сервера (SSE-S3, SSE-KMS)

**Классы хранения:**
| Класс | Стоимость | Доступ | Сценарии |
| :--- | :--- | :--- | :--- |
| **Standard** | Базовая | Мгновенный | Активные данные, частый доступ |
| **Infrequent Access** | Ниже | Мгновенный | Редкий доступ, бэкапы |
| **Cold Storage** | Минимальная | Часы | Архивы, долгосрочное хранение |

**Лимиты:**
- Макс. размер объекта: 5 ГБ (один запрос), 5 ТБ (multipart upload)
- Макс. количество бакетов на каталог: 100
- Макс. размер бакета: неограничен

### Block Storage (диски)

**Типы дисков:**

| Тип | IOPS | Пропускная способность | Задержка | Сценарии |
| :--- | :--- | :--- | :--- | :--- |
| **network-ssd** | До 10 000 | До 300 МБ/с | <1 мс | БД, системы реального времени |
| **network-ssd-nonreplicated** | До 50 000 | До 600 МБ/с | <0.5 мс | Критичные к задержкам БД |
| **network-hdd** | До 200 | До 100 МБ/с | ~10 мс | Файловые серверы, архивы |
| **network-ssd-readonly** | До 20 000 | До 400 МБ/с | <1 мс | Реплики БД, статические данные |

**Возможности:**
- **Снимки (snapshots)** — резервные копии дисков
- **Онлайн-расширение** — увеличение размера без остановки ВМ
- **Мульти-аттач** (для network-ssd-readonly) — подключение к нескольким ВМ

**Лимиты:**
- Макс. размер диска: 4 ТБ (network-ssd), 8 ТБ (network-hdd)
- Макс. количество снапшотов: 100 на диск
- Макс. IOPS на ВМ: зависит от платформы (до 120 000)

### File Storage

**Характеристики:**
- Протокол: NFS v4
- Пропускная способность: до 1 ГБ/с
- IOPS: до 10 000
- Макс. размер: до 10 ТБ

**Сценарии:**
- Общие каталоги для микросервисов
- Медиа-библиотеки для веб-приложений
- Профильные данные пользователей
- Shared storage для CI/CD

---

## Практические сценарии

### Object Storage: создание бакета и загрузка

```bash
# Создание бакета
aws s3api create-bucket \
  --bucket my-artifacts \
  --endpoint-url https://storage.yandexcloud.net \
  --create-bucket-configuration LocationConstraint=ru-central1

# Загрузка артефакта
aws s3 cp build.tar.gz s3://my-artifacts/releases/ \
  --endpoint-url https://storage.yandexcloud.net

# Загрузка с ACL (публичный доступ)
aws s3 cp index.html s3://my-artifacts/static/ \
  --acl public-read \
  --endpoint-url https://storage.yandexcloud.net

# Синхронизация директории
aws s3 sync ./dist s3://my-artifacts/www/ \
  --endpoint-url https://storage.yandexcloud.net
```

### Object Storage: версионирование и lifecycle

```bash
# Включение версионирования
aws s3api put-bucket-versioning \
  --bucket my-artifacts \
  --versioning-configuration Status=Enabled \
  --endpoint-url https://storage.yandexcloud.net

# Lifecycle-политика: удаление старых версий через 30 дней
cat <<EOF > lifecycle.json
{
  "Rules": [
    {
      "ID": "DeleteOldVersions",
      "Status": "Enabled",
      "Filter": {"Prefix": "releases/"},
      "NoncurrentVersionExpiration": {"NoncurrentDays": 30}
    }
  ]
}
EOF

aws s3api put-bucket-lifecycle-configuration \
  --bucket my-artifacts \
  --lifecycle-configuration file://lifecycle.json \
  --endpoint-url https://storage.yandexcloud.net
```

### Object Storage: статический сайт

```bash
# Настройка website hosting
aws s3api put-bucket-website \
  --bucket my-artifacts \
  --website-configuration '{
    "IndexDocument": {"Suffix": "index.html"},
    "ErrorDocument": {"Key": "404.html"}
  }' \
  --endpoint-url https://storage.yandexcloud.net

# Публичный доступ к объектам
aws s3api put-bucket-policy \
  --bucket my-artifacts \
  --policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Sid": "PublicRead",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::my-artifacts/*"
    }]
  }' \
  --endpoint-url https://storage.yandexcloud.net

# URL сайта: https://my-artifacts.storage.yandexcloud.net
```

### Block Storage: создание и подключение диска

```bash
# Создание диска
yc compute disk create \
  --name data-disk \
  --type network-ssd \
  --size 50 \
  --zone ru-central1-a

# Подключение к ВМ
yc compute instance attach-disk \
  --instance-name app-vm \
  --disk-name data-disk \
  --mode r/w \
  --auto-delete

# Внутри ВМ: форматирование и монтирование
sudo mkfs.ext4 /dev/vdb
sudo mkdir /data
sudo mount /dev/vdb /data
echo '/dev/vdb /data ext4 defaults 0 2' | sudo tee -a /etc/fstab
```

### Block Storage: снимки дисков

```bash
# Создание снапшота
yc compute disk snapshot create \
  --disk-name data-disk \
  --name data-snapshot-$(date +%Y%m%d)

# Список снапшотов
yc compute snapshot list

# Создание диска из снапшота
yc compute disk create \
  --name restored-disk \
  --source-snapshot-name data-snapshot-20260301 \
  --size 50 \
  --zone ru-central1-a

# Удаление снапшота
yc compute snapshot delete --name data-snapshot-20260301
```

### File Storage: создание и монтирование

```bash
# Создание файлового хранилища
yc vpc filesystem create \
  --name shared-fs \
  --type nfs \
  --size 100 \
  --zone ru-central1a

# Монтирование на ВМ
sudo mkdir /shared
sudo mount -t nfs4 \
  <filesystem_endpoint>:/ /shared

# Авто-монтирование
echo '<filesystem_endpoint>:/ /shared nfs4 defaults 0 0' | sudo tee -a /etc/fstab
```

### Бэкапы Managed DB в Object Storage

```bash
# Экспорт бэкапа PostgreSQL в S3
pg_dump -h <db_host> -U app app | \
  aws s3 cp - s3://my-artifacts/backups/pg-$(date +%Y%m%d).sql.gz \
  --endpoint-url https://storage.yandexcloud.net

# Автоматизация через cron
cat <<EOF | sudo tee /etc/cron.daily/db-backup
#!/bin/bash
BACKUP_FILE="pg-backup-$(date +%Y%m%d-%H%M).sql.gz"
pg_dump -h <db_host> -U app app | gzip | \
  aws s3 cp - s3://my-artifacts/backups/$BACKUP_FILE \
  --endpoint-url https://storage.yandexcloud.net
EOF

sudo chmod +x /etc/cron.daily/db-backup
```

### Интеграция с CI/CD

**GitLab CI пример:**

```yaml
stages:
  - build
  - deploy

build:
  stage: build
  script:
    - docker build -t app:$CI_COMMIT_SHA .
    - docker push registry.example.com/app:$CI_COMMIT_SHA
    - aws s3 cp build.tar.gz s3://my-artifacts/releases/$CI_COMMIT_SHA.tar.gz \
      --endpoint-url https://storage.yandexcloud.net

deploy:
  stage: deploy
  script:
    - aws s3 cp s3://my-artifacts/releases/$CI_COMMIT_SHA.tar.gz . \
      --endpoint-url https://storage.yandexcloud.net
    - tar xzf $CI_COMMIT_SHA.tar.gz
    - ./deploy.sh
```

---

## Дополнительная информация

### Связанные документы

- **[Compute Cloud](./Compute-Cloud.md)** — диски для ВМ
- **[Managed Databases](./Managed-Databases.md)** — бэкапы БД
- **[CI/CD](../CI-CD/artifact_management.md)** — управление артефактами

### Интеграции

- **[Docker](../Docker/docker_overview.md)** — хранение образов в Object Storage
- **[Kubernetes](../Kubernetes/)** — Persistent Volumes из Block/File Storage
- **[Terraform](../Concepts/iac_overview.md)** — декларативное управление хранилищами

### Безопасность

- **IAM-политики** — доступ к бакетам и дискам
- **Шифрование** — SSE-S3, SSE-KMS для Object Storage
- **Security Groups** — сетевой доступ к File Storage
- **Приватный доступ** — через VPC без выхода в интернет

### Best Practices

**Object Storage:**
- Используйте lifecycle-политики для экономии
- Включайте версионирование для критичных данных
- Применяйте префиксы для организации объектов
- Используйте multipart upload для файлов >100 МБ

**Block Storage:**
- Делайте снапшоты перед обновлениями
- Используйте SSD для БД и latency-критичных приложений
- Монтируйте диски через /etc/fstab для авто-подключения

**File Storage:**
- Используйте для общих данных между ВМ
- Настраивайте backup через снапшоты
- Мониторьте использование места

### Актуальная информация (2025–2026)

- **Object Storage:** добавлен класс Cold Storage (Q4 2025)
- **Block Storage:** новые типы network-ssd-readonly (Q3 2025)
- **Лимиты:** увеличены до 100 бакетов на каталог
