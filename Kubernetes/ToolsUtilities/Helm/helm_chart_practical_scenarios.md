# Практические сценарии Helm-чартов

Рабочие процессы создания, оркестрации и промышленного развёртывания Helm-чартов: от базовой структуры до управления сотнями микросервисов и сложными стеками в среде **v4 (стандарт 2026 года)**.

---

## Определения

| Термин | Описание |
|--------|----------|
| **helm create** | Генерация стандартного скелета чарта. См. [Структура Helm-чарта](./helm_chart_structure.md). |
| **Shared Chart (Общий чарт)** | Универсальный чарт-«движок», используемый для деплоя множества однотипных сервисов через специфичные `values.yaml`. |
| **Umbrella Chart (Зонтичный чарт)** | Чарт-агрегатор, объединяющий другие чарты как зависимости для деплоя всего стека (например, мониторинга). |
| **Library Chart (Библиотечный чарт)** | Чарт типа `library`, предоставляющий только именованные шаблоны для переиспользования. См. [Зависимости и Library Charts](./helm_dependencies_and_library_charts.md). |
| **Server-Side Apply (SSA)** | (v4) Механизм Kubernetes, делегирующий API-серверу логику слияния и управления полями (Field Ownership). |
| **Environment Promotion** | Паттерн поэтапного продвижения конфигурации через окружения (dev → staging → prod) с иммутабельностью артефактов. |
| **Values Layering** | Многослойная система переопределения значений: base → environment → cluster → runtime. |
| **Diff-before-apply** | Паттерн визуализации изменений перед применением через `helm-diff`. |

---

## Основные концепции

### Жизненный цикл разработки и валидация

Процесс создания промышленного чарта включает многоуровневую проверку:
1.  **Линтинг:** `helm lint` — проверка структуры и синтаксиса `Chart.yaml`.
2.  **Локальный рендеринг:** `helm template` — генерация YAML без кластера для отладки логики.
3.  **Server-side Dry-run:** (v4) `helm install --dry-run --debug` — проверка на стороне API-сервера (права, схемы, квоты) без применения изменений.
4.  **Diff:** `helm diff upgrade` — визуализация конкретных изменений, которые будут применены к кластеру.
5.  **Валидация схемы:** `values.schema.json` — автоматическая проверка типов и ограничений параметров.

### Управление состоянием и конфликтами в v4

Использование SSA позволяет Helm корректно сосуществовать с внешними контроллерами (Sidecar-инжекторы, HPA, Mesh-прокси).
- **Разрешение конфликтов:** Если поле управляется другим контроллером, Helm v4 не затирает его, если не указан флаг `--force-conflicts`.
- **Проверка готовности:** Helm v4 использует библиотеку `kstatus` для унифицированного ожидания готовности ресурсов (`--wait`).

### Иерархия приоритетов значений

Helm применяет значения в строгом порядке (от низшего к высшему приоритету):

1.  `values.yaml` по умолчанию в чарте (самый низкий приоритет)
2.  Файлы `-f values.yaml` — порядок объединения: первый файл → второй → третий (каждый перезаписывает предыдущий)
3.  `--set` / `--set-string` флаги CLI (самый высокий приоритет)
4.  Встроенные значения (`.Release.Name`, `.Release.Namespace`)

**Правило:** Базовый `values.yaml` коммитится в VCS. Environment-файлы (`values-prod.yaml`) — тоже в VCS. Runtime-флаги (`--set`) — только для временных override в CI, не для постоянных конфигураций.

---

## Практические сценарии

### 1. Структура и создание промышленного чарта

Для Production-сред используется расширенная структура, включающая поддержку CRD и тестов.

```bash
helm create my-app
```

**Рекомендуемая структура:**
```
production-chart/
├── Chart.yaml              # Метаданные (v4: apiVersion: v2)
├── Chart.lock              # Зафиксированные версии зависимостей
├── values.yaml             # Глобальные значения по умолчанию
├── values-production.yaml  # Переопределения для Production
├── values-staging.yaml     # Переопределения для Staging
├── values.schema.json      # JSON Schema для валидации values
├── crds/                   # (v4) Приоритетная установка CRD
├── templates/
│   ├── _helpers.tpl        # Вспомогательные функции (Named Templates)
│   ├── deployment.yaml     # Манифесты с поддержкой SSA-аннотаций
│   ├── ...
│   └── tests/              # Тесты (SSoT: helm_hooks_and_tests.md)
│       └── health-check.yaml
└── charts/                 # Загруженные зависимости (Subcharts)
```

### 2. Многоокружная стратегия через значения (values)

Использование слоев конфигурации позволяет избежать дублирования шаблонов. Подробный разбор иерархии значений см. в [Управление версиями Helm](./helm_release_versioning.md).

**Цепочка переопределения (пример):**
```
values.yaml              → реплики: 1, image: nginx:1.25, resources: минимальные
  ↓
values-staging.yaml      → реплики: 2, image: nginx:1.25, resources: средние, ingress.enabled: true
  ↓
values-production.yaml   → реплики: 5, image: nginx:1.27, resources: максимальные, autoscaling: true
  ↓
--set image.tag=1.28     →runtime override (только для CI/одноразовых изменений)
```

**Применение (порядок флагов критичен):**
```bash
# Значения из values-production.yaml перезапишут базовый values.yaml
helm upgrade --install app ./chart \
  -f values.yaml \
  -f values-production.yaml \
  --namespace prod \
  --atomic \
  --timeout 10m
```

**Продвинутый паттерн: values overlay с defaults:**
```bash
# Базовый → окружение → кластер → runtime
helm upgrade --install app ./chart \
  -f values.yaml \
  -f values-staging.yaml \
  -f values-staging-eu-west-1.yaml \
  --set image.tag=1.28-rc1 \
  --namespace staging
```

### 3. Паттерн «Зонтичный чарт» (Umbrella Chart)

Идеален для развёртывания инфраструктурных стеков как единого релиза. Подробнее о зависимостях см. [Зависимости и Library Charts](./helm_dependencies_and_library_charts.md).

**monitoring-stack/Chart.yaml:**
```yaml
apiVersion: v2
name: monitoring-stack
version: 1.0.0
dependencies:
  - name: prometheus
    version: "25.x.x"
    repository: "oci://registry.example.com/charts"
    condition: prometheus.enabled
  - name: grafana
    version: "7.x.x"
    repository: "oci://registry.example.com/charts"
    condition: grafana.enabled
  - name: loki
    version: "5.x.x"
    repository: "oci://registry.example.com/charts"
    condition: loki.enabled
  - name: tempo
    version: "1.x.x"
    repository: "oci://registry.example.com/charts"
    condition: tempo.enabled
    tags:
      - tracing
```

**monitoring-stack/values.yaml:**
```yaml
# Включение/отключение компонентов стека
prometheus:
  enabled: true
  retention: 15d
  storageSize: 50Gi

grafana:
  enabled: true
  adminPassword: ""  # Переопределять через secrets!

loki:
  enabled: true
  storage:
    type: filesystem

tempo:
  enabled: false  # Включать при необходимости tracing

# Теги для группового управления
tags:
  tracing: false
```

**Управление стеком:**
```bash
# Установка всего стека
helm upgrade --install monitoring ./monitoring-stack \
  -f values-production.yaml \
  --namespace monitoring --create-namespace

# Установка только Prometheus + Grafana (без Loki/Tempo)
helm upgrade --install monitoring ./monitoring-stack \
  --set prometheus.enabled=true \
  --set grafana.enabled=true \
  --set loki.enabled=false \
  --set tempo.enabled=false \
  --namespace monitoring

# Обновление одного компонента (переопределение через сабчарт)
helm upgrade --install monitoring ./monitoring-stack \
  --set prometheus.version=26.x.x \
  --namespace monitoring
```

**Ограничения Umbrella Charts:**
- Сложность деления values между компонентами при большом количестве зависимостей.
- Один `helm upgrade` обновляет все компоненты — нет возможности обновить только Prometheus без Grafana.
- Для серийного управления используйте [Helmfile](./helmfile_overview.md) или [Helmwave](./helmwave_overview.md).

### 4. Масштабирование через Общий чарт (Shared Chart)

Для 100+ микросервисов создаётся один универсальный чарт-движок в OCI-реестре. Каждый сервис — это только `values.yaml` с параметрами.

**Структура репозитория конфигураций:**
```
infra-gitops/
├── engine/                    # Shared Chart (чарт-движок)
│   ├── Chart.yaml
│   ├── values.yaml
│   ├── values.schema.json
│   └── templates/
│       ├── _helpers.tpl
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── ingress.yaml
│       ├── hpa.yaml
│       ├── pdb.yaml
│       ├── configmap.yaml
│       ├── secret.yaml
│       └── networkpolicy.yaml
└── apps/
    ├── auth-svc/
    │   └── values.yaml       # Только параметры для auth
    ├── api-gateway/
    │   └── values.yaml
    ├── payment-svc/
    │   └── values.yaml
    └── notification-svc/
        └── values.yaml
```

**Пример values.yaml для конкретного сервиса (apps/auth-svc/values.yaml):**
```yaml
replicaCount: 3

image:
  repository: registry.example.com/auth-svc
  tag: "2.1.0"
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 8080
  targetPort: 8080

ingress:
  enabled: true
  className: nginx
  host: auth.example.com
  path: /
  tls:
    - secretName: auth-tls
      hosts:
        - auth.example.com

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70

resources:
  limits:
    cpu: 1000m
    memory: 512Mi
  requests:
    cpu: 250m
    memory: 256Mi

env:
  DB_HOST: postgresql.database.svc.cluster.local
  REDIS_HOST: redis-master.cache.svc.cluster.local

envFromSecrets:
  - name: DB_PASSWORD
    secretName: auth-db-creds
    secretKey: password
```

**Публикация движка в OCI-реестр:**
```bash
# Упаковка и публикация
helm package ./engine
helm push engine-1.0.0.tgz oci://registry.example.com/charts

# Использование из OCI-реестра
helm upgrade --install auth-svc oci://registry.example.com/charts/engine \
  --version 1.0.0 \
  -f apps/auth-svc/values.yaml \
  --namespace auth --create-namespace
```

**Оркестрация через ArgoCD ApplicationSet:**
Автоматизирует создание сотен приложений на базе одного чарта.
```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: microservices
  namespace: argocd
spec:
  generators:
    - git:
        repoURL: https://github.com/org/infra-gitops.git
        revision: main
        directories:
          - path: "apps/*"
  template:
    metadata:
      name: "{{ path.basename }}"
    spec:
      project: default
      source:
        repoURL: https://github.com/org/infra-gitops.git
        targetRevision: main
        path: engine
        helm:
          valueFiles:
            - "../../apps/{{ path.basename }}/values.yaml"
      destination:
        server: https://kubernetes.default.svc
        namespace: "{{ path.basename }}"
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

### 5. Безопасное управление секретами (Helm Secrets + SOPS)

Шифрование чувствительных данных (пароли, ключи) с использованием KMS или PGP. Подробнее см. [Безопасность Helm](./Advanced/security_best_practices.md) и [Helm + секреты](../../Base/secrets/helm_secrets.md).

**Рабочий процесс:**
1.  Шифрование: `sops -e secrets.yaml > secrets.enc.yaml`.
2.  Развёртывание:
```bash
# Плагин расшифровывает значения в памяти перед рендерингом
helm secrets upgrade --install my-app ./chart \
  -f values.yaml \
  -f secrets.enc.yaml \
  --namespace prod
```

**Сравнение подходов к секретам:**

| Подход | Механизм | Плюсы | Минусы |
|--------|----------|-------|--------|
| **helm-secrets + SOPS** | Шифрование файлов в Git | Нативная интеграция с Helm, Git-friendly | Требует KMS/PGP инфраструктуру |
| **External Secrets Operator** | Синхронизация из Vault/AWS SM | Автоматическая ротация, аудит | Дополнительная зависимость |
| **Sealed Secrets** | Шифрование в кластере | Простота, Git-friendly | Шифрование/дешифрование в кластере |
| **CSI Driver** | Монтирование секретов из Vault | Прозрачно для приложения | Сложность настройки |

**Важно:** Не храните секреты в `values.yaml`. Если секрет передаётся через `--set` или `-f`, он попадает в историю Helm (Secret в кластере) и может быть извлечён через `helm get values`.

### 6. Проверка работоспособности (Helm Test)

Автоматизированная верификация релиза после деплоя. Детально: [Хуки и тестирование](./helm_hooks_and_tests.md).

**Пример теста (templates/tests/health-check.yaml):**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "mychart.fullname" . }}-test"
  annotations:
    "helm.sh/hook": test
spec:
  containers:
    - name: check
      image: curlimages/curl
      command: ['curl', '-f', '{{ include "mychart.fullname" . }}:{{ .Values.service.port }}/health']
  restartPolicy: Never
```

### 7. Дифф перед применением (helm-diff)

Паттерн визуализации изменений перед их применением к кластеру. Критичен для production-сред.

**Установка:**
```bash
helm plugin install https://github.com/databus23/helm-diff
```

**Использование:**
```bash
# Сравнение текущего состояния с предстоящим upgrade
helm diff upgrade my-app ./chart \
  -f values.yaml \
  -f values-production.yaml \
  --namespace prod

# С опциональным context lines
helm diff upgrade my-app ./chart \
  -f values-production.yaml \
  --context 5 \
  --namespace prod

# Автоматическое применение, если diff пуст
helm diff upgrade my-app ./chart \
  -f values-production.yaml \
  --namespace prod \
  --suppress -a  # Подавить вывод, если изменений нет
```

**Интеграция в CI/CD:**
```yaml
# GitLab CI
helm-diff:
  stage: validate
  script:
    - helm plugin install https://github.com/databus23/helm-diff
    - helm diff upgrade my-app ./chart -f values-production.yaml --namespace prod --color
  allow_failure: false

helm-deploy:
  stage: deploy
  needs: [helm-diff]
  script:
    - helm upgrade --install my-app ./chart -f values-production.yaml --namespace prod --atomic
```

### 8. Production стратегии деплоя

Helm сам по себе не управляет трафиком, но обеспечивает инфраструктуру для продвинутых стратегий.

#### Blue/Green деплой

Два независимых релиза с переключением трафика через Service.

```bash
# Blue — текущая версия
helm upgrade --install app-blue ./chart \
  -f values.yaml \
  --set image.tag=1.25.0 \
  --set service.selector.version=blue \
  --namespace app

# Green — новая версия (тестируется отдельно)
helm upgrade --install app-green ./chart \
  -f values.yaml \
  --set image.tag=1.26.0 \
  --set service.selector.version=green \
  --namespace app

# Переключение трафика (меняем selector в Service)
kubectl patch service app -n app -p '{"spec":{"selector":{"version":"green"}}}'

# Удаление старой версии (после проверки)
helm uninstall app-blue --namespace app
```

#### Canary деплой

Малая часть трафика направляется на новую версию.

```bash
# Основной релиз (90% трафика)
helm upgrade --install app ./chart \
  -f values.yaml \
  --set image.tag=1.25.0 \
  --set replicaCount=9 \
  --namespace app

# Canary релиз (10% трафика)
helm upgrade --install app-canary ./chart \
  -f values.yaml \
  --set image.tag=1.26.0 \
  --set replicaCount=1 \
  --set service.name=app-canary \
  --namespace app
```

**Важно для SSA:** При переключении трафика оба релиза (blue и green) управляют **разными** Deployment-ами, поэтому конфликтов field ownership не возникает.

### 9. Стратегии отката в production

#### Быстрый откат к предыдущей ревизии

```bash
# Откат к последней рабочей версии
helm rollback my-app 5 --namespace prod

# Просмотр истории перед откатом
helm history my-app --namespace prod --max 10

# Откат с ожиданием готовности
helm rollback my-app 5 --namespace prod --wait --timeout 5m
```

#### Атомарный деплой с автоматическим откатом

```bash
helm upgrade --install my-app ./chart \
  -f values-production.yaml \
  --namespace prod \
  --atomic \
  --wait \
  --wait-for-jobs \
  --timeout 10m \
  --cleanup-on-fail \
  --history-max 5
```

**Флаги и их назначение:**
- `--atomic` — автоматический откат при неуспехе rollout
- `--wait` — ожидание готовности всех подов и сервисов
- `--wait-for-jobs` — ожидание завершения Job'ов (миграции БД)
- `--timeout 10m` — таймаут (увеличьте для долгих миграций)
- `--cleanup-on-fail` — удаление ресурсов неудавшегося релиза
- `--history-max 5` — ограничение истории для минимизации Secret-объектов

#### Принудительный откат при pending状态下

```bash
# Если релиз застрял в pending状态下
helm rollback my-app 5 --namespace prod --force --cleanup-on-fail

# Или удаление и переустановка
helm uninstall my-app --namespace prod --keep-history
helm install my-app ./chart -f values-production.yaml --namespace prod --atomic
```

### 10. CI/CD оркестрация

#### Полный pipeline (GitLab CI)

```yaml
stages:
  - lint
  - test
  - build
  - validate
  - deploy-staging
  - deploy-production

variables:
  CHART_DIR: ./chart
  OCI_REGISTRY: oci://registry.example.com/charts

helm-lint:
  stage: lint
  image: alpine/helm:3.14.0
  script:
    - helm lint $CHART_DIR --strict
    - helm template test-release $CHART_DIR > /dev/null

helm-test:
  stage: test
  image: alpine/helm:3.14.0
  script:
    - helm unittest $CHART_DIR
    - helm template test-release $CHART_DIR | kubeconform -strict -kubernetes-version 1.30.0

helm-package:
  stage: build
  image: alpine/helm:3.14.0
  script:
    - helm package $CHART_DIR --version $CI_COMMIT_TAG
    - helm push *.tgz $OCI_REGISTRY
  rules:
    - if: $CI_COMMIT_TAG

validate-staging:
  stage: validate
  image: alpine/helm:3.14.0
  script:
    - helm plugin install https://github.com/databus23/helm-diff
    - helm diff upgrade my-app $CHART_DIR -f values-staging.yaml --namespace staging
    - helm upgrade --install my-app $CHART_DIR -f values-staging.yaml --namespace staging --dry-run --debug

deploy-staging:
  stage: deploy-staging
  image: alpine/helm:3.14.0
  script:
    - helm upgrade --install my-app $CHART_DIR -f values-staging.yaml --namespace staging --atomic --timeout 10m
  environment:
    name: staging

deploy-production:
  stage: deploy-production
  image: alpine/helm:3.14.0
  script:
    - helm upgrade --install my-app $CHART_DIR -f values-production.yaml --namespace prod --atomic --wait --timeout 15m
  environment:
    name: production
  when: manual
  rules:
    - if: $CI_COMMIT_TAG
```

### 11. Multi-tenancy паттерны

Изоляция нескольких команд или проектов в одном кластере через Namespace и RBAC.

```bash
# Создание namespace для каждой команды
for team in backend frontend data; do
  kubectl create namespace team-${team}
done

# Установка сервиса в namespace команды
helm upgrade --install auth-svc ./chart \
  -f values.yaml \
  -f values-team-backend.yaml \
  --namespace team-backend

# Ограничение через ResourceQuota
kubectl apply -f - <<EOF
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-quota
  namespace: team-backend
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
    pods: "20"
EOF
```

### 12. Дистрибуция чартов

#### OCI Registry (рекомендуется для v4)

```bash
# Публикация
helm package ./my-chart
helm push my-chart-1.0.0.tgz oci://registry.example.com/charts

# Установка из OCI
helm install my-app oci://registry.example.com/charts/my-chart \
  --version 1.0.0 \
  -f values.yaml

# Использование дигеста для иммутабельности
helm install my-app oci://registry.example.com/charts/my-chart@sha256:abc123...
```

#### Локальный репозиторий (для on-premise)

```bash
# Запуск ChartMuseum
docker run -d -p 8080:8080 \
  -e STORAGE=local \
  -e STORAGE_LOCAL_ROOTDIR=/charts \
  -v /data/charts:/charts \
  chartmuseum/chartmuseum:latest

# Добавление репозитория
helm repo add local http://localhost:8080
helm repo update

# Публикация
helm package ./my-chart
helm push my-chart-1.0.0.tgz local
```

---

## Диагностика и устранение неполадок

### Частые ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Error: rendered manifests contain a resource that already exists` | Ресурс создан вне Helm (kubectl) | `helm install --take-over` или удалите вручную |
| `Error: UPGRADE FAILED: conflict` | Конфликт SSA field ownership | Используйте `--force-conflicts` при миграции |
| `Error: timed out waiting for resources` | `--timeout` слишком мал | Увеличьте timeout, проверьте readiness подов |
| `Error: release already exists` | Имя релиза занято | Используйте `--name` или удалите старый релиз |
| `Error: chart not found` | Неверный путь или версия | Проверьте `helm repo list`, `helm search repo` |
| `Error: validation error` | values не проходят валидацию схемы | Проверьте `values.schema.json` |

### Полезные команды диагностики

```bash
# Просмотр всех релизов в namespace
helm list -n prod

# Детали конкретного релиза
helm status my-app -n prod

# История изменений
helm history my-app -n prod --max 10

# Сравнение текущего состояния с предстоящим upgrade
helm diff upgrade my-app ./chart -f values.yaml -n prod

# Рендер конкретного шаблона для отладки
helm template my-app ./chart --show-only templates/deployment.yaml

# Проверка зависимостей
helm dependency list ./chart
```

---

## Дополнительная информация

### Сравнение подходов к масштабированию

| Параметр | Shared Chart | Skeleton Pattern | Umbrella Chart | Library Chart |
| :--- | :--- | :--- | :--- | :--- |
| **Назначение** | Единый шаблон для всех | Копия эталона для сервиса | Агрегация независимых чартов | Общая логика в `_helpers` |
| **Развёртывание** | Напрямую (`helm install`) | Напрямую | Как единый релиз | Только как зависимость |
| **Автономия сервисов** | Низкая (общий код) | Высокая (своя копия) | Средняя | Зависит от потребителя |
| **Масштабируемость** | Высокая (ArgoCD) | Средняя | Низкая | Средняя |
| **Обновление** | Мгновенное для всех | Покомпонентное | Пакетное | Покомпонентное |
| **Сложность** | Средняя | Низкая | Высокая | Высокая |

**Когда выбирать Shared Chart:**
- Сервисы однотипны и отличаются только параметрами (replicas, resources, env).
- Нужно централизованно обновлять логику для всех сервисов одновременно.
- Важна единообразная безопасность и compliance.

**Когда выбирать Skeleton Pattern:**
- Сервисы имеют существенные различия в конфигурации.
- Команда сервиса автономна и не хочет зависеть от общего чарта.
- Количество сервисов < 20.

**Когда выбирать Umbrella Chart:**
- Компоненты сильно связаны и должны развёртываться вместе (стек мониторинга, CI/CD).
- Нужен единый жизненный цикл для группы связанных сервисов.

### Интеграция с оркестраторами

| Инструмент | Описание | SSoT |
|------------|----------|------|
| **[Helmfile](./helmfile_overview.md)** | Декларативный оркестратор для управления группами релизов | `helmfile_overview.md` |
| **[Helmwave](./helmwave_overview.md)** | Современная альтернатива на Go с поддержкой DAG | `helmwave_overview.md` |
| **ArgoCD** | GitOps-контроллер с нативной поддержкой Helm | `GitOps/ArgoCD/helm_integration.md` |
| **Flux CD** | GitOps-контроллер с HelmRelease CRD | `GitOps/Flux/` |

### Инструменты

| Инструмент | Назначение |
|------------|-----------|
| **helm-diff** | Визуализация изменений перед применением |
| **helm-unittest** | Юнит-тесты шаблонов Helm |
| **kubeconform** | Валидация рендеренных манифестов |
| **chart-testing (ct)** | Автоматическая валидация и тестирование чартов |
| **ChartMuseum** | Приватный OCI-совместимый реестр чартов |
| **Cosign** | Подпись и верификация чартов |
| **conftest** | Policy-as-code проверка (OPA Rego) |

### См. также

- [Зависимости и Library Charts](./helm_dependencies_and_library_charts.md) — детали работы с `type: library`.
- [Основные команды и рабочий процесс Helm](./helm_commands_and_workflow.md) — SSA, OCI и жизненный цикл.
- [Скелетный паттерн (Skeleton Pattern)](./helm_skeleton_pattern.md) — альтернатива Shared Chart.
- [Управление версиями Helm](./helm_release_versioning.md) — SemVer, ревизии и история.
- [Паттерны и устранение неисправностей](./Advanced/patterns_troubleshooting.md) — решение проблем с SSA и лимитами.
- [Продвинутые сценарии Helm](./Advanced/scenarios.md) — OCI, пост-рендеринг и адаптивные чарты.
- [Безопасность Helm](./Advanced/security_best_practices.md) — шифрование, RBAC, admission-контроллеры.
