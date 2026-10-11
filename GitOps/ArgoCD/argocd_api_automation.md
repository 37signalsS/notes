# Argo CD: Автоматизация через API, CLI и Ansible

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; REST API v1, gRPC / gRPC-Web, Service Accounts, JWT API Tokens)

**Argo CD** предоставляет два интерфейса для программного управления: высокопроизводительный бинарный протокол gRPC (HTTP/2) и классический REST API (HTTP/JSON, работающий через `grpc-gateway`). Автоматизация через API и сопутствующие инструменты (CLI, Ansible, Python, Terraform) позволяет исключить ручные операции из процессов деплоя, безопасно интегрировать GitOps в существующие пайплайны доставки кода на self-hosted инфраструктуре и декларативно управлять конфигурацией самого сервера Argo CD.

## Предварительные требования

Перед началом настройки автоматизации убедитесь в выполнении следующих условий:

1. **Развернутый кластер Kubernetes:** версия v1.28+ на self-hosted / bare-metal инфраструктуре.
2. **Установленный Argo CD:** компоненты `argocd-server`, `argocd-repo-server`, `argocd-application-controller` функционируют штатно:
   ```bash
   kubectl get pods -n argocd -l app.kubernetes.io/part-of=argocd
   # → argocd-application-controller-0   1/1     Running   0          5d
   # → argocd-repo-server-xxx            1/1     Running   0          5d
   # → argocd-server-xxx                 1/1     Running   0          5d
   # → argocd-redis-xxx                  1/1     Running   0          5d
   ```
3. **Сетевой доступ к API:** порт 443 (или 8080 внутри кластера) доступен для CI-раннеров и систем автоматизации. Проверьте эндпоинт здоровья:
   ```bash
   curl -k -s https://argocd.internal.example.com/healthz
   # → ok
   ```
4. **Утилиты автоматизации:**
   - `argocd` CLI v3.5+ установлен на хосте управления.
   - `kubectl` с правами редактирования ConfigMap в namespace `argocd`.
   - `ansible-core` v2.15+ и коллекция `argoproj.argocd` (для Ansible-сценариев).
   - Python 3.10+ с библиотекой `requests` (для программных скриптов).
   - `jq` v1.6+ и `curl` v7.80+ для CLI-скриптов.

## Определения

- **Argo CD REST API** — HTTP/JSON интерфейс, обслуживаемый встроенным прокси `grpc-gateway` внутри процесса `argocd-server`. Доступен по пути `/api/v1/` и транслирует HTTP-запросы во внутренние gRPC-вызовы.
- **Argo CD gRPC API** — бинарный протокол на базе HTTP/2 и Protobuf, используемый по умолчанию утилитой `argocd` CLI и внутренними контроллерами на порту 8080 (или 443 через TLS Ingress).
- **gRPC-Web** — протокол-обертка, инкапсулирующая gRPC-фреймы в стандартные HTTP/1.1 или HTTP/2 POST-запросы. Позволяет CLI работать через корпоративные прокси и балансировщики, не поддерживающие сквозной HTTP/2 gRPC.
- **Service Account (Argo CD Local Account)** — программная учетная запись, определенная в ConfigMap `argocd-cm`, предназначенная для скриптов и систем CI/CD. Позволяет генерировать API-токены без привязки к конкретному человеку.
- **Project JWT Token** — токен доступа с ограниченной областью видимости, генерируемый в рамках конкретного `AppProject` (`spec.roles[].jwtTokens`). Предоставляет права только на ресурсы внутри этого проекта.
- **Session Token** — временный JWT-токен пользователя, выдаваемый эндпоинтом `/api/v1/session` после передачи логина и пароля.
- **Ansible Collection `argoproj.argocd`** — сертифицированная коллекция модулей Ansible для декларативного создания и синхронизации приложений, проектов, кластеров и репозиториев Argo CD.
- **Idempotency (Идемпотентность API)** — свойство API-операций (PUT/PATCH), гарантирующее, что повторный запуск запроса с теми же параметрами не приводит к нежелательным изменениям состояния системы при отсутствии дрифта.

## Базовые концепции и архитектура API

### Архитектура API-сервера

Процесс `argocd-server` является единой точкой входа для пользовательских интерфейсов (Web UI), консольного клиента (`argocd` CLI), внешних систем автоматизации и вебхуков:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 Внешние клиенты                                        │
│     cURL / Python (REST)             argocd CLI (gRPC/gRPC-Web)          Ansible / TF  │
└───────────────────────────┬────────────────────────────────┬───────────────────────────┘
                            │                                │
                            ▼                                ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  argocd-server (Pod)                                                                   │
│  ┌───────────────────────────────┐                  ┌────────────────────────────────┐ │
│  │   grpc-gateway (/api/v1/*)    │──[ In-process ]─▶│       gRPC API Server          │ │
│  │   (HTTP/1.1 / JSON транслятор)│                  │       (:8080 / Protobuf)       │ │
│  └───────────────────────────────┘                  └────────────────┬───────────────┘ │
│                                                                      │                 │
│                 ┌────────────────────────────────────────────────────┴───────────────┐ │
│                 ▼                                                                    ▼ │
│  ┌───────────────────────────────┐                                ┌──────────────────┐ │
│  │  Аутентификация & RBAC        │                                │  Кэш состояний   │ │
│  │  - Проверка JWT (secretkey)   │                                │  Redis (:6379)   │ │
│  │  - Валидация в policy.csv     │                                └──────────────────┘ │
│  └──────────────┬────────────────┘                                                     │
└─────────────────┼──────────────────────────────────────────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  Kubernetes API Server                                                                 │
│  - Чтение и запись CRD: Application, AppProject, ApplicationSet                        │
│  - argocd-application-controller отслеживает изменения и инициирует синхронизацию      │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Единый порт и трансляция:** `argocd-server` слушает один сетевой порт (по умолчанию 8080). Входящие REST-запросы на `/api/v1/` перехватываются мультиплексором и преобразуются компонентом `grpc-gateway` в бинарные вызовы gRPC внутри того же процесса.
2. **Сессионный слой и безопасность:** Все запросы проходят валидацию JWT-токена с использованием секретного ключа `server.secretkey`, хранящегося в Kubernetes Secret `argocd-secret`.
3. **Авторизация:** Проверенный субъект сопоставляется с правилами RBAC из `argocd-rbac-cm` (`policy.csv`) или локальными ролями `AppProject`.
4. **Взаимодействие с хранилищем:** Состояние приложений кэшируется в Redis, а целевые манифесты и статусы сохраняются непосредственно в Custom Resource Definitions (CRD) кластера Kubernetes.

### Сравнение протоколов: REST vs gRPC vs gRPC-Web

| Характеристика | REST (HTTP/JSON) | gRPC (HTTP/2 Protobuf) | gRPC-Web (HTTP/1.1 / HTTP/2) |
| :--- | :--- | :--- | :--- |
| **Формат данных** | JSON (текстовый) | Protocol Buffers (бинарный) | Protobuf / Base64 в HTTP-фреймах |
| **Транспорт** | HTTP/1.1 или HTTP/2 | Строго HTTP/2 | HTTP/1.1 или HTTP/2 |
| **Основное применение** | cURL, Python `requests`, вебхуки, CI/CD | `argocd` CLI, внутренние вызовы, Go SDK | CLI за обратными прокси, Web UI |
| **Нагрузка на сеть** | Выше (за счет заголовков и JSON) | Минимальная (бинарное сжатие) | Средняя |
| **Требования к Ingress** | Стандартный HTTP/HTTPS прокси | Требуется поддержка сквозного HTTP/2 gRPC | Работает через любой стандартный прокси |
| **Активация в CLI** | Не поддерживается напрямую | По умолчанию | Флаг `--grpc-web` |

### Сетевое взаимодействие и Ingress в self-hosted окружении

При развертывании в bare-metal / on-prem Kubernetes для доступа к API настраивается Ingress (например, Ingress-NGINX). Существует два архитектурных паттерна:

1. **Режим gRPC-Web / REST (рекомендуемый универсальный вариант):**
   Ingress работает в стандартном режиме терминирования TLS. Все REST-клиенты работают напрямую, а CLI-клиенты вызывают сервер с флагом `--grpc-web`:
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: Ingress
   metadata:
     name: argocd-server-http
     namespace: argocd
     annotations:
       nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
       nginx.ingress.kubernetes.io/ssl-passthrough: "false"
       nginx.ingress.kubernetes.io/proxy-body-size: "32m"
   spec:
     rules:
       - host: argocd.internal.example.com
         http:
           paths:
             - path: /
               pathType: Prefix
               backend:
                 service:
                   name: argocd-server
                   port:
                     name: http
   ```

2. **Режим сквозного gRPC (высокая производительность):**
   Требует отдельного Host-имени или пути и специфической аннотации `backend-protocol: "GRPC"`:
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: Ingress
   metadata:
     name: argocd-server-grpc
     namespace: argocd
     annotations:
       nginx.ingress.kubernetes.io/backend-protocol: "GRPC"
   spec:
     rules:
       - host: grpc.argocd.internal.example.com
         http:
           paths:
             - path: /
               pathType: Prefix
               backend:
                 service:
                   name: argocd-server
                   port:
                     name: https
   ```

### Методы аутентификации и токены

Argo CD поддерживает три механизма аутентификации для автоматизации:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Механизмы аутентификации                        │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Service Account (глобальный)                                        │
│    Определяется в `argocd-cm`, права в `argocd-rbac-cm`               │
│    Генерация: `argocd account generate-token --account <name>`         │
│    Применение: системные CI/CD пайплайны, операторы                    │
├────────────────────────────────────────────────────────────────────────┤
│ 2. Project-Scoped Token (локальный в AppProject)                       │
│    Определяется в `AppProject.spec.roles[].jwtTokens`                 │
│    Генерация: `argocd proj role create-token <project> <role>`         │
│    Применение: изоляция команд, токены только для конкретных приложений │
├────────────────────────────────────────────────────────────────────────┤
│ 3. Временная сессия пользователя (Session Token)                       │
│    Запрос: POST /api/v1/session {"username": "...", "password": "..."} │
│    Применение: интерактивные скрипты, временные админ-задачи          │
└────────────────────────────────────────────────────────────────────────┘
```

Структура полезной нагрузки JWT-токена (Payload):
```json
{
  "sub": "ci-automation",
  "iss": "argocd",
  "iat": 1728660000,
  "exp": 1760196000,
  "id": "c1a2b3c4-d5e6-7890-abcd-ef1234567890"
}
```
Токен передается во всех HTTP-запросах в заголовке `Authorization: Bearer <token>`.

### Rate Limiting и защита API

Для предотвращения деградации контроллера и сервера при высокой нагрузке от скриптов автоматизации Argo CD предоставляет встроенный rate limiter. Настройка выполняется в ConfigMap `argocd-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Лимит запросов на один IP-адрес / токен (запросов в секунду)
  server.rate-limit: "50"
  # Допустимый всплеск запросов (burst)
  server.rate-limit.burst: "100"
  # Лимит на попытки логина во избежание подбора паролей
  server.rate-limit.login.burst: "5"
```
При превышении порога сервер возвращает статус `429 Too Many Requests`. Скрипты автоматизации обязаны реализовывать задержку с экспоненциальным откатом (Exponential Backoff).

## Практические сценарии и автоматизация

### Сценарий 1: Настройка Service Account и выпуск JWT-токенов

Создадим выделенный сервисный аккаунт `ci-automation` для пайплайнов и выпустим токен с ограниченными правами.

#### Шаг 1. Создание аккаунта в argocd-cm
Добавьте аккаунт с поддержкой API-ключей:
```bash
kubectl patch configmap argocd-cm -n argocd --type merge -p '{"data":{"accounts.ci-automation":"apiKey"}}'
# → configmap/argocd-cm patched
```

Убедитесь, что аккаунт появился в системе:
```bash
argocd account list
# → NAME           ENABLED  CAPABILITIES  FLAG
# → admin          true     login         
# → ci-automation  true     apiKey        
```

#### Шаг 2. Назначение RBAC-прав в argocd-rbac-cm
Предоставим аккаунту права только на просмотр и синхронизацию приложений в проекте `production`:
```bash
kubectl patch configmap argocd-rbac-cm -n argocd --type merge -p '{
  "data": {
    "policy.csv": "p, role:ci-runner, applications, get, production/*, allow\np, role:ci-runner, applications, sync, production/*, allow\ng, ci-automation, role:ci-runner\n"
  }
}'
# → configmap/argocd-rbac-cm patched
```

#### Шаг 3. Генерация глобального API-токена
Сгенерируйте токен со сроком действия 90 дней (7776000 секунд):
```bash
ARGOCD_TOKEN=$(argocd account generate-token --account ci-automation --expires-in 7776000s)
echo "$ARGOCD_TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{sub, exp}'
# → {
# →   "sub": "ci-automation",
# →   "exp": 1736438400
# → }
```

#### Шаг 4. Альтернатива: Генерация Project-Scoped токена
Для многопользовательских систем предпочтительно выпускать токен в рамках `AppProject`:
```bash
# Создание роли внутри проекта
argocd proj role create production-proj deploy-bot \
  --description "CI deployer for production"
# → Role 'deploy-bot' created in project 'production-proj'

# Назначение прав роли
argocd proj role add-policy production-proj deploy-bot \
  --action sync --object "production-proj/*" --permission allow
# → Policy added to role 'deploy-bot'

# Генерация токена
PROJ_TOKEN=$(argocd proj role create-token production-proj deploy-bot)
echo "Project Token generated successfully"
# → Project Token generated successfully
```

---

### Сценарий 2: Низкоуровневая автоматизация через REST API (cURL и Bash)

Использование REST API актуально для легковесных скриптов, где установка `argocd` CLI нежелательна или невозможна.

Экспортируйте переменные окружения:
```bash
export ARGOCD_SERVER="https://argocd.internal.example.com"
export ARGOCD_TOKEN="<ваш_jwt_токен>"
```

#### 1. Проверка аутентификации и контекста
```bash
curl -s -k -H "Authorization: Bearer $ARGOCD_TOKEN" \
  "$ARGOCD_SERVER/api/v1/session/userinfo" | jq '{username, iss}'
# → {
# →   "username": "ci-automation",
# →   "iss": "argocd"
# → }
```

#### 2. Создание AppProject
```bash
curl -s -k -X POST \
  -H "Authorization: Bearer $ARGOCD_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project": {
      "metadata": {
        "name": "core-services"
      },
      "spec": {
        "description": "On-prem core infrastructure applications",
        "sourceRepos": [
          "https://git.internal.example.com/infrastructure/*"
        ],
        "destinations": [
          {
            "server": "https://kubernetes.default.svc",
            "namespace": "core"
          }
        ],
        "clusterResourceWhitelist": [
          {
            "group": "",
            "kind": "Namespace"
          }
        ]
      }
    }
  }' "$ARGOCD_SERVER/api/v1/projects" | jq '.metadata.name'
# → "core-services"
```

#### 3. Создание Application с декларативной политикой синхронизации
```bash
curl -s -k -X POST \
  -H "Authorization: Bearer $ARGOCD_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "name": "ingress-controller",
      "namespace": "argocd"
    },
    "spec": {
      "project": "core-services",
      "source": {
        "repoURL": "https://git.internal.example.com/infrastructure/manifests.git",
        "targetRevision": "main",
        "path": "ingress/overlays/production"
      },
      "destination": {
        "server": "https://kubernetes.default.svc",
        "namespace": "core"
      },
      "syncPolicy": {
        "automated": {
          "prune": true,
          "selfHeal": true
        },
        "syncOptions": [
          "CreateNamespace=true",
          "ApplyOutOfSyncOnly=true"
        ]
      }
    }
  }' "$ARGOCD_SERVER/api/v1/applications" | jq '{name: .metadata.name, project: .spec.project}'
# → {
# →   "name": "ingress-controller",
# →   "project": "core-services"
# → }
```

#### 4. Запуск принудительной синхронизации (Trigger Sync)
Передадим параметры точечной синхронизации с включенным удалением лишних ресурсов (`prune`):
```bash
curl -s -k -X POST \
  -H "Authorization: Bearer $ARGOCD_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "revision": "main",
    "prune": true,
    "dryRun": false,
    "strategy": {
      "hook": {
        "force": false
      }
    }
  }' "$ARGOCD_SERVER/api/v1/applications/ingress-controller/sync" | jq '.status.operationState.phase'
# → "Running"
```

#### 5. Опрос статуса выполнения синхронизации и здоровья
```bash
curl -s -k -H "Authorization: Bearer $ARGOCD_TOKEN" \
  "$ARGOCD_SERVER/api/v1/applications/ingress-controller" | jq '{sync: .status.sync.status, health: .status.health.status}'
# → {
# →   "sync": "Synced",
# →   "health": "Healthy"
# → }
```

#### 6. Получение сгенерированных манифестов (Diff / Manifests)
Позволяет валидировать рендеринг Helm/Kustomize на стороне `argocd-repo-server`:
```bash
curl -s -k -H "Authorization: Bearer $ARGOCD_TOKEN" \
  "$ARGOCD_SERVER/api/v1/applications/ingress-controller/manifests?revision=main" | jq '.manifests | length'
# → 6
```

#### 7. Безопасное удаление приложения
Для удаления приложения без удаления управляемых ресурсов в Kubernetes передайте параметр `cascade=false`:
```bash
# Каскадное удаление (удалит приложение и все созданные им ресурсы в K8s):
curl -s -k -X DELETE -H "Authorization: Bearer $ARGOCD_TOKEN" \
  "$ARGOCD_SERVER/api/v1/applications/ingress-controller?cascade=true"
# → {}

# Некаскадное удаление (оставит поды и сервисы в K8s, удалит только объект Application):
# curl -s -k -X DELETE -H "Authorization: Bearer $ARGOCD_TOKEN" "$ARGOCD_SERVER/api/v1/applications/ingress-controller?cascade=false"
```

---

### Сценарий 3: Автоматизация через Argo CD CLI в пайплайнах

CLI-клиент предоставляет наиболее лаконичный синтаксис для CI/CD скриптов благодаря встроенным механизмам ожидания статусов.

#### Пайплайн-скрипт деплоя с ожиданием статуса
```bash
#!/usr/bin/env bash
set -euo pipefail

ARGOCD_SERVER="argocd.internal.example.com:443"
APP_NAME="payment-service"
TIMEOUT=300

echo "==> Выполняем неинтерактивный вход в Argo CD..."
argocd login "$ARGOCD_SERVER" \
  --auth-token "$ARGOCD_TOKEN" \
  --grpc-web \
  --insecure
# → 'admin' logged in successfully

echo "==> Обновляем целевой коммит и запускаем синхронизацию..."
argocd app set "$APP_NAME" --revision "v2.14.0" --grpc-web
# → application 'payment-service' updated

echo "==> Запускаем асинхронную синхронизацию..."
argocd app sync "$APP_NAME" --async --prune --grpc-web
# → TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS   HEALTH        HOOK  MESSAGE
# → 2026-10-11T20:45:00+03:00  apps   Deployment     finance       payment-service  OutOfSync  Healthy             

echo "==> Ожидаем завершения синхронизации и перехода в Healthy..."
argocd app wait "$APP_NAME" \
  --sync \
  --health \
  --timeout "$TIMEOUT" \
  --grpc-web
# → TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS   HEALTH        HOOK  MESSAGE
# → 2026-10-11T20:45:15+03:00  apps   Deployment     finance       payment-service    Synced  Progressing         
# → 2026-10-11T20:45:30+03:00  apps   Deployment     finance       payment-service    Synced   Healthy             

echo "==> Деплой успешно завершен!"
```

---

### Сценарий 4: Декларативное управление через Ansible Collection (`argoproj.argocd`)

Коллекция `argoproj.argocd` идеальна для администраторов инфраструктуры (SysAdmin / DevOps), управляющих конфигурацией Argo CD как кодом.

#### Установка коллекции
```bash
ansible-galaxy collection install argoproj.argocd:>=2.0.0
# → Starting galaxy collection install process
# → Process install dependency map
# → Starting collection install process
# → Installing 'argoproj.argocd:2.1.0' to '/home/ansible/.ansible/collections/ansible_collections/argoproj/argocd'
```

#### Использование Ansible Vault для токена
Храните токен в зашифрованном файле `vault.yml` (см. [Ansible Vault](../../Ansible/Vault/basics.md)):
```yaml
# vault.yml
vault_argocd_token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

#### Плейбук создания проекта и приложения
Создайте файл `deploy_argocd_resources.yml`:
```yaml
---
- name: Управление ресурсами Argo CD на self-hosted инфраструктуре
  hosts: localhost
  connection: local
  gather_facts: false

  vars_files:
    - vault.yml

  vars:
    argocd_server: "https://argocd.internal.example.com"
    app_project: "billing-system"

  tasks:
    - name: Создать AppProject для биллинговой системы
      argoproj.argocd.project:
        server_url: "{{ argocd_server }}"
        auth_token: "{{ vault_argocd_token }}"
        validate_certs: false
        name: "{{ app_project }}"
        description: "Billing microservices and database migrations"
        state: present
        source_repos:
          - "https://git.internal.example.com/billing/*"
        destinations:
          - server: "https://kubernetes.default.svc"
            namespace: "billing"
        cluster_resource_whitelist:
          - group: ""
            kind: "Namespace"

    - name: Создать и задеплоить Application
      argoproj.argocd.app:
        server_url: "{{ argocd_server }}"
        auth_token: "{{ vault_argocd_token }}"
        validate_certs: false
        name: "billing-api"
        namespace: "argocd"
        project: "{{ app_project }}"
        state: present
        repo_url: "https://git.internal.example.com/billing/manifests.git"
        target_revision: "main"
        path: "apps/billing-api/overlays/prod"
        dest_server: "https://kubernetes.default.svc"
        dest_namespace: "billing"
        sync_policy:
          automated:
            prune: true
            self_heal: true
          sync_options:
            - "CreateNamespace=true"
            - "PruneLast=true"
        sync: true
        wait: true
        wait_timeout: 300
      register: app_deploy_result

    - name: Вывести результат деплоя
      ansible.builtin.debug:
        msg: "Приложение {{ app_deploy_result.name }} успешно синхронизировано."
```

Запуск плейбука:
```bash
ansible-playbook -i localhost, deploy_argocd_resources.yml --ask-vault-pass
# → PLAY [Управление ресурсами Argo CD на self-hosted инфраструктуре] ********************
# → TASK [Создать AppProject для биллинговой системы] ***********************************
# → changed: [localhost]
# → TASK [Создать и задеплоить Application] *********************************************
# → changed: [localhost]
# → TASK [Вывести результат деплоя] *****************************************************
# → ok: [localhost] => {
# →     "msg": "Приложение billing-api успешно синхронизировано."
# → }
# → PLAY RECAP **************************************************************************
# → localhost                  : ok=3    changed=2    unreachable=0    failed=0
```

---

### Сценарий 5: CI/CD автоматизация на self-hosted раннерах (GitLab CI)

Пример интеграции в GitLab CI на внутренних Runner-серверах без облачных зависимостей:

```yaml
stages:
  - build
  - gitops-trigger

deploy_to_argocd:
  stage: gitops-trigger
  image: curlimages/curl:8.5.0
  variables:
    ARGOCD_SERVER: "https://argocd.internal.example.com"
    APP_NAME: "auth-gateway"
  before_script:
    - apk add --no-cache jq
  script:
    - echo "==> Инициируем синхронизацию через REST API..."
    - |
      SYNC_RESP=$(curl -s -k -X POST \
        -H "Authorization: Bearer ${ARGOCD_API_TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{"prune": true, "dryRun": false}' \
        "${ARGOCD_SERVER}/api/v1/applications/${APP_NAME}/sync")
      
      echo "Sync initiated: $(echo "$SYNC_RESP" | jq -r '.status.operationState.phase // .message')"
    
    - echo "==> Ожидаем завершения синхронизации и перехода в Healthy..."
    - |
      MAX_RETRIES=30
      SLEEP_SEC=10
      for i in $(seq 1 $MAX_RETRIES); do
        STATUS=$(curl -s -k -H "Authorization: Bearer ${ARGOCD_API_TOKEN}" \
          "${ARGOCD_SERVER}/api/v1/applications/${APP_NAME}" | jq -r '.status.sync.status + "/" + .status.health.status')
        
        echo "Попытка $i: Статус $STATUS"
        if [ "$STATUS" = "Synced/Healthy" ]; then
          echo "Приложение успешно развернуто!"
          exit 0
        fi
        sleep $SLEEP_SEC
      done
      
      echo "Ошибка: Превышен таймаут ожидания Healthy статуса!"
      exit 1
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

---

### Сценарий 6: Production-ready скрипт автоматизации на Python (requests)

Готовый скрипт для SRE-автоматизации и интеграции в кастомные сервисы. Реализует сессию с повторными попытками при сетевых сбоях и обработку HTTP 429:

```python
#!/usr/bin/env python3
"""
Argo CD API Automation Client for SRE / DevOps.
Программный опрос и синхронизация приложений без облачных зависимостей.
"""

import os
import sys
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

class ArgoCDClient:
    def __init__(self, server_url: str, token: str, verify_ssl: bool = True):
        self.server_url = server_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })

        # Настройка стратегии повторных попыток для отказоустойчивости
        retries = Retry(
            total=5,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def trigger_sync(self, app_name: str, revision: str = "HEAD", prune: bool = True) -> dict:
        url = f"{self.server_url}/api/v1/applications/{app_name}/sync"
        payload = {
            "revision": revision,
            "prune": prune,
            "dryRun": False,
            "strategy": {"hook": {"force": False}}
        }
        resp = self.session.post(url, json=payload, verify=self.verify_ssl)
        resp.raise_for_status()
        return resp.json()

    def wait_for_healthy(self, app_name: str, timeout_sec: int = 300, poll_interval: int = 10) -> bool:
        url = f"{self.server_url}/api/v1/applications/{app_name}"
        start_time = time.time()

        while time.time() - start_time < timeout_sec:
            resp = self.session.get(url, verify=self.verify_ssl)
            resp.raise_for_status()
            data = resp.json()

            sync_status = data.get("status", {}).get("sync", {}).get("status")
            health_status = data.get("status", {}).get("health", {}).get("status")

            print(f"[{time.strftime('%X')}] Application {app_name}: Sync={sync_status}, Health={health_status}")

            if sync_status == "Synced" and health_status == "Healthy":
                return True
            if health_status == "Degraded":
                raise RuntimeError(f"Application {app_name} перешло в состояние Degraded!")

            time.sleep(poll_interval)

        raise TimeoutError(f"Таймаут {timeout_sec}c ожидания Synced/Healthy для {app_name}")

if __name__ == "__main__":
    server = os.getenv("ARGOCD_SERVER", "https://argocd.internal.example.com")
    token = os.getenv("ARGOCD_TOKEN")
    if not token:
        print("Ошибка: Переменная окружения ARGOCD_TOKEN не задана", file=sys.stderr)
        sys.exit(1)

    client = ArgoCDClient(server_url=server, token=token, verify_ssl=False)
    app = "billing-api"

    print(f"==> Инициируем синхронизацию {app}...")
    client.trigger_sync(app_name=app, prune=True)

    print("==> Ожидаем завершения деплоя...")
    success = client.wait_for_healthy(app_name=app, timeout_sec=180)
    if success:
        print(f"==> Приложение {app} успешно развернуто!")
        sys.exit(0)
```

Запуск скрипта:
```bash
python3 argocd_deploy.py
# → ==> Инициируем синхронизацию billing-api...
# → ==> Ожидаем завершения деплоя...
# → [20:46:10] Application billing-api: Sync=OutOfSync, Health=Progressing
# → [20:46:20] Application billing-api: Sync=Synced, Health=Progressing
# → [20:46:30] Application billing-api: Sync=Synced, Health=Healthy
# → ==> Приложение billing-api успешно развернуто!
```

---

### Сценарий 7: Инфраструктурное управление через Terraform Provider (`argoproj-labs/argocd`)

Для платформенных команд, управляющих Kubernetes-инфраструктурой через Terraform/OpenTofu на self-hosted стендах:

```hcl
terraform {
  required_version = ">= 1.5.0"
  required_providers {
    argocd = {
      source  = "argoproj-labs/argocd"
      version = "~> 7.2.0"
    }
  }
}

provider "argocd" {
  server_addr = "argocd.internal.example.com:443"
  auth_token  = var.argocd_auth_token
  insecure    = true
  grpc_web    = true
}

resource "argocd_project" "monitoring" {
  metadata {
    name      = "monitoring"
    namespace = "argocd"
  }

  spec {
    description  = "Self-hosted Prometheus and Grafana stack"
    source_repos = ["https://git.internal.example.com/monitoring/*"]

    destination {
      server    = "https://kubernetes.default.svc"
      namespace = "monitoring"
    }

    cluster_resource_whitelist {
      group = "rbac.authorization.k8s.io"
      kind  = "ClusterRoleBinding"
    }
  }
}

resource "argocd_application" "prometheus_stack" {
  metadata {
    name      = "kube-prometheus"
    namespace = "argocd"
  }

  spec {
    project = argocd_project.monitoring.metadata[0].name

    source {
      repo_url        = "https://git.internal.example.com/monitoring/manifests.git"
      target_revision = "main"
      path            = "charts/kube-prometheus-stack"
    }

    destination {
      server    = "https://kubernetes.default.svc"
      namespace = "monitoring"
    }

    sync_policy {
      automated {
        prune     = true
        self_heal = true
      }

      sync_options = [
        "CreateNamespace=true",
        "ServerSideApply=true"
      ]
    }
  }
}
```

## Диагностика и Troubleshooting

### Таблица типовых ошибок API и кодов возврата

| HTTP код | gRPC код | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- | :--- |
| **401 Unauthorized** | 16 UNAUTHENTICATED | Истек срок действия JWT-токена (`exp`), ротирован `server.secretkey` или не передан заголовок | `echo $TOKEN \| cut -d. -f2 \| base64 -d \| jq .exp` | Выпустите новый токен через `argocd account generate-token` или перелогиньтесь |
| **403 Forbidden** | 7 PERMISSION_DENIED | Учетная запись не имеет прав в `policy.csv` или ограничена правилами `AppProject` | Проверьте правила `argocd-rbac-cm` и роли в проекте | Добавьте запись `p, role:..., <resource>, <action>, <object>, allow` |
| **404 Not Found** | 5 NOT_FOUND | Неверный URL, приложение или проект не существуют | `curl -s -k -H "Authorization: Bearer $T" $URL/api/v1/applications` | Проверьте имя приложения и наличие спецсимволов (URL-encode для серверов кластеров) |
| **409 Conflict** | 6 ALREADY_EXISTS | Попытка создать ресурс с уже занятым именем или конфликт версий `resourceVersion` | Проверьте список ресурсов в namespace | Используйте PUT/PATCH вместо POST для обновления существующих объектов |
| **429 Too Many Requests** | 8 RESOURCE_EXHAUSTED | Превышен лимит запросов, настроенный в `server.rate-limit` | Изучите логи `argocd-server` на наличие записей rate limit | Внедрите экспоненциальный откат (backoff) или увеличьте лимит в `argocd-cm` |
| **502 / 503 Bad Gateway** | 14 UNAVAILABLE | `argocd-server` недоступен, сбой пода или несовместимость протокола на Ingress | `kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server` | Проверьте readiness probe подов и настройки Ingress (`backend-protocol`) |
| **504 Gateway Timeout** | 4 DEADLINE_EXCEEDED | Таймаут при генерации манифестов в `argocd-repo-server` или обращении к Git | Проверьте логи `argocd-repo-server` | Увеличьте `timeout.reconciliation` в `argocd-cm` и проверьте скорость доступа к Git-серверу |

### Пошаговые сценарии диагностики

#### 1. Проверка работоспособности API-сервера и метрик
Проверьте доступность внутренних портов и задержку ответов сервера:
```bash
kubectl exec -n argocd deploy/argocd-server -c argocd-server -- \
  curl -s http://localhost:8080/healthz
# → ok
```

Проверьте метрику ошибок API через встроенный endpoint Prometheus:
```bash
kubectl exec -n argocd deploy/argocd-server -c argocd-server -- \
  curl -s http://localhost:8083/metrics | grep "argocd_api_request_duration_seconds_count" | head -n 5
# → argocd_api_request_duration_seconds_count{grpc_code="OK",grpc_method="Get",grpc_service="application.ApplicationService"} 1420
# → argocd_api_request_duration_seconds_count{grpc_code="PermissionDenied",grpc_method="Sync",grpc_service="application.ApplicationService"} 3
```

#### 2. Диагностика транспортного уровня gRPC / gRPC-Web
Если `argocd` CLI возвращает ошибку `rpc error: code = Unavailable desc = transport is closing` или `connection reset by peer`:
```bash
# Тест подключения в режиме чистого gRPC
argocd app list --loglevel debug
# → DEBU[0000] Connecting to argocd.internal.example.com:443
# → rpc error: code = Unavailable desc = connection closed before server preface received

# Решение: принудительное переключение на gRPC-Web через Ingress
argocd app list --grpc-web
# → NAME             CLUSTER                         STATUS   HEALTH   AUTO-SYNC
# → billing-api      https://kubernetes.default.svc  Synced   Healthy  Manual
```

#### 3. Отладка отклонения прав (RBAC Forbidden)
Проверьте права конкретного аккаунта без запуска деплоя через CLI:
```bash
argocd account can-i sync applications 'production/*' --account ci-automation
# → Yes

argocd account can-i delete applications 'production/*' --account ci-automation
# → No
```

#### 4. Анализ структурированных логов сервера
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server --tail=50 | grep -E "(level=error|level=warning)"
# → time="2026-10-11T20:40:12Z" level=warning msg="Rate limit exceeded for client IP 10.244.2.1"
```

## Рекомендации и Best Practices

### Безопасность (Security)
- **Принцип наименьших привилегий:** Избегайте использования токена учетной записи `admin`. Создавайте Service Accounts с точечными ролями в `policy.csv`.
- **Использование Project-Scoped токенов:** Для изоляции сервисов команд выпускайте JWT-токены в рамках `AppProject`. Утечка такого токена не ставит под угрозу приложения других проектов.
- **Шифрование секретов автоматизации:** Никогда не храните JWT-токены в открытом виде в Git. Используйте Ansible Vault, HashiCorp Vault или Sealed Secrets.
- **Сетевая изоляция API:** Ограничивайте доступ к API-серверу на уровне Kubernetes `NetworkPolicy` и Ingress IP-Allowlist, разрешая подключения только из доверенных подсетей CI-раннеров и систем мониторинга:
  ```yaml
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: argocd-server-ingress-allow
    namespace: argocd
  spec:
    podSelector:
      matchLabels:
        app.kubernetes.io/name: argocd-server
    ingress:
      - from:
          - ipBlock:
              cidr: 10.50.0.0/16 # Подсеть self-hosted CI/CD раннеров
        ports:
          - protocol: TCP
            port: 8080
  ```

### Производительность и масштабирование (SRE / SysAdmin)
- **Горизонтальное масштабирование `argocd-server`:** Процесс сервера является stateless (все состояние хранится в Redis и Kubernetes CRD). При интенсивной автоматизации увеличьте число реплик:
  ```bash
  kubectl scale deployment argocd-server -n argocd --replicas=3
  # → deployment.apps/argocd-server scaled
  ```
- **Тюнинг Redis-кэша:** При частых вызовах списочных методов API `/api/v1/applications` кэш Redis предотвращает перегрузку Kubernetes API Server. Контролируйте память пода `argocd-redis`.
- **Идемпотентность и Server-Side Apply:** При программном обновлении спецификаций приложений через API используйте Server-Side Apply (`ApplyOutOfSyncOnly=true`, `ServerSideApply=true`), чтобы минимизировать сетевой оверхед и избежать конфликтов `resourceVersion`.

### Надежность скриптов автоматизации
- **Отказ от бесконечных циклов:** Любой опрос статуса (`wait`) в скриптах обязан иметь жесткий таймаут (обычно 300–600 секунд) и интервал между запросами не менее 5–10 секунд.
- **Двухэтапная валидация:** Синхронизация считается успешной только при достижении двух условий: `status.sync.status == "Synced"` и `status.health.status == "Healthy"`. Проверка только `Synced` может скрыть факт сбоя приложения (например, `CrashLoopBackOff` пода).
- **Экспоненциальный откат (Backoff):** При получении HTTP-статусов 429, 502 или 503 скрипт должен повторить запрос с увеличивающейся задержкой (например, 2s, 4s, 8s).

## Дополнительная информация

### См. также

- [RBAC — модель доступа, policy.csv и практические сценарии](./argocd_rbac_deep.md) — Детальное описание синтаксиса политик, встроенных ролей и маппинга групп.
- [AppProject — изоляция проектов и сред](./argocd_appproject_deep.md) — Настройка ролей проектов, генерация Project JWT токенов и ограничения дестинаций.
- [SSO и аутентификация через GitLab](./argocd_sso_gitlab.md) — Настройка внешней аутентификации пользователей и связывание групп с RBAC.
- [Синхронизация и политики жизненного цикла](./synchronization.md) — Синхронизационные волны, хуки, фазы и опции синхронизации.
- [Многопользовательская аренда (Multi-tenancy)](./argocd_multi_tenancy.md) — Изоляция команд, квоты и разграничение прав в больших кластерах.
- [Безопасность и hardening](./argocd_security_hardening.md) — Сетевые политики, mTLS, аудит-логирование и защищенный периметр.
- [Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md) — Метрики Prometheus, дашборды Grafana и устранение сбоев контроллера.
- [Ansible: Использование Vault](../../Ansible/Vault/basics.md) — Безопасное шифрование токенов доступа и учетных данных в плейбуках.
- [Интеграция GitLab CI с Kubernetes](../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md) — Построение GitOps пайплайнов на self-hosted раннерах.

### Официальная документация

- [Argo CD Server API Overview](https://argo-cd.readthedocs.io/en/stable/operator-manual/argocd-server-api/)
- [Argo CD Swagger / OpenAPI Reference](https://argo-cd.readthedocs.io/en/stable/operator-manual/api/)
- [Argo CD CLI Installation & Manual](https://argo-cd.readthedocs.io/en/stable/cli_installation/)
- [Ansible Collection argoproj.argocd Documentation](https://galaxy.ansible.com/ui/repo/published/argoproj/argocd/)
- [Terraform Argo CD Provider (argoproj-labs)](https://registry.terraform.io/providers/argoproj-labs/argocd/latest/docs)
