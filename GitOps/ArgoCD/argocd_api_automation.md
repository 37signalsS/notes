# ArgoCD: Автоматизация через API и Ansible

**ArgoCD** предоставляет мощный набор API (REST и gRPC) для полной автоматизации жизненного цикла приложений. Использование Ansible в связке с API обеспечивает декларативный подход к управлению конфигурацией самого ArgoCD, позволяя интегрировать GitOps-процессы в существующие CI/CD пайплайны.

> **Актуальность (2026):** ArgoCD API remains the recommended automation interface. Начиная с v2.4+, REST API стабилен и документирован. CLI-клиент использует gRPC по умолчанию, но поддерживает REST через флаг `--grpc-web`. Проект активно поддерживается, выпускаются регулярные релизы с исправлениями безопасности.

## Предварительные требования

1. **ArgoCD установлен и доступен:** REST API (`https://<argocd-url>/api/v1/`) и gRPC (`<argocd-url>:443`) доступны.
2. **CLI установлен:** `argocd` CLI v2.x+ для командной строки. Установка: `brew install argocd` (macOS) или [документация](https://argo-cd.readthedocs.io/en/stable/cli_installation/).
3. **Ansible установлен:** `ansible` и `ansible-galaxy` для управления через плейбуки.
4. **Учетные данные:** Service Account с RBAC-ролями или временная сессия для аутентификации.

## Определения

- **ArgoCD REST API** — HTTP-интерфейс (JSON) для управления всеми ресурсами ArgoCD (Applications, Projects, Clusters, Repositories). Доступен на `/api/v1/`.
- **ArgoCD gRPC API** — высокопроизводительный бинарный интерфейс (HTTP/2), используемый CLI-клиентом по умолчанию. Основан на protobuf-схемах.
- **Service Account (SA)** — специальный тип аккаунта в ArgoCD для программного доступа, не привязанный к конкретному пользователю. Рекомендуемый метод для CI/CD.
- **API Token** — JWT-токен (JSON Web Token) для аутентификации запросов. Генерируется из Service Account.
- **Ansible Collection `argoproj.argocd`** — официальный набор модулей для управления ресурсами ArgoCD без написания HTTP-запросов.
- **API Scope** — область видимости API-токена (read, write, create, delete). Определяется RBAC-политиками.

## Базовые концепции

### Архитектура API-взаимодействия

```
┌─────────────────────────────────────────────────────────────────────┐
│          ArgoCD API: Архитектура автоматизации                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │  CI/CD       │    │  ArgoCD API  │    │  Kubernetes  │          │
│  │  System      │───▶│  Server      │───▶│  Cluster     │          │
│  │  (GitHub     │    │  (REST/gRPC) │    │  (App CRDs)  │          │
│  │   Actions)   │    └──────────────┘    └──────────────┘          │
│  └──────────────┘           │                    ▲                   │
│         │                   ▼                    │                   │
│         │            ┌──────────────┐           │                   │
│         │            │  Application │           │                   │
│         └───────────▶│  Controller  │───────────┘                   │
│                      └──────────────┘                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Методы аутентификации

Для программного взаимодействия требуется токен доступа. В современных версиях ArgoCD (v2.0+) рекомендуется использовать **Service Accounts**.

#### 1. Сервисные аккаунты (Service Accounts)
Это предпочтительный метод для CI/CD систем.
1. **Создание SA:** Добавьте аккаунт в `argocd-cm` ConfigMap.
   ```yaml
   data:
     accounts.github-actions: apiKey
   ```
2. **Назначение прав:** В `argocd-rbac-cm` свяжите аккаунт с ролью.
   ```yaml
   data:
     policy.csv: |
       p, role:ci-bot, applications, sync, *, allow
       g, github-actions, role:ci-bot
   ```
3. **Генерация токена:**
   ```bash
   argocd account generate-token --account github-actions
   ```

#### 2. Временная сессия (User Session)
Используется для разовых задач от имени пользователя.
```bash
curl -s -X POST $ARGOCD_SERVER/api/v1/session \
  -d '{"username":"admin","password":"password"}' | jq -r .token
```

#### 3. OIDC Token (SSO)
Для интеграции с корпоративными SSO-системами:
```bash
curl -s -X POST $ARGOCD_SERVER/api/v1/session \
  -d '{"username":"user@example.com","password":"sso-password","issuer":"https://gitlab.example.com"}' | jq -r .token
```

### Сравнение протоколов: REST vs gRPC

| Протокол | Назначение | Особенности | Клиенты |
| :--- | :--- | :--- | :--- |
| **REST (HTTP/JSON)** | Интеграция с внешними скриптами, cURL, Ansible. | Прост в использовании, работает через стандартные HTTP-клиенты. | cURL, wget, Python requests, Go net/http |
| **gRPC (HTTP/2)** | Внутреннее взаимодействие, работа через `argocd` CLI. | Высокая производительность, требует protobuf-схем. | argocd CLI, Go gRPC, Python grpcio |

*Примечание: Если ArgoCD находится за прокси-сервером, не поддерживающим HTTP/2, используйте флаг `--grpc-web` в CLI или REST API.*

### API версии

| Версия | Описание | Доступность |
| :--- | :--- | :--- |
| **v1** | Основная версия API | `/api/v1/` — стабильна, рекомендуется |
| **v2** | Экспериментальная | `/api/v2/` — может измениться в будущих релизах |

### Обработка ошибок API

| HTTP код | Описание | Решение |
| :--- | :--- | :--- |
| **401** | Unauthorized | Проверьте токен или اسم пользователя/пароль |
| **403** | Forbidden | Проверьте RBAC-политики Service Account |
| **404** | Not Found | Ресурс не существует или неверный endpoint |
| **409** | Conflict | Ресурс уже существует (при создании) |
| **422** | Unprocessable Entity | Невалидные данные запроса |
| **429** | Too Many Requests | Превышен лимит запросов — подождите |
| **500** | Internal Server Error | Ошибка сервера — повторите запрос позже |

### Пагинация

Для списковых запросов API поддерживает пагинацию:

```bash
# Получить первую страницу (по умолчанию 50 элементов)
curl -H "Authorization: Bearer $ARGOCD_TOKEN" \
  $ARGOCD_SERVER/api/v1/applications?offset=0&limit=50

# Получить вторую страницу
curl -H "Authorization: Bearer $ARGOCD_TOKEN" \
  $ARGOCD_SERVER/api/v1/applications?offset=50&limit=50
```

### Rate Limiting

ArgoCD API имеет встроенный rate limiting:
- **Без аутентификации:** 10 запросов/минуту
- **С аутентификацией:** 100 запросов/минуту (настраивается в `argocd-cm`)
- **Service Account:** Ограничения снимаются при использовании API-токена

## Практические сценарии

### Сценарий 1: Управление ресурсами через cURL

Экспортируйте токен: `export ARGOCD_TOKEN="ваш_токен"`

**Создание AppProject:**
```bash
curl -X POST -H "Authorization: Bearer $ARGOCD_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "project": {
      "metadata": {"name": "prod-project"},
      "spec": {
        "destinations": [{"server": "https://kubernetes.default.svc", "namespace": "prod"}],
        "sourceRepos": ["https://github.com/my-org/*"]
      }
    }
  }' $ARGOCD_SERVER/api/v1/projects
```

**Принудительная синхронизация приложения:**
```bash
curl -X POST -H "Authorization: Bearer $ARGOCD_TOKEN" \
  $ARGOCD_SERVER/api/v1/applications/my-app/sync
```

**Создание Application:**
```bash
curl -X POST -H "Authorization: Bearer $ARGOCD_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name": "my-app",
    "project": "default",
    "source": {
      "repoURL": "https://github.com/my-org/my-repo.git",
      "path": "k8s/overlays/prod",
      "targetRevision": "HEAD"
    },
    "destination": {
      "server": "https://kubernetes.default.svc",
      "namespace": "production"
    },
    "syncPolicy": {
      "automated": {
        "prune": true,
        "selfHeal": true
      }
    }
  }' $ARGOCD_SERVER/api/v1/applications
```

**Получение списка приложений:**
```bash
curl -H "Authorization: Bearer $ARGOCD_TOKEN" \
  $ARGOCD_SERVER/api/v1/applications | jq '.items[].metadata.name'
```

**Получение деталей приложения:**
```bash
curl -H "Authorization: Bearer $ARGOCD_TOKEN" \
  $ARGOCD_SERVER/api/v1/applications/my-app | jq '.status'
```

**Удаление приложения:**
```bash
curl -X DELETE -H "Authorization: Bearer $ARGOCD_TOKEN" \
  $ARGOCD_SERVER/api/v1/applications/my-app
```

**Просмотр diff:**
```bash
curl -H "Authorization: Bearer $ARGOCD_TOKEN" \
  $ARGOCD_SERVER/api/v1/applications/my-app/manifests?revision=HEAD
```

### Сценарий 2: Использование CLI как API-клиента

ArgoCD CLI — это обертка над gRPC API, предоставляющая удобный интерфейс для автоматизации.

**Авторизация через CLI:**
```bash
# Авторизация через SSO
argocd login argocd.example.com

# Авторизация через токен
argocd login argocd.example.com --auth-token $ARGOCD_TOKEN --insecure

# Просмотр текущей сессии
argocd account get-user-info
```

**CRUD-операции через CLI:**
```bash
# Создание приложения
argocd app create my-app \
  --repo https://github.com/my-org/my-repo.git \
  --path k8s/overlays/prod \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace production \
  --sync-policy automated \
  --auto-prune \
  --self-heal

# Синхронизация
argocd app sync my-app

# Просмотр статуса
argocd app get my-app

# Просмотр diff
argocd app diff my-app

# Удаление
argocd app delete my-app

# Откат
argocd app history my-app
argocd app rollback my-app <revision>
```

**Управление проектами:**
```bash
# Создание проекта
argocd proj create my-project \
  --src https://github.com/my-org/* \
  --dest https://kubernetes.default.svc,production

# Просмотр проектов
argocd proj list

# Добавление приложения в проект
argocd app set my-app --project my-project
```

**Управление кластерами:**
```bash
# Добавление кластера
argocd cluster add my-cluster-context

# Просмотр кластеров
argocd cluster list

# Удаление кластера
argocd cluster rm my-cluster
```

### Сценарий 3: Использование Ansible Collection

Официальная коллекция `argoproj.argocd` позволяет управлять приложениями без написания низкоуровневых HTTP-запросов.

**Установка коллекции:**
```bash
ansible-galaxy collection install argoproj.argocd
```

**Пример плейбука для создания приложения:**
```yaml
- hosts: localhost
  tasks:
    - name: Create ArgoCD Application
      argoproj.argocd.app:
        name: guestbook
        namespace: argocd
        repo_url: https://github.com/argoproj/argocd-example-apps.git
        path: guestbook
        dest_namespace: default
        dest_server: https://kubernetes.default.svc
        project: default
        sync_policy:
          automated:
            prune: true
            self_heal: true
        auth_token: "{{ lookup('env', 'ARGOCD_TOKEN') }}"
        server_url: "{{ lookup('env', 'ARGOCD_SERVER') }}"
```

**Плейбук для управления проектами:**
```yaml
- hosts: localhost
  tasks:
    - name: Create ArgoCD Project
      argoproj.argocd.project:
        name: my-project
        description: "Production project"
        source_repos:
          - "https://github.com/my-org/*"
        destinations:
          - server: "https://kubernetes.default.svc"
            namespace: "production"
        auth_token: "{{ lookup('env', 'ARGOCD_TOKEN') }}"
        server_url: "{{ lookup('env', 'ARGOCD_SERVER') }}"
```

**Плейбук для синхронизации:**
```yaml
- hosts: localhost
  tasks:
    - name: Sync ArgoCD Application
      argoproj.argocd.app:
        name: my-app
        state: present
        sync: true
        auth_token: "{{ lookup('env', 'ARGOCD_TOKEN') }}"
        server_url: "{{ lookup('env', 'ARGOCD_SERVER') }}"
```

### Сценарий 4: Интеграция с CI/CD (GitHub Actions)

**Пример workflow для автоматического деплоя:**
```yaml
name: Deploy to ArgoCD
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install ArgoCD CLI
        run: |
          curl -sSL -o argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
          chmod +x argocd
          sudo mv argocd /usr/local/bin/
      - name: Deploy to ArgoCD
        env:
          ARGOCD_TOKEN: ${{ secrets.ARGOCD_TOKEN }}
          ARGOCD_SERVER: ${{ secrets.ARGOCD_SERVER }}
        run: |
          argocd login $ARGOCD_SERVER --auth-token $ARGOCD_TOKEN --insecure
          argocd app sync my-app --prune
```

**Пример workflow для создания приложения:**
```yaml
name: Create ArgoCD App
on:
  workflow_dispatch:
    inputs:
      app_name:
        description: 'Application name'
        required: true
      repo_url:
        description: 'Repository URL'
        required: true
jobs:
  create-app:
    runs-on: ubuntu-latest
    steps:
      - name: Create Application
        env:
          ARGOCD_TOKEN: ${{ secrets.ARGOCD_TOKEN }}
          ARGOCD_SERVER: ${{ secrets.ARGOCD_SERVER }}
        run: |
          curl -X POST -H "Authorization: Bearer $ARGOCD_TOKEN" -H "Content-Type: application/json" \
            -d "{
              \"name\": \"${{ github.event.inputs.app_name }}\",
              \"project\": \"default\",
              \"source\": {
                \"repoURL\": \"${{ github.event.inputs.repo_url }}\",
                \"path\": \"k8s\",
                \"targetRevision\": \"HEAD\"
              },
              \"destination\": {
                \"server\": \"https://kubernetes.default.svc\",
                \"namespace\": \"default\"
              }
            }" $ARGOCD_SERVER/api/v1/applications
```

### Сценарий 5: Terraform Provider для ArgoCD

**Установка провайдера:**
```hcl
terraform {
  required_providers {
    argocd = {
      source  = "argoproj-labs/argocd"
      version = "~> 7.0"
    }
  }
}

provider "argocd" {
  server     = "https://argocd.example.com"
  username   = "admin"
  password   = var.argocd_password
  insecure   = true
}
```

**Создание приложения через Terraform:**
```hcl
resource "argocd_application" "my_app" {
  metadata {
    name      = "my-app"
    namespace = "argocd"
  }

  spec {
    project = "default"

    source {
      repo_url  = "https://github.com/my-org/my-repo.git"
      path      = "k8s/overlays/prod"
      target_revision = "HEAD"
    }

    destination {
      server    = "https://kubernetes.default.svc"
      namespace = "production"
    }

    sync_policy {
      automated {
        prune    = true
        self_heal = true
      }
    }
  }
}
```

**Создание проекта через Terraform:**
```hcl
resource "argocd_project" "my_project" {
  metadata {
    name      = "my-project"
    namespace = "argocd"
  }

  spec {
    description = "Production project"

    source_repos = ["https://github.com/my-org/*"]

    destination {
      server    = "https://kubernetes.default.svc"
      namespace = "production"
    }
  }
}
```

### Сценарий 6: Python SDK (argocd-python)

**Установка:**
```bash
pip install argocd-python
```

**Пример использования:**
```python
from argocd_python import ArgoCDClient

client = ArgoCDClient(
    server="https://argocd.example.com",
    token="your-token",
    insecure=True
)

# Получение списка приложений
apps = client.applications.list()
for app in apps.items:
    print(f"{app.metadata.name}: {app.status.sync.status}")

# Создание приложения
client.applications.create({
    "name": "my-app",
    "project": "default",
    "source": {
        "repoURL": "https://github.com/my-org/my-repo.git",
        "path": "k8s",
        "targetRevision": "HEAD"
    },
    "destination": {
        "server": "https://kubernetes.default.svc",
        "namespace": "default"
    }
})

# Синхронизация
client.applications.sync("my-app")
```

### Сценарий 7: Go SDK (argo-cd)

**Установка:**
```bash
go get github.com/argoproj/argo-cd/v2/pkg/client
```

**Пример использования:**
```go
package main

import (
    "context"
    "log"

    "github.com/argoproj/argo-cd/v2/pkg/client/clientset/versioned"
    "k8s.io/client-go/tools/clientcmd"
)

func main() {
    config, err := clientcmd.BuildConfigFromFlags("", "kubeconfig")
    if err != nil {
        log.Fatal(err)
    }

    client, err := versioned.NewForConfig(config)
    if err != nil {
        log.Fatal(err)
    }

    apps, err := client.ArgoprojV1alpha1().Applications("argocd").List(context.TODO(), metav1.ListOptions{})
    if err != nil {
        log.Fatal(err)
    }

    for _, app := range apps.Items {
        log.Printf("%s: %s", app.Name, app.Status.Sync.Status)
    }
}
```

## Рекомендации и лучшие практики

### Безопасность
- **Ansible Vault:** Всегда шифруйте токены доступа. Никогда не фиксируйте их в Git в открытом виде.
- **Принцип минимальных привилегий:** Используйте Service Accounts с узкоспециализированными RBAC-ролями вместо токена администратора.
- **Изоляция API:** Рекомендуется ограничить доступ к API ArgoCD на уровне сети (Ingress Allow-list) только доверенными IP-адресами (например, раннерами CI).
- **Token Rotation:** Регулярно обновляйте API-токены и Service Account secrets.
- **Audit Logging:** Включите аудит-логирование для отслеживания API-запросов.

### Производительность
- **Кеширование:** Используйте кеширование списковых запросов для снижения нагрузки на сервер.
- **Batch Operations:** Группируйте CRUD-операции для повышения эффективности.
- **Connection Pooling:** Используйте connection pooling при большом количестве запросов.

### Надежность
- **Retry Logic:** Настройте повторные попытки при временных ошибках (429, 500).
- **Timeouts:** Устанавливайте таймауты для долгих операций (синхронизация,.health checks).
- **Circuit Breaker:** Реализуйте circuit breaker для предотвращения каскадных сбоев.

### Устранение проблем
- **Логирование:** Включите debug-логирование для отладки API-запросов.
- **Мониторинг:** Добавьте алерты на rate limiting и ошибки API.
- **Инструменты:** Используйте `argocd admin` для диагностики серверных проблем.

## Ограничения и edge cases

### Ограничения

1. **Rate Limiting:** API имеет встроенные ограничения на количество запросов.
2. **Одновременные операции:** Возможны конфликты при параллельных изменениях одного ресурса.
3. **Размер запросов:** Ограничение на размер тела запроса (обычно 1MB).
4. **Время жизни токена:** JWT-токены истекают (по умолчанию 24 часа).

### Edge Cases

1. **Откат при синхронизации:** При откате через API генерируется новое событие.
2. **Удаление при синхронизации:** Параллельное удаление и синхронизация могут привести к ошибкам.
3. **Мультикластер:** Требуется отдельная конфигурация для каждого кластера.
4. **OIDC Token:** При использовании SSO токен может истечь раньше времени.
5. **Прокси-серверы:** Не все прокси поддерживают HTTP/2 (gRPC).
6. **Большие приложения:** При большом количестве ресурсов API может отвечать медленно.
7. **API версии:** При переходе на v2 API могут измениться форматы ответов.

## Диагностика

### Базовые команды

```bash
# Просмотр состояния API
argocd admin cluster stats

# Проверка версии API
argocd version

# Просмотр логов контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# Просмотр событий API
kubectl get events -n argocd --field-selector involvedObject.kind=Application

# Проверка доступности API
curl -k https://argocd.example.com/healthz

# Просмотр速率限制
curl -H "Authorization: Bearer $ARGOCD_TOKEN" \
  $ARGOCD_SERVER/api/v1/account/github-actions | jq '.caps'
```

### Отладка API-запросов

```bash
# Включить отладку в CLI
argocd app get my-app --loglevel debug

# Просмотр HTTP-запросов
curl -v -H "Authorization: Bearer $ARGOCD_TOKEN" \
  $ARGOCD_SERVER/api/v1/applications

# Просмотр gRPC-трафика (через CLI)
argocd app get my-app --grpc-web
```

## Дополнительная информация

### См. также

- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Изоляция проектов, квоты, restrictions, кастомные роли.
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.

### Связанные документы

- [ArgoCD: Обзор системы](./argocd_overview.md) — общая архитектура ArgoCD.
- [ArgoCD: Настройка SSO и RBAC](./argocd_sso_gitlab.md) — аутентификация и авторизация.
- [ArgoCD: Синхронизация и политики](./synchronization.md) — Sync Waves и хуки.
- [ArgoCD: Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md) — устранение проблем.
- [Ansible: Использование Vault](../../Ansible/Vault/basics.md) — шифрование секретов.

### Официальная документация

- [ArgoCD API Reference](https://argo-cd.readthedocs.io/en/stable/operator-manual/argocd-server-api/)
- [ArgoCD CLI Reference](https://argo-cd.readthedocs.io/en/stable/cli_installation/)
- [Ansible argoproj.argocd Collection](https://galaxy.ansible.com/argoproj/argocd)
