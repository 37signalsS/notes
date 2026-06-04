# Yandex Storage: Практические сценарии

## 1. Определения

**Практические сценарии** — пошаговые команды и конфигурации для работы с [Object Storage](./storage_concepts.md#1-определения), [Block Storage](./storage_concepts.md#1-определения) и [File Storage](./storage_concepts.md#1-определения) через aws-cli и yc CLI.

Инструменты: [aws-cli](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) (S3-совместимый API), [yc CLI](https://yandex.cloud/ru/docs/cli/quickstart) (нативный CLI Yandex Cloud).

---

## 2. Базовые концепции

### Группировка по типу хранилища

Сценарии разделены по типу хранилища и задаче:

- **Объектное хранилище (Object Storage)** — создание бакетов, загрузка объектов, версионирование, жизненные циклы (lifecycle), статические сайты.
- **Блочное хранилище (Block Storage)** — создание дисков, подключение к ВМ, снимки, восстановление.
- **Файловое хранилище (File Storage)** — создание NFS-хранилищ, монтирование.
- **Кросс-сервисные сценарии** — бэкапы Managed DB в Object Storage, интеграция с CI/CD.

### Общие требования

- Для aws-cli: параметр `--endpoint-url https://storage.yandexcloud.net` обязателен.
- Для yc CLI: требуется предварительная авторизация через `yc init`.
- IAM-роли и сервисные аккаунты — см. [Дополнительные темы](./storage_advanced_topics.md).
- Определения и характеристики хранилищ — [Основные концепции](./storage_concepts.md).

---

## 3. Практические сценарии

### Объектное хранилище: создание бакета и загрузка

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

### Объектное хранилище: версионирование и жизненные циклы

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

### Объектное хранилище: статический сайт

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
```

### Блочное хранилище: создание и подключение диска

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

### Блочное хранилище: снимки дисков

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

### Файловое хранилище: создание и монтирование

```bash
# Создание файлового хранилища
yc vpc filesystem create \
  --name shared-fs \
  --type nfs \
  --size 100 \
  --zone ru-central1-a

# Монтирование на ВМ
sudo mkdir /shared
sudo mount -t nfs4 \
  <filesystem_endpoint>:/ /shared

# Авто-монтирование
echo '<filesystem_endpoint>:/ /shared nfs4 defaults 0 0' | sudo tee -a /etc/fstab
```

### Бэкапы баз данных в объектное хранилище

```bash
# Экспорт бэкапа PostgreSQL в S3
pg_dump -h <db_host> -U app app | \
  aws s3 cp - s3://my-artifacts/backups/pg-$(date +%Y%m%d).sql.gz \
  --endpoint-url https://storage.yandexcloud.net
```

---

## 4. Дополнительная информация

- **[Основные концепции](./storage_concepts.md)** — характеристики и лимиты хранилищ.
- **[Дополнительные темы](./storage_advanced_topics.md)** — безопасность и шифрование.
- **[Compute Cloud](../Compute-Cloud.md)** — управление дисками виртуальных машин.
