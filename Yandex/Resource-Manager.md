# Yandex Cloud DevOps - Resource Manager

## Автоматизация развертываний: Yandex Resource Manager

Yandex Resource Manager — сервис управления иерархией ресурсов Yandex Cloud и доступами к ним. Он определяет базовые сущности для DevOps-практик: облако (cloud), каталоги (folders), метки (labels) и привязки прав (access bindings). От корректной автоматизации на этом уровне зависит воспроизводимость сред, минимальные права для CI/CD и единые политики по проектам.

## Ключевые понятия и роль в DevOps

- **Облако** — верхний уровень изоляции с единым биллингом и квотами.
- **Каталог** — логическая единица развертывания. Чаще всего соответствует окружению или продукту: dev, test, prod.
- **Метки** — пары ключ–значение для группировки, поиска, биллинга и политик.
- **Привязки прав** — назначение ролей субъектам (сервисные аккаунты, пользователи, группы) на уровне облака или каталога.

Для автоматизации важны идемпотентность (повторный запуск не меняет итогового состояния), декларативность (Terraform) и минимально необходимые права (роль на уровне каталога вместо облака, узкие сервисные роли вместо editor).

## Паттерны автоматизации

- Разделение окружений по каталогам. Каждый каталог — отдельный контур развертывания и доступа.
- Bootstrap «сквозь» сервисный аккаунт. CI/CD работает от имени сервисного аккаунта с ограниченными ролями.
- Политики доступа декларативно. Роли оформляются как код (Terraform), а не вручную через консоль.
- Метки как обязательный атрибут. Все каталоги и ресурсы снабжаются метками env, owner, cost-center для прозрачного управления и учета.

### Сравнение подходов

| Подход | Когда использовать | Преимущества | Риски |
|--------|-------------------|--------------|-------|
| CLI (yc) | Быстрый bootstrap, скрипты в CI | Простота, минимум зависимостей | Сложнее обеспечить идемпотентность |
| Terraform | Постоянные среды, контроль дрейфа | Декларативность, план/апплай, аудит | Требует управления состоянием |
| API/SDK | Кастомные инструменты | Тонкий контроль, интеграции | Усложнение разработки |

## Примеры автоматизации

Создание каталога и базовых прав через yc:

```bash
# Предполагается настроенная аутентификация через ключ сервисного аккаунта:
# export YC_SERVICE_ACCOUNT_KEY_FILE=key.json

# Идентификатор облака
CLOUD_ID=$(yc resource-manager cloud list --format json | jq -r '.[0].id')

# Создать каталог с метками, если не существует
yc resource-manager folder get --name ci || \
yc resource-manager folder create --name ci --cloud-id "$CLOUD_ID" \
  --labels env=ci,owner=devops

FOLDER_ID=$(yc resource-manager folder get --name ci --format json | jq -r '.id')

# Сервисный аккаунт для деплоя
yc iam service-account create --name sa-deploy --folder-id "$FOLDER_ID" \
  --description "CI/CD deployments" || true
SA_ID=$(yc iam service-account get --name sa-deploy --format json | jq -r '.id')

# Роли минимум необходимых прав
yc resource-manager folder add-access-binding --id "$FOLDER_ID" \
  --role editor --subject serviceAccount:$SA_ID
```

Декларативное описание тех же объектов в Terraform:

```hcl
variable "cloud_id" { type = string }

provider "yandex" {
  cloud_id                  = var.cloud_id
  folder_id                 = yandex_resourcemanager_folder.ci.id
  service_account_key_file  = "key.json"
}

resource "yandex_resourcemanager_folder" "ci" {
  cloud_id = var.cloud_id
  name     = "ci"
  labels = {
    env   = "ci"
    owner = "devops"
  }
}

resource "yandex_iam_service_account" "deploy" {
  name        = "sa-deploy"
  folder_id   = yandex_resourcemanager_folder.ci.id
  description = "CI/CD deployments"
}

resource "yandex_resourcemanager_folder_iam_binding" "deploy_editor" {
  folder_id = yandex_resourcemanager_folder.ci.id
  role      = "editor"
  members   = ["serviceAccount:${yandex_iam_service_account.deploy.id}"]
}
```

Фрагмент скрипта для пайплайна, гарантирующий контекст перед деплоем:

```bash
export YC_SERVICE_ACCOUNT_KEY_FILE="$CI_PROJECT_DIR/key.json"
yc config set cloud-id "$CLOUD_ID"
yc config set folder-id "$FOLDER_ID"

# Проверка доступов и меток каталога
yc resource-manager folder get --id "$FOLDER_ID" --format json | jq -e '.labels.env=="ci"'
```

Такая настройка позволяет CI/CD-процессам работать в правильно изолированных каталогах, использовать метки для учёта и управлять доступами как кодом.
