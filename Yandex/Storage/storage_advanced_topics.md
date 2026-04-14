# Yandex Storage: Дополнительные темы

## Определения

**IAM-политики** — правила управления доступом к ресурсам Yandex Cloud через привязку ролей к субъектам (пользователям, [сервисным аккаунтам](../Resource_Manager/iam_roles.md#субъекты-iam)).

**SSE-S3 / SSE-KMS** — шифрование на стороне сервера: SSE-S3 использует управляемые ключи Yandex Cloud, SSE-KMS — ключи из сервиса [KMS](../Resource_Manager/overview.md), предоставляя контроль над ключами шифрования.

**Приватный доступ** — подключение к хранилищам через VPC без выхода в интернет, с использованием [Security Groups](../VPC.md#security-groups) для контроля трафика.

---

## Основные концепции

### Интеграции

Object Storage используется для хранения Docker-образов в [частных реестрах](../../Docker/docker_overview.md#реестры). Block Storage и File Storage выступают источником [Persistent Volumes](../../Kubernetes/) для stateful-нагрузок. Декларативное управление всеми хранилищами — через [Terraform](../../Concepts/iac_overview.md) и провайдер `yandex`.

### Безопасность

| Механизм | Что защищает | Подробности |
| :--- | :--- | :--- |
| **IAM-политики** | Доступ к бакетам, дискам, снапшотам | Роли `storage.admin`, `storage.editor`, `storage.viewer` — [IAM roles](../Resource_Manager/iam_roles.md) |
| **SSE-S3** | Данные Object Storage at rest | Автоматическое, без дополнительной настройки |
| **SSE-KMS** | Данные Object Storage at rest | Свои ключи, аудит использования, ротация через KMS |
| **Security Groups** | Сетевой доступ к File Storage | Правила ingress/egress на L3/L4 для NFS-эндпоинтов |
| **Приватный эндпоинт** | Object Storage без публичного интернета | Через VPC, без NAT, изоляция от внешней сети |

**Шифрование в транзите:** все хранилища поддерживают HTTPS/TLS. Object Storage требует явного указания `--endpoint-url https://` в aws-cli.

---

## Практические сценарии

### IAM: выдача доступа сервисному аккаунту к бакету

```bash
# Создать сервисный аккаунт
yc iam service-account create --name ci-deployer
SA_ID=$(yc iam service-account get --name ci-deployer --format json | jq -r .id)

# Назначить роль storage.editor на каталог
yc resource-manager folder add-access-binding \
  --id <folder_id> \
  --subject serviceAccount:$SA_ID \
  --role storage.editor
```

### SSE-KMS: шифрование бакета своим ключом

```bash
# Создать ключ KMS
yc kms symmetric-key create --name storage-key --default-algorithm aes-256
KEY_ID=$(yc kms symmetric-key get --name storage-key --format json | jq -r .id)

# Создать бакет с KMS-шифрованием
cat <<EOF > bucket-config.json
{
  "SSEAlgorithm": "aws:kms",
  "KMSMasterKeyID": "$KEY_ID"
}
EOF

aws s3api put-bucket-encryption \
  --bucket my-secure-bucket \
  --server-side-encryption-configuration '{"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": "'$KEY_ID'"}}]}' \
  --endpoint-url https://storage.yandexcloud.net
```

### Security Groups: ограничение доступа к File Storage

```bash
# Разрешить NFS (порт 2049) только из подсети ВМ
yc vpc security-group-rule create \
  --security-group-name fs-access \
  --rule-name allow-nfs-from-app-subnet \
  --direction ingress \
  --protocol TCP \
  --port 2049 \
  --cidr 10.0.1.0/24
```

---

## Дополнительная информация

### Best Practices

**Object Storage:**

- Lifecycle-политики: удалять старые версии через 30–90 дней, архивы — переводить в Cold Storage через 180 дней ([пример](./storage_practical_scenarios.md#object-storage-версионирование-и-lifecycle))
- Версионирование: обязательно для production-бакетов с артефактами и бэкапами
- Префиксы: использовать иерархию `releases/<version>/`, `backups/<db>/<date>/` для оптимизации запросов
- Multipart upload: для файлов >100 МБ (макс. chunk — 5 ГБ, рекомендуемый — 100 МБ)

**Block Storage:**

- Снапшоты — перед обновлениями ОС, миграциями, изменениями конфигурации; удалять через 7–14 дней после подтверждения стабильности
- Тип диска: `network-ssd` для БД и latency-критичных приложений, `network-hdd` для логов и архивов
- `/etc/fstab`: обязательное авто-монтирование с опцией `nofail` для graceful boot

**File Storage:**

- Использовать для общих данных между ВМ (конфиги, медиа-библиотеки, шаринг между микросервисами)
- Бэкапы: снапшоты файлового хранилища + копирование в Object Storage для offsite-хранения
- Мониторинг: алерт на заполнение >80%, контроль IOPS через [Yandex Monitoring](../Monitoring/index.md)

### Актуальная информация (2025–2026)

- **Object Storage:** добавлен класс Cold Storage (Q4 2025) — минимальная стоимость, доступ за часы, для архивов и долгосрочного хранения
- **Block Storage:** новый тип `network-ssd-readonly` (Q3 2025) — до 20 000 IOPS, мульти-аттач для реплик БД и статических данных
- **Лимиты:** увеличено до 100 бакетов на каталог (ранее — 50)

Связанные темы: определения и типы хранилищ — [Storage concepts](./storage_concepts.md), практические сценарии — [Storage practical scenarios](./storage_practical_scenarios.md), обзор хранилищ — [Storage index](./index.md).
