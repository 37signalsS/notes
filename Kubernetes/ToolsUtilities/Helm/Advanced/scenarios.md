# Продвинутые сценарии Helm: OCI, мутации и адаптивные чарты

## Определения

**Продвинутые сценарии Helm** — это совокупность практических методик, направленных на решение задач промышленной эксплуатации Kubernetes: обеспечение безопасности цепочки поставок (Supply Chain Security), сложную мутацию сторонних чартов и создание универсальных шаблонов для гетерогенных кластеров (Multi-cloud/Edge).

---

## Основные концепции

### 1. Доверительная дистрибуция (OCI + Sigstore)
В 2026 году использование OCI-реестров является обязательным стандартом. Продвинутый подход включает не только хранение, но и **подпись артефактов** (чартов) с помощью Cosign, что гарантирует подлинность кода на этапе установки.

### 2. Декларативная мутация (Post-rendering)
Механизм `--post-renderer` позволяет использовать Helm как «генератор сырых данных», которые затем дорабатываются внешними инструментами (Kustomize, yq, scripts). Это критично для внедрения сквозных политик безопасности (Sidecar-инъекции, специфические аннотации) в чарты, исходный код которых недоступен для модификации.

### 3. Изолированная расширяемость (WASM Plugins)
Helm v4 внедряет стандарт **WASM-плагинов**. В отличие от бинарных плагинов v3, они безопасны (Sandboxed), кроссплатформенны и могут распространяться через те же OCI-реестры, что и чарты.

### 4. Адаптивность на уровне движка (Capabilities)
Создание «умных» чартов, которые самостоятельно определяют возможности целевого кластера (версию API, наличие Ingress-контроллера, поддержку определенных CRD) и адаптируют состав манифестов без изменения `values.yaml`.

---

## Практические сценарии

### 1. Безопасная дистрибуция в OCI с подписью (Cosign)

Сценарий обеспечивает защиту от подмены чарта в реестре.

**Шаг 1: Упаковка и публикация**
```bash
helm package ./my-chart
helm push my-chart-1.2.3.tgz oci://registry.example.com/charts
```

**Шаг 2: Подпись артефакта через Cosign**
```bash
# Подпись образа чарта в реестре
cosign sign --key cosign.key registry.example.com/charts/my-chart:1.2.3
```

**Шаг 3: Проверка при установке**
В CI/CD пайплайне или через Admission Controller (Kyverno/OPA) выполняется верификация перед деплоем:
```bash
cosign verify --key cosign.pub registry.example.com/charts/my-chart:1.2.3
helm install my-app oci://registry.example.com/charts/my-chart --version 1.2.3
```

### 2. Глубокая мутация через Post-rendering (Kustomize)

Используется для наложения патчей на "закрытые" чарты (например, из публичных репозиториев), которые не поддерживают нужные параметры.

**Пример: Инъекция Sidecar-контейнера безопасности**

1.  **Создание `kustomization.yaml`**:
    ```yaml
    resources:
      - all.yaml # Сюда Helm направит отрендеренные манифесты
    patches:
      - target:
          kind: Deployment
        patch: |-
          - op: add
            path: /spec/template/spec/containers/-
            value:
              name: security-proxy
              image: security-proxy:latest
    ```

2.  **Скрипт-обертка (`patcher.sh`)**:
    ```bash
    #!/bin/bash
    cat <&0 > all.yaml # Читаем stdin от Helm
    kustomize build .
    rm all.yaml
    ```

3.  **Запуск**:
    ```bash
    helm upgrade --install web oci://registry.com/web-chart --post-renderer ./patcher.sh
    ```

### 3. Создание универсальных адаптивных чартов

Сценарий для компаний с множеством кластеров разных версий (например, миграция с 1.25 на 1.30+).

**Динамический выбор API для Ingress и PDB:**
```yaml
{{- /* Проверка Ingress */ -}}
{{- $ingressApi := "networking.k8s.io/v1" -}}
{{- if not (.Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress") -}}
  {{- $ingressApi = "networking.k8s.io/v1beta1" -}}
{{- end -}}

{{- /* Проверка наличия Istio в кластере */ -}}
{{- $hasIstio := .Capabilities.APIVersions.Has "networking.istio.io/v1beta1/VirtualService" -}}

apiVersion: {{ $ingressApi }}
kind: Ingress
metadata:
  annotations:
    {{- if $hasIstio }}
    kubernetes.io/ingress.class: istio
    {{- end }}
...
```

### 4. Работа с WASM-плагинами (Helm v4)

В v4 плагины становятся частью OCI-экосистемы.

```bash
# Установка плагина для валидации политик из реестра
helm plugin install oci://registry.example.com/plugins/policy-checker:v1.0.0

# Использование плагина в процессе деплоя
helm upgrade --install my-app ./chart --verify-policies
```

---

## Дополнительная информация

- **[Обзор Helm](../helm_overview.md)** — архитектура v4, SSA и работа с реестрами.
- **[Зависимости и библиотечные чарты](../helm_dependencies_and_library_charts.md)** — механизмы композиции и Blueprint-паттерн.
- **[Проверка версий API и возможностей](../templating/scenarios/api_versions.md)** — детальный справочник по `.Capabilities`.
- **[Безопасность Helm](./security_best_practices.md)** — работа с секретами (SOPS) и RBAC.
- **[Sigstore/Cosign](../../Security/Tools/sigstore.md)** — подробное руководство по подписи артефактов.
