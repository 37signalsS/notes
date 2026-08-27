# Argo CD Image Updater — автоматизация обновления образов

**Argo CD Image Updater** — это контроллер для Argo CD, который отслеживает изменения в реестрах контейнеров (Container Registries) и автоматически обновляет версии образов в приложениях. Это позволяет реализовать цикл непрерывной доставки (CD), где публикация нового образа в реестре инициирует автоматический деплой без ручного редактирования Git-репозитория.

> **Актуальность (2026):** Argo CD Image Updater по-прежнему является рекомендуемым решением для автоматического обновления образов в Argo CD. Проект активно поддерживается, выпускаются регулярные релизы с исправлениями безопасности. Для архитектур, требующих нативной интеграции без зависимости от аннотаций, рекомендуется **Flux Image Automation** (CMFA Graduated).

## Предварительные требования

1. **Kubernetes кластер:** v1.22+.
2. **Argo CD установлен:** Версия 2.x или 3.x. Проверка: `kubectl get pods -n argocd` — все поды в статусе `Running`.
3. **Доступ к реестру:** Учетные данные для аутентификации в целевом реестре образов (Harbor, Docker Hub, AWS ECR, GCP GAR, Azure ACR).
4. **Хранилище:** Доступ к Git-репозиторию для записи (если используется Git write-back) или достаточный объем памяти в кластере (если используется API write-back).

## Определения

- **Image Updater** — вспомогательный контроллер Argo CD, опрашивающий API реестров образов (Harbor, Docker Hub, AWS ECR, GCP GAR, Azure ACR) на наличие новых тегов и автоматически обновляющий параметры приложений.
- **Write-back Method** — механизм фиксации изменений версии образа:
    - **Git (Declarative)** — запись обновленного тега обратно в Git-репозиторий в виде коммита (рекомендуется для GitOps).
    - **API (Imperative)** — временное переопределение параметров приложения в оперативной памяти Argo CD через его API (для Dev/QA сред).
- **Update Strategy** — алгоритм выбора «наилучшего» тега из списка доступных в реестре (SemVer, Latest, Name, Digest).
- **Pull Secret** — секрет Kubernetes типа `docker-registry`, используемый контроллером для аутентификации в приватных реестрах.
- **Registry Configuration** — конфигурация реестра в `argocd-image-updater-config`, определяющая URL API, аутентификацию и особенности работы с конкретным реестром.
- **Webhook Receiver** — HTTP-эндпоинт Image Updater, принимающий уведомления от реестров о появлении новых образов для немедленной проверки.

## Базовые концепции

### Архитектура взаимодействия

```
┌─────────────────────────────────────────────────────────────────────┐
│         Argo CD Image Updater: Архитектура автоматизации            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │  Container   │    │ argocd-image │    │  argocd-     │          │
│  │  Registry    │◀───│ -updater     │───▶│ application  │          │
│  │  (Harbor,    │    │ (Контроллер) │    │ controller   │          │
│  │   ECR, etc.) │    └──────────────┘    └──────────────┘          │
│  └──────────────┘           │                   │                   │
│         │                   ▼                   ▼                   │
│         │         ┌──────────────┐    ┌──────────────┐             │
│         │         │ argocd-image │    │  Application │             │
│         │         │ -updater-    │    │  (Git/Helm/  │             │
│         │         │ config       │    │   Kustomize) │             │
│         │         └──────────────┘    └──────────────┘             │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────┐    ┌──────────────┐                              │
│  │ Webhook      │    │  Git         │                              │
│  │ Receiver     │    │  Repository  │                              │
│  │ (Опционально)│    │  (Write-back)│                              │
│  └──────────────┘    └──────────────┘                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Механизм работы

1. **Обнаружение:** Контроллер сканирует объекты `Application` в кластере.
2. **Фильтрация:** Выбираются только приложения, имеющие аннотацию `argocd-image-updater.argoproj.io/image-list`.
3. **Опрос реестра:** Для каждого образа выполняется запрос к API реестра. Контроллер учитывает настройки аутентификации из `argocd-image-updater-config`.
4. **Сравнение:** Найденные теги фильтруются согласно стратегии (SemVer, Latest, Name, Digest).
5. **Обновление:** Если найден тег новее текущего, инициируется запись изменений.

### Write-back методы: Git vs API

| Критерий | Git write-back | API write-back |
| :--- | :--- | :--- |
| **Согласованность** | Высокая (Git — SSoT) | Средняя (параметры в памяти) |
| **Аудит** | Полная история коммитов | Только текущее состояние |
| **Сложность настройки** | Высокая (SSH/HTTPS ключи) | Низкая (токен ArgoCD) |
| **Конфликты** | Возможны при параллельных коммитах | Отсутствуют |
| **Рекомендуемая среда** | Production, Staging | Dev, QA, Testing |
| **Восстановление** | Через `git revert` | Через `argocd app rollback` |

### Аутентификация в реестрах

Image Updater поддерживает несколько способов авторизации:

- **Секреты Kubernetes:** Указание аннотации `secret://<namespace>/<secret-name>` для конкретного образа.
- **Глобальная настройка:** Определение учетных данных в ConfigMap `argocd-image-updater-config`.
- **Cloud IAM:** Использование ролей (например, IAM Roles for Service Accounts в AWS ECR).
- **Azure Workload Identity:** Для Azure ACR.
- **GCP Workload Identity:** Для GCP GAR.

**Важно:** Secret должен содержать ключи `username` и `password` в формате `docker-registry`:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: harbor-pull-secret
  namespace: argocd
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: <base64-encoded>
```

### Полный список аннотаций

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `argocd-image-updater.argoproj.io/image-list` | Список образов и фильтры | `app=my-registry/app:^1.0` |
| `argocd-image-updater.argoproj.io/<name>.update-strategy` | Стратегия обновления | `semver`, `latest`, `name`, `digest` |
| `argocd-image-updater.argoproj.io/write-back-method` | Метод записи | `git`, `argocd` |
| `argocd-image-updater.argoproj.io/write-back-target` | Цель записи | `git:secret:argocd/git-creds` |
| `argocd-image-updater.argoproj.io/<name>.kustomize.image-name` | Имя образа в Kustomize | `my-org/frontend` |
| `argocd-image-updater.argoproj.io/<name>.helm.image-name` | Имя параметра Helm | `image.repository` |
| `argocd-image-updater.argoproj.io/<name>.helm.image-tag` | Имя параметра тега | `image.tag` |
| `argocd-image-updater.argoproj.io/<name>.pull-secret` | Ссылка на Secret | `secret://argocd/pull-secret` |
| `argocd-image-updater.argoproj.io/<name>.registry` | Имя реестра из конфигурации | `harbor` |
| `argocd-image-updater.argoproj.io/force-update` | Принудительное обновление | `true` |

## Настройка и конфигурация

### Глобальные параметры (ConfigMap)

Основные настройки контроллера хранятся в `argocd-image-updater-config`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  # Интервал опроса реестров (по умолчанию 2 минуты)
  check.interval: "2m"
  # Настройка логирования
  log.level: "info"
  # Конфигурация реестров
  registries.conf: |
    registries:
    - name: Harbor
      prefix: harbor.example.com
      api_url: https://harbor.example.com/api/v2.0
      credentials: secret://argocd/harbor-pull-secret
    - name: DockerHub
      prefix: docker.io
      api_url: https://registry.hub.docker.com
      default: true
    - name: AWS ECR
      prefix: 123456789.dkr.ecr.us-east-1.amazonaws.com
      api_url: https://123456789.dkr.ecr.us-east-1.amazonaws.com
      credentials: secret://argocd/ecr-credentials
      default: false
    - name: GCP GAR
      prefix: us-central1-docker.pkg.dev
      api_url: https://us-central1-docker.pkg.dev
      credentials: secret://argocd/gar-credentials
```

**Параметры реестра:**

| Параметр | Описание | Обязательный |
| :--- | :--- | :--- |
| `name` | Уникальное имя реестра | Да |
| `prefix` | Префикс пути к образам | Да |
| `api_url` | URL API реестра | Да |
| `credentials` | Ссылка на Secret | Да |
| `default` | Реестр по умолчанию | Нет (false) |
| `insecure` | Отключение TLS-проверки | Нет (false) |

### Стратегии обновления

| Стратегия | Описание | Пример аннотации | Когда использовать |
| :--- | :--- | :--- | :--- |
| **SemVer** | Выбор по семантическому версионированию. Поддерживает диапазоны. | `semver:~1.2` | Стабильные релизы, Production |
| **Latest** | Выбор самого последнего созданного образа (по дате). | `latest` | Dev, Nightly builds |
| **Name** | Алфавитный порядок тегов. | `name` | Нестандартная нумерация |
| **Digest** | Использование SHA256 хеша (для неизменяемых тегов). | `digest` | Критические среды, Security |

**Примеры диапазонов SemVer:**
- `^1.0` — все версии 1.x.x
- `~1.2` — все версии 1.2.x
- `>=1.0 <2.0` — все версии от 1.0 до 2.0

## Практические сценарии

### Сценарий 1: Установка Image Updater

```bash
# 1. Добавление Helm-чарта ArgoCD
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# 2. Установка Image Updater
helm install argocd-image-updater argo/argocd-image-updater \
  --namespace argocd \
  --set config registries.conf=<path-to-config> \
  --set extraEnv[0].name=ARGOCD_IMAGE_UPDATER_CONFIG \
  --set extraEnv[0].value=/config/config.yaml

# 3. Проверка статуса
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-image-updater
```

### Сценарий 2: Автоматизация через Git write-back (Helm)

Это рекомендуемый метод для соблюдения принципов GitOps. Контроллер создает файл `.argocd-source-<app-name>.yaml` в репозитории.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  annotations:
    # 1. Список образов и фильтр (только минорные обновления v1.x)
    argocd-image-updater.argoproj.io/image-list: app-image=my-registry/api:^1.0
    # 2. Стратегия
    argocd-image-updater.argoproj.io/app-image.update-strategy: semver
    # 3. Метод записи
    argocd-image-updater.argoproj.io/write-back-method: git
    # 4. Настройка коммита
    argocd-image-updater.argoproj.io/write-back-target: git:secret:argocd/git-creds
spec:
  source:
    helm:
      # Параметр, который будет переопределен в файле-источнике
      parameters:
      - name: image.tag
        value: 1.0.0
```

### Сценарий 3: API write-back (Dev/QA)

Для Dev/QA сред, где не требуется история коммитов в Git:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app-dev
  annotations:
    argocd-image-updater.argoproj.io/image-list: app=my-registry/api
    argocd-image-updater.argoproj.io/app.update-strategy: latest
    argocd-image-updater.argoproj.io/write-back-method: argocd
spec:
  source:
    helm:
      parameters:
      - name: image.tag
        value: latest
```

### Сценарий 4: Использование Kustomize

Для Kustomize контроллер использует механизм переопределения образов (`images` в `kustomization.yaml`):

```yaml
annotations:
  argocd-image-updater.argoproj.io/image-list: web=my-org/frontend
  argocd-image-updater.argoproj.io/web.kustomize.image-name: my-org/frontend
  argocd-image-updater.argoproj.io/web.update-strategy: semver
  argocd-image-updater.argoproj.io/write-back-method: git
  argocd-image-updater.argoproj.io/write-back-target: git:secret:argocd/git-creds
```

### Сценарий 5: Несколько образов в одном приложении

```yaml
annotations:
  argocd-image-updater.argoproj.io/image-list: |
    frontend=my-registry/frontend,
    backend=my-registry/backend:^2.0
  argocd-image-updater.argoproj.io/frontend.update-strategy: semver
  argocd-image-updater.argoproj.io/backend.update-strategy: semver
  argocd-image-updater.argoproj.io/write-back-method: git
  argocd-image-updater.argoproj.io/write-back-target: git:secret:argocd/git-creds
```

### Сценарий 6: Webhook Receiver для немедленного обновления

Для немедленного отклика на появление новых образов настройте webhook receiver:

```yaml
# 1. Установка webhook receiver
apiVersion: v1
kind: Service
metadata:
  name: argocd-image-updater-webhook
  namespace: argocd
spec:
  ports:
  - port: 80
    targetPort: 8080
  selector:
    app.kubernetes.io/name: argocd-image-updater
---
# 2. Настройка Ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-image-updater-webhook
  namespace: argocd
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
  - host: image-updater.example.com
    http:
      paths:
      - path: /webhook
        pathType: Prefix
        backend:
          service:
            name: argocd-image-updater-webhook
            port:
              number: 80
```

### Сценарий 7: AWS ECR с IAM Roles

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  registries.conf: |
    registries:
    - name: AWS ECR
      prefix: 123456789.dkr.ecr.us-east-1.amazonaws.com
      api_url: https://123456789.dkr.ecr.us-east-1.amazonaws.com
      credentials: secret://argocd/ecr-credentials
      default: true
---
apiVersion: v1
kind: Secret
metadata:
  name: ecr-credentials
  namespace: argocd
type: Opaque
stringData:
  username: AWS
  password: <ecr-token>
```

### Сценарий 8: Digest Pinning для Production

```yaml
annotations:
  argocd-image-updater.argoproj.io/image-list: app=my-registry/api
  argocd-image-updater.argoproj.io/app.update-strategy: digest
  argocd-image-updater.argoproj.io/write-back-method: git
  argocd-image-updater.argoproj.io/write-back-target: git:secret:argocd/git-creds
```

## Сравнение с Flux Image Automation

| Характеристика | Argo CD Image Updater | Flux Image Automation |
| :--- | :--- | :--- |
| **Интеграция** | Внешний аддон (Labs проект). | Встроено в ядро (Image Controller). CNCF Graduated. |
| **Точность записи** | Создает отдельный YAML-файл (минимум конфликтов). | Изменяет оригинальный YAML (маркеры в комментариях). |
| **Управление** | В основном через аннотации. | Через Custom Resources (`ImagePolicy`, `ImageRepository`, `ImageUpdateAutomation`). |
| **Масштабирование** | Привязка к объекту `Application`. | Независимые политики для всего кластера. |
| **Управление тегами** | SemVer, Latest, Name, Digest. | SemVer, Numerical, Alphabetical. |
| **Multi-registry** | Да, через `registries.conf`. | Да, через `ImageRepository` CRD. |
| **Webhook** | Да, встроенный receiver. | Да, через `Receiver` CRD. |
| **Аудит** | Через Git-коммиты (Git write-back) или API логи. | Через Git-коммиты. |
| **Production readiness** | Да (используется в крупных компаниях). | Да (CNCF Graduated). |
| **Кривая обучения** | Низкая (аннотации). | Средняя (CRD). |

## Диагностика и отладка

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **No image found** | Нет аннотации `image-list` или неверное имя образа. | Проверьте аннотации приложения. Убедитесь, что образ доступен в реестре. |
| **Rate limit exceeded** | Превышен лимит запросов к реестру. | Увеличьте `check.interval`, добавьте аутентификацию, используйте приватный реестр. |
| **Failed to login** | Неверные учетные данные в Secret. | Проверьте Secret: `kubectl get secret -n argocd <secret-name> -o yaml`. |
| **No write-back method** | Не указан `write-back-method`. | Добавьте аннотацию `argocd-image-updater.argoproj.io/write-back-method`. |
| **Image not in registry** | Образ или тег не найден. | Проверьте имя образа и доступные теги: `crane ls <image>`. |
| **Git write-back failed** | Ошибка доступа к Git-репозиторию. | Проверьте Secret с credentials для Git. Убедитесь, что репозиторий доступен. |
| **Invalid semver range** | Неверный синтаксис диапазона. | Используйте стандартный синтаксис SemVer: `^1.0`, `~1.2`, `>=1.0 <2.0`. |

### Полезные команды для отладки

```bash
# Просмотр логов контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater --tail=100

# Просмотр конфигурации реестров
kubectl get configmap argocd-image-updater-config -n argocd -o yaml

# Просмотр приложений с аннотациями Image Updater
kubectl get applications -n argocd -o json | jq -r '.items[] | select(.metadata.annotations["argocd-image-updater.argoproj.io/image-list"] != null) | .metadata.name'

# Проверка доступных тегов в реестре
crane ls harbor.example.com/my-app --limit 10

# Принудительное обновление приложения
kubectl annotate app my-app -n argocd argocd-image-updater.argoproj.io/force-update=true

# Проверка статуса Image Updater
kubectl get deployment argocd-image-updater -n argocd

# Просмотр событий Image Updater
kubectl get events -n argocd --field-selector involvedObject.name=argocd-image-updater
```

### Валидация конфигурации

```bash
# Проверка доступности реестра
curl -s https://harbor.example.com/api/v2.0/health | jq .

# Проверка credentials
crane auth whoami https://harbor.example.com

# Просмотр информации об образе
crane manifest harbor.example.com/my-app:latest
```

## Рекомендации и лучшие практики

### Безопасность

- **Приватные реестры:** Всегда используйте аутентификацию для доступа к реестрам.
- **Least Privilege:** Создавайте отдельные Service Account для Image Updater с минимальными правами.
- **Secrets:** Храните credentials в Kubernetes Secrets, не в ConfigMap.
- **Image Signing:** Используйте Cosign или Notary для подписи образов.
- **Webhook Security:** Настройте webhook secret для проверки подлинности запросов.

### Производительность

- **Интервал опроса:** Настройте `check.interval` в зависимости от требуемой отзывчивости (по умолчанию 2 минуты).
- **Кеширование:** Image Updater кеширует результаты запросов к реестру.
- **Rate Limiting:** Для публичных реестров (Docker Hub) используйте аутентификацию для увеличения лимитов.
- **Параллелизм:** Контроллер обрабатывает приложения параллельно, но реестры могут иметь ограничения.

### Надежность

- **Health Checks:** Image Updater проверяет доступность реестра перед обновлением.
- **Retry Logic:** Автоматические повторные попытки при временных ошибках.
- **Graceful Degradation:** При недоступности реестра Image Updater продолжает работать с последней известной версией.
- **Мониторинг:** Добавьте алерты на CrashLoopBackOff пода Image Updater.

### Устранение проблем

- **Логирование:** Включите `log.level: debug` для отладки, затем верните `info`.
- **Тестирование:** Используйте Image Policy для тестирования обновлений в Dev/QA среде.
- **Откат:** При проблемах с обновлением используйте `argocd app rollback` или `git revert`.

## Ограничения и edge cases

### Ограничения

1. **Только чтение образов:** Image Updater не может создавать или удалять образы в реестре.
2. **Одновременная запись:** При использовании Git write-back возможны конфликты коммитов при параллельных обновлениях.
3. **Rate Limits:** Публичные реестры (Docker Hub) имеют ограничения на количество запросов.
4. **Docker Hub Rate Limiting:** Без аутентификации — 100 запросов в 6 часов дляanonymous, 200 дляauthenticated.
5. **OCI:** Поддержка OCI-реестров ограничена (не все API доступны).

### Edge Cases

1. **Несколько приложений:** Image Updater может обновлять несколько приложений одновременно.
2. **Диапазоны SemVer:** При использовании `^1.0` могут обновляться только минорные версии.
3. **Digest Pinning:** При фиксации по дайджесту обновления не будут применяться автоматически.
4. **Latest Tag:** Использование `latest` не рекомендуется для Production (нарушает детерминизм).
5. **Временные ошибки реестра:** Image Updater повторяет попытки при временных ошибках.
6. **Конфликты Git:** При параллельных коммитах в Git возможны конфликты.
7. **Аннотации:** Image Updater не валидирует аннотации — ошибки в синтаксисе приводят к тихим сбоям.

## Дополнительная информация

### См. также

- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.

### Связанные документы

- [Argo CD: Обзор системы](./argocd_overview.md)
- [Синхронизация в Argo CD](./synchronization.md)
- [Версионирование и тегирование образов](../../Docker/Docker_registries/image_versioning_and_tagging.md)

### Официальные ресурсы

- [Документация Argo CD Image Updater](https://argocd-image-updater.readthedocs.io/)
- [Argo CD Image Updater — GitHub](https://github.com/argoproj-labs/argocd-image-updater)
