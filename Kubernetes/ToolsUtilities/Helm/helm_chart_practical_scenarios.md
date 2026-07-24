# Практические сценарии Helm-чартов

Рабочие процессы создания, оркестрации и промышленного развёртывания Helm-чартов: от базовой структуры до управления сотнями микросервисов и сложными стеками.

---

## Определения

| Термин | Описание |
|--------|----------|
| **helm create** | Команда генерации стандартной структуры чарта (скелета). См. [Структура Helm-чарта](./helm_chart_structure.md). |
| **Shared Chart (Общий чарт)** | Универсальный чарт с шаблонами, используемый для деплоя множества однотипных сервисов через передачу специфичных `values.yaml`. |
| **Umbrella Chart (Зонтичный чарт)** | Чарт-агрегатор, который не содержит собственных шаблонов, а объединяет другие чарты как зависимости для деплоя всего стека (например, мониторинга). |
| **Library Chart (Библиотечный чарт)** | Чарт типа `library`, содержащий только именованные шаблоны (`define`), которые переиспользуются в других чартах через `include`. |
| **Helm Test** | Встроенный механизм проверки работоспособности релиза после установки/обновления. |

---

## Основные концепции

### Валидация и жизненный цикл разработки

Процесс создания чарта всегда включает три этапа проверки:
1.  **Синтаксическая:** `helm lint` — проверка корректности `Chart.yaml` и структуры.
2.  **Локальный рендер:** `helm template` — генерация YAML без кластера для проверки логики шаблонов.
3.  **Имитация установки:** `helm install --dry-run --debug` — проверка на стороне Kubernetes API (права доступа, схемы ресурсов).

### Управление зависимостями

`helm dependency update` скачивает актуальные версии зависимостей (описанных в `Chart.yaml`) в директорию `charts/` и создаёт `Chart.lock`. `helm dependency build` — восстанавливает зависимости строго по версиям из `Chart.lock`. Детали — в разделе [зависимости](./helm_dependencies_and_library_charts.md).

---

## Практические сценарии

### 1. Структура и создание production-чарта

```bash
helm create my-app
```

**Рекомендуемая структура промышленного чарта:**
```
production-chart/
├── Chart.yaml              # Метаданные (version, appVersion)
├── Chart.lock              # Зафиксированные версии зависимостей
├── values.yaml             # Базовые значения (по умолчанию)
├── values-production.yaml  # Переопределения для prod
├── values-staging.yaml     # Переопределения для staging
├── templates/
│   ├── _helpers.tpl        # Вспомогательные функции (named templates)
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secrets.yaml
│   ├── hpa.yaml            # HorizontalPodAutoscaler
│   ├── pdb.yaml            # PodDisruptionBudget
│   └── tests/              # Тесты для helm test
│       └── test-connection.yaml
└── charts/                 # Загруженные зависимости (после dependency update)
    └── postgresql-12.1.0.tgz
```

### 2. Многоокружная стратегия через values-файлы

Для управления конфигурациями в разных окружениях (dev, staging, production) используется принцип многослойности.

**values.yaml (базовый файл):**
Содержит минимальные значения и служит документацией.
```yaml
replicaCount: 1
ingress:
  enabled: false
# resources:  # Оставляем структуру как подсказку
#   limits:
#     cpu: 100m
```

**values-production.yaml (переопределения):**
```yaml
replicaCount: 3
ingress:
  enabled: true
  hosts:
    - host: app.prod.com
resources:
  limits:
    cpu: 2000m
    memory: 4Gi
```

**Применение (порядок флагов важен):**
```bash
# Значения из values-production.yaml перезапишут значения из values.yaml
helm upgrade --install app ./chart -f values.yaml -f values-production.yaml -n prod --atomic
```

### 3. Паттерн «Зонтичный чарт» (Umbrella Chart)

Используется для развёртывания целого стека (например, мониторинга) как единого релиза.

**monitoring-stack/Chart.yaml:**
```yaml
apiVersion: v2
name: monitoring-stack
version: 1.0.0
dependencies:
  - name: prometheus
    version: "25.x.x"
    repository: "https://prometheus-community.github.io/helm-charts"
  - name: grafana
    version: "7.x.x"
    repository: "https://grafana.github.io/helm-charts"
```

**monitoring-stack/values.yaml:**
Управление дочерними чартами через ключи, соответствующие их именам:
```yaml
prometheus:
  server:
    retention: 30d
grafana:
  adminPassword: "admin"
  ingress:
    enabled: true
```

### 4. Shared-чарт для масштабирования (100+ микросервисов)

Для однотипных сервисов создаётся один **shared-чарт** (движок), публикуемый в OCI-реестре.

**Структура репозитория:**
```
infra/
├── charts/shared-engine/      # Один чарт на все сервисы
│   ├── Chart.yaml
│   ├── templates/ (deployment, service, ingress и т.д.)
│   └── values.yaml            # Глобальные дефолты
└── services/
    ├── auth-svc/values.yaml   # Только специфичные настройки сервиса
    └── pay-svc/values.yaml
```

**values.yaml сервиса (auth-svc):**
```yaml
image:
  repository: my-org/auth-svc
  tag: v2.1.0
resources:
  requests: { cpu: 200m, memory: 512Mi }
```

**Оркестрация через ArgoCD ApplicationSet:**
Автоматически создает приложения для всех папок в `services/`.
```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
spec:
  generators:
    - git:
        repoURL: https://github.com/org/infra.git
        directories: [{path: "services/*"}]
  template:
    metadata:
      name: '{{ path.basename }}'
    spec:
      source:
        repoURL: https://github.com/org/infra.git
        path: charts/shared-engine
        helm:
          valueFiles:
            - ../../services/{{ path.basename }}/values.yaml
            - ../../values-prod.yaml
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{ path.basename }}'
```

### 5. Безопасное хранение секретов (Helm Secrets + SOPS)

Интеграция с `mozilla/sops` позволяет хранить зашифрованные секреты в Git.

**Использование:**
1.  Шифруем файл: `sops -e secrets.yaml > secrets.enc.yaml`.
2.  Деплоим:
```bash
# Плагин расшифровывает файл в памяти перед запуском Helm
helm secrets upgrade --install my-app ./chart -f values.yaml -f secrets.enc.yaml
```

### 6. Пост-инсталляционное тестирование (Helm Test)

Позволяет убедиться, что приложение не просто "запустилось", но и корректно работает.

**Пример теста (templates/tests/test-api.yaml):**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "mychart.fullname" . }}-test"
  annotations:
    "helm.sh/hook": test
spec:
  containers:
    - name: wget
      image: busybox
      command: ['wget']
      args: ['{{ include "mychart.fullname" . }}:{{ .Values.service.port }}']
  restartPolicy: Never
```

**Запуск:**
```bash
helm test my-app -n prod
# → Pod test-connection-test-api started
# → Test Case test-connection-test-api status: Succeeded
```

---

## Дополнительная информация

### Сравнение Shared Chart и Library Chart

| Вариант | Shared Chart | Library Chart (`type: library`) |
|---------|--------------|---------------------------------|
| **Развертывание** | Может быть установлен напрямую (`helm install`) | **Не может** быть установлен самостоятельно |
| **Содержимое** | Полноценные шаблоны в `templates/` | Только `define`-блоки в `templates/` |
| **Когда использовать** | Деплой сотен идентичных сервисов | Переиспользование общей логики (labeling, annotations) в разных чартах |

### См. также

- [Зависимости и Library Charts](./helm_dependencies_and_library_charts.md)
- [Основные команды и рабочий процесс Helm](./helm_commands_and_workflow.md)
- [Скелетный паттерн (Skeleton Pattern)](./helm_skeleton_pattern.md)
- [Helmfile: декларативный оркестратор](./helmfile_overview.md)
