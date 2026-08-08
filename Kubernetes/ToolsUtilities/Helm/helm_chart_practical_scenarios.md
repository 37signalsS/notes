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

---

## Основные концепции

### Жизненный цикл разработки и валидация

Процесс создания промышленного чарта включает многоуровневую проверку:
1.  **Линтинг:** `helm lint` — проверка структуры и синтаксиса `Chart.yaml`.
2.  **Локальный рендеринг:** `helm template` — генерация YAML без кластера для отладки логики.
3.  **Server-side Dry-run:** (v4) `helm install --dry-run --debug` — проверка на стороне API-сервера (права, схемы, квоты) без применения изменений.

### Управление состоянием и конфликтами в v4

Использование SSA позволяет Helm корректно сосуществовать с внешними контроллерами (Sidecar-инжекторы, HPA, Mesh-прокси).
- **Разрешение конфликтов:** Если поле управляется другим контроллером, Helm v4 не затирает его, если не указан флаг `--force-conflicts`.
- **Проверка готовности:** Helm v4 использует библиотеку `kstatus` для унифицированного ожидания готовности ресурсов (`--wait`).

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

Использование слоев конфигурации позволяет избежать дублирования шаблонов.

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

### 3. Паттерн «Зонтичный чарт» (Umbrella Chart)

Идеален для развёртывания инфраструктурных стеков (например, LGTM или мониторинг) как единого релиза.

**monitoring-stack/Chart.yaml:**
```yaml
apiVersion: v2
name: monitoring-stack
version: 1.0.0
dependencies:
  - name: prometheus
    version: "25.x.x"
    repository: "oci://registry.example.com/charts"
  - name: grafana
    version: "7.x.x"
    repository: "oci://registry.example.com/charts"
```

### 4. Масштабирование через Общий чарт (Shared Chart)

Для 100+ микросервисов создаётся один универсальный чарт-движок в OCI-реестре.

**Структура репозитория конфигураций:**
```
infra-gitops/
├── engine/ (Shared Chart)
└── apps/
    ├── auth-svc/values.yaml   # Только параметры для auth
    └── api-gateway/values.yaml
```

**Оркестрация через ArgoCD ApplicationSet:**
Автоматизирует создание сотен приложений на базе одного чарта.
```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
spec:
  generators:
    - git:
        repoURL: https://github.com/org/infra-gitops.git
        directories: [{path: "apps/*"}]
  template:
    spec:
      source:
        repoURL: https://github.com/org/infra-gitops.git
        path: engine
        helm:
          valueFiles: ["../../apps/{{ path.basename }}/values.yaml"]
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{ path.basename }}'
```

### 5. Безопасное управление секретами (Helm Secrets + SOPS)

Шифрование чувствительных данных (пароли, ключи) с использованием KMS (AWS/GCP/Azure) или PGP.

**Рабочий процесс:**
1.  Шифрование: `sops -e secrets.yaml > secrets.enc.yaml`.
2.  Развёртывание:
```bash
# Плагин расшифровывает значения в памяти перед рендерингом
helm secrets upgrade --install my-app ./chart -f values.yaml -f secrets.enc.yaml
```

### 6. Проверка работоспособности (Helm Test)

Автоматизированная верификация релиза после деплоя. См. детально: [Хуки и тестирование](./helm_hooks_and_tests.md).

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

---

## Дополнительная информация

### Сравнение подходов к масштабированию

| Параметр | Shared Chart | Library Chart | Umbrella Chart |
| :--- | :--- | :--- | :--- |
| **Назначение** | Единый шаблон для всех | Общая логика в `_helpers` | Агрегация независимых чартов |
| **Развёртывание** | Напрямую (`helm install`) | Только как зависимость | Как единый релиз |
| **Масштабируемость** | Высокая (ArgoCD) | Средняя | Низкая (сложно делить values) |

### См. также

- [Зависимости и Library Charts](./helm_dependencies_and_library_charts.md) — детали работы с `type: library`.
- [Основные команды и рабочий процесс Helm](./helm_commands_and_workflow.md) — SSA, OCI и жизненный цикл.
- [Скелетный паттерн (Skeleton Pattern)](./helm_skeleton_pattern.md) — альтернатива Shared Chart.
- [Паттерны и устранение неисправностей](./Advanced/patterns_troubleshooting.md) — решение проблем с SSA и лимитами.
