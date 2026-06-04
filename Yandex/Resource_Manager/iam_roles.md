# Yandex Resource Manager: IAM Роли и права доступа

## 1. Определения

**IAM Roles (Роли и права)** — механизм управления доступом к ресурсам Yandex Cloud через привязку ролей к субъектам (пользователям, сервисным аккаунтам, группам).

**Субъект (Subject)** — пользователь, сервисный аккаунт или группа, которым назначаются роли.

**Access Binding** — привязка роли к субъекту на определённом ресурсе (облако, каталог, сервис).

---

## 2. Базовые концепции

### Системные роли

- **admin** — полное управление ресурсом.
- **editor** — создание и изменение ресурсов.
- **viewer** — только просмотр.
- **usage** — использование ресурсов.

### Сервисные роли

- `compute.admin` — управление Compute Cloud.
- `vpc.admin` — управление сетями.
- `mdb.admin` — управление Managed Databases.
- `storage.admin` — управление Object Storage.

### Принцип минимальных прав

- Назначайте роли на уровне каталога, а не облака.
- Используйте узкие сервисные роли вместо `editor`.
- Разделяйте права для dev/stage/prod окружений.

---

## 3. Практические сценарии

### Создание каталога и базовых прав через yc CLI

```bash
# Предполагается настроенная аутентификация:
# yc init

# Получить ID облака
CLOUD_ID=$(yc resource-manager cloud list --format json | jq -r '.[0].id')
echo "Cloud ID: $CLOUD_ID"

# Создать каталог с метками
FOLDER_ID=$(yc resource-manager folder get --name ci --format json | jq -r '.id' 2>/dev/null || \
  yc resource-manager folder create \
    --name ci \
    --cloud-id "$CLOUD_ID" \
    --labels env=ci,owner=devops,cost-center=infra \
    --format json | jq -r '.id')

echo "Folder ID: $FOLDER_ID"

# Создать сервисный аккаунт для деплоя
SA_ID=$(yc iam service-account get --name sa-deploy --folder-id "$FOLDER_ID" --format json | jq -r '.id' 2>/dev/null || \
  yc iam service-account create \
    --name sa-deploy \
    --folder-id "$FOLDER_ID" \
    --description "CI/CD deployments" \
    --format json | jq -r '.id')

echo "Service Account ID: $SA_ID"

# Назначить минимально необходимые роли
yc resource-manager folder add-access-binding \
  --id "$FOLDER_ID" \
  --role compute.editor \
  --subject serviceAccount:$SA_ID

yc resource-manager folder add-access-binding \
  --id "$FOLDER_ID" \
  --role vpc.editor \
  --subject serviceAccount:$SA_ID

yc resource-manager folder add-access-binding \
  --id "$FOLDER_ID" \
  --role storage.admin \
  --subject serviceAccount:$SA_ID

# Создать API-ключ для сервисного аккаунта
yc iam key create \
  --service-account-id $SA_ID \
  --output key.json \
  --folder-id "$FOLDER_ID"

# Проверка: список привязок
yc resource-manager folder list-access-bindings --id "$FOLDER_ID"
```

### Аудит и мониторинг ресурсов

```bash
# Список всех каталогов с метками
yc resource-manager folder list --format json | jq '.[] | {
  id: .id,
  name: .name,
  labels: .labels,
  cloud_id: .cloud_id
}'

# Поиск каталогов без меток
yc resource-manager folder list --format json | jq '.[] | select(.labels == null or .labels == {}) | .name'

# Список сервисных аккаунтов в каталоге
yc iam service-account list --folder-id <FOLDER_ID>

# Проверка привязок прав
yc resource-manager folder list-access-bindings --id <FOLDER_ID>
```

---

## 4. Дополнительная информация

### Связанные документы

- **[Overview](./overview.md)** — базовые концепции Resource Manager.
- **[Terraform Automation](./terraform_automation.md)** — декларативное управление.
