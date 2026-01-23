# kubeconform

## Определения

**`kubeconform`** — это высокопроизводительный валидатор для манифестов Kubernetes, который проверяет их на соответствие официальным схемам API.

## Основные понятия

### Ключевые особенности

*   **Высокая производительность:** Значительно превосходит аналоги, такие как `kubeval`, за счет параллельной обработки файлов и кэширования схем.
*   **Интеграция с CI/CD:** Легко встраивается в пайплайны, возвращая ненулевой код выхода при ошибках валидации.
*   **Поддержка CRD:** Валидирует Custom Resources при указании пути к их OpenAPI схемам.
*   **Офлайн-режим:** Способен работать без доступа к интернету при наличии предварительно загруженных схем.
*   **Гибкость:** Поддерживает валидацию файлов из локальных директорий, `stdin` или Helm-чартов.

### Установка

Установка `kubeconform` выполняется с помощью `go install`:

```bash
go install github.com/yannh/kubeconform/cmd/kubeconform@latest
```

## Практические сценарии

### Локальная валидация

*   **Проверка отдельных файлов:**
    ```bash
    kubeconform my-deployment.yaml another-file.yaml
    ```
*   **Рекурсивная проверка директории:**
    ```bash
    kubeconform -R .
    ```

### Интеграция в GitLab CI

Пример шага для `.gitlab-ci.yml`, проверяющего все манифесты в репозитории.

```yaml
validate-k8s-manifests:
  image: ghcr.io/yannh/kubeconform:v0.7.0
  stage: test
  script:
    - echo "Validating Kubernetes manifests..."
    - kubeconform -summary -output tap 'manifests/**/*.yaml'
```

*   `-summary`: Отображает краткий отчет о проверенных файлах.
*   `-output tap`: Форматирует вывод в Test Anything Protocol (TAP) для парсинга в CI-системах.

### Валидация Helm-чарта

Рендеринг шаблонов Helm-чарта и передача их напрямую в `kubeconform`:

```bash
helm template my-chart | kubeconform -
```

