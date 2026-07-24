# Сценарии Helm: OCI-реестры, пост-рендеринг и адаптивные шаблоны

## Определения

**Сценарии Helm** — практические методики применения Helm для решения сложных инфраструктурных задач, включая управление артефактами в OCI-реестрах, гибридную конфигурацию с внешними инструментами и построение динамических систем шаблонизации.

---

## Основные концепции

### Эволюция подходов (Helm v4+)

1.  **OCI-First**: Переход от статических HTTP-индексов (`index.yaml`) к реестрам артефактов (OCI), обеспечивающим безопасность, версионирование и единое хранилище с образами контейнеров.
2.  **Декларативная мутация (Post-rendering)**: Использование Helm как базового генератора с последующей коррекцией манифестов через специализированные инструменты без изменения исходного кода чарта.
3.  **Модульность через библиотеки**: Вынос общей логики в `library`-чарты для обеспечения консистентности сотен микросервисов.

---

## Практические сценарии

### 1. Работа с OCI (Open Container Initiative) реестрами

В современных средах OCI-реестр является основным способом дистрибуции. Helm v4 оптимизирован для работы с реестрами (Harbor, ECR, Artifact Registry) без использования промежуточных плагинов.

**Публикация чарта:**

```bash
# 1. Авторизация (только домен)
helm registry login registry.example.com -u robot-user

# 2. Упаковка и пуш
helm package ./my-chart
helm push my-chart-1.2.3.tgz oci://registry.example.com/charts
```

**Установка по дигесту (Immutable Infrastructure):**
Использование дигеста (хеша) гарантирует, что в кластер будет установлена именно та версия чарта, которая прошла аутентификацию, исключая риски подмены тега.

```bash
helm install my-release oci://registry.example.com/charts/my-chart@sha256:7f... --atomic
```

### 2. Гибридное использование через Пост-рендеринг

Если Helm-чарт не поддерживает нужный параметр (например, специфическую аннотацию безопасности), используйте `--post-renderer` для наложения патчей Kustomize на лету.

**Алгоритм:**

1.  **Создайте kustomization.yaml** в директории `scripts/`:
    ```yaml
    resources:
      - all.yaml # Временный файл, генерируемый Helm
    patches:
      - target: { kind: Deployment }
        patch: |-
          - op: add
            path: /metadata/annotations/security
            value: strictly-enforced
    ```

2.  **Скрипт-обертка (`scripts/kustomize.sh`):**
    ```bash
    #!/bin/bash
    cat <&0 > scripts/all.yaml
    kustomize build scripts/
    ```

3.  **Запуск Helm:**
    ```bash
    helm upgrade --install my-app ./my-chart --post-renderer ./scripts/kustomize.sh
    ```

### 3. Использование библиотечных чартов (Library Charts)

Для исключения дублирования `_helpers.tpl` создайте общий чарт с типом `library`.

**В библиотечном чарте (`common-lib/Chart.yaml`):**
```yaml
apiVersion: v2
name: common-lib
type: library
version: 1.0.0
```

**В целевом чарте (`app-chart/Chart.yaml`):**
```yaml
dependencies:
  - name: common-lib
    version: 1.0.0
    repository: "oci://registry.example.com/charts"
```

**Использование шаблона:**
```yaml
metadata:
  labels:
    {{- include "common-lib.standardLabels" . | nindent 4 }}
```

### 4. Адаптивные шаблоны и проверка API

Для создания универсальных чартов используйте проверки доступности ресурсов в кластере.

**Пример выбора API-версии Ingress:**
```yaml
{{- $apiVersion := "networking.k8s.io/v1" -}}
{{- if not (.Capabilities.APIVersions.Has "networking.k8s.io/v1") -}}
  {{- $apiVersion = "networking.k8s.io/v1beta1" -}}
{{- end -}}
apiVersion: {{ $apiVersion }}
kind: Ingress
```

**Проверка версии Kubernetes:**
```yaml
{{- if semverCompare ">=1.24-0" .Capabilities.KubeVersion.GitVersion -}}
# Логика для новых версий K8s (например, изменение полей Service)
{{- end -}}
```

---

## Дополнительная информация

- **[Обзор Helm](../helm_overview.md)** — архитектура v4, SSA и работа с OCI.
- **[Зависимости и библиотеки](../helm_dependencies_and_library_charts.md)** — детальный разбор типов чартов.
- **[Сравнение версий](../helm_v2_vs_v3.md)** — изменения в стратегиях слияния (Three-way merge vs SSA).
- **[Шаблонизация в Helm](../helm_templating.md)** — полный список функций (semverCompare, include и др.).
