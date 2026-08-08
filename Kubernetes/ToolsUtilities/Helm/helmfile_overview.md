# Helmfile: декларативный оркестратор для Helm

Helmfile — это инструмент для декларативного управления множеством Helm-релизов. Он позволяет описать желаемое состояние всей инфраструктуры приложений в одном или нескольких YAML-файлах, обеспечивая повторяемость, автоматизацию и управление сложными зависимостями между чартами.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Helmfile** | Декларативный оркестратор, автоматизирующий выполнение команд Helm для группы чартов. |
| **State File (`helmfile.yaml`)** | Основной файл конфигурации, описывающий репозитории, релизы, параметры окружений и зависимости. |
| **Environment (Окружение)** | Именованный контекст (например, `production`, `staging`), позволяющий варьировать значения `values` для одних и тех же релизов. |
| **Selector (Селектор)** | Механизм фильтрации релизов по именам или меткам для выборочного применения изменений. |
| **Needs (Зависимости)** | Механизм, определяющий порядок развертывания релизов. Релиз будет установлен только после успешной готовности зависимых релизов. |
| **Templates (Шаблоны)** | Блоки конфигурации, которые можно переиспользовать в разных релизах для минимизации дублирования (DRY). |

---

## Базовые концепции

### Ключевые возможности

1.  **Декларативное управление:** Описание целевого состояния инфраструктуры. Helmfile сам вычисляет необходимые действия (install, upgrade, delete) для достижения этого состояния.
2.  **Многоуровневая шаблонизация:** Поддержка Go-шаблонов непосредственно в `helmfile.yaml`. Это позволяет использовать логику, функции (например, `readFile`, `env`, `exec`) и динамически формировать конфигурацию на основе переменных окружения.
3.  **Управление зависимостями (`needs`):** Позволяет выстраивать направленный ациклический граф (DAG) развертывания. Helmfile дождется готовности (readiness) ресурсов зависимого релиза, прежде чем приступать к следующему.
4.  **Модульность и переиспользование:**
    *   **`templates`**: Позволяют выносить общие настройки релизов в именованные блоки.
    *   **`bases` / `helmfiles`**: Механизмы разделения огромных конфигураций на логические части или вложенные файлы.
5.  **Интеграция с экосистемой:** Нативная поддержка плагинов `helm-diff` (для безопасного предпросмотра изменений) и `helm-secrets` (через SOPS/Vault).
6.  **Хуки (Hooks):** Возможность запуска команд на разных стадиях жизненного цикла (пре-деплой, пост-деплой, при ошибках).

### Командный интерфейс

| Команда | Описание |
|---------|----------|
| `helmfile repos` | Синхронизация репозиториев, описанных в конфигурации. |
| `helmfile diff` | Визуализация разницы между текущим состоянием кластера и конфигурацией (требуется `helm-diff`). |
| `helmfile apply` | Основная команда: выполняет `diff` и применяет только необходимые изменения. |
| `helmfile sync` | Принудительная переустановка всех релизов, даже если изменений нет. |
| `helmfile destroy` | Полное удаление ресурсов, описанных в текущем контексте/селекторе. |
| `helmfile lint` | Валидация синтаксиса шаблонов и проверка чартов. |

### Работа с окружениями и значениями

Helmfile поддерживает иерархическое наложение значений. Значения могут быть статическими файлами, шаблонами или результатом выполнения команд.

```yaml
environments:
  default:
    values:
      - domain: dev.example.com
  production:
    values:
      - domain: example.com
      - replicas: 5
```

---

## Практические сценарии

### Комплексный пример с зависимостями и шаблонами

Пример демонстрирует использование переиспользуемых шаблонов, управления порядком деплоя (`needs`) и секретов.

```yaml
# Использование шаблонов для DRY
templates:
  default-app:
    namespace: apps
    chart: ./charts/generic-app
    missingFileHandler: Warn
    values:
      - ./config/common.yaml
      - ./config/{{ .Environment.Name }}/values.yaml

environments:
  staging:
  production:

repositories:
  - name: prometheus-community
    url: https://prometheus-community.github.io/helm-charts

releases:
  # Инфраструктурный компонент
  - name: prometheus-operator
    namespace: monitoring
    chart: prometheus-community/kube-prometheus-stack
    version: 45.0.0

  # Приложение, зависящее от инфраструктуры
  - name: backend-api
    inherit:
      - template: default-app
    # Релиз начнется только после готовности prometheus-operator
    needs:
      - monitoring/prometheus-operator
    values:
      - image: my-registry/api:v1.2.3
    secrets:
      - secrets/{{ .Environment.Name }}/api-secrets.yaml

  # Условная установка (только для prod)
  - name: cleanup-job
    chart: ./charts/cleanup
    installed: {{ eq .Environment.Name "production" }}
```

### Использование хуков для автоматизации

Хуки позволяют интегрироваться с внешними системами (Slack, БД, CI).

```yaml
releases:
  - name: my-db
    chart: bitnami/postgresql
    hooks:
      - events: ["presync"]
        showlogs: true
        command: "./scripts/db-backup.sh"
      - events: ["postsync"]
        command: "curl"
        args: ["-X", "POST", "-H", "Content-Type: application/json", "--data", '{"text":"Database updated in {{ .Environment.Name }}"}', "https://hooks.slack.com/..."]
```

### Группировка и фильтрация (Selectors)

Селекторы позволяют управлять частями инфраструктуры, не затрагивая остальные.

```yaml
releases:
  - name: redis
    labels:
      tier: storage
      critical: "true"
  - name: web-ui
    labels:
      tier: frontend
```

Применение изменений только для критических хранилищ:
```bash
helmfile -l tier=storage -l critical=true apply
```

---

## Дополнительная информация

### Сравнение с Helmwave

*   **[Helmwave](./helmwave_overview.md):** Написан на Go, ориентирован на максимальную производительность. Предлагает полную шаблонизацию всего файла (а не только значений) и нативный DAG на базе `depends_on`.
*   **Helmfile:** Более зрелый инструмент с огромным сообществом. Имеет более богатый набор встроенных функций шаблонизатора и поддержку классических окружений.

### Интеграция с GitOps (Argo CD CMP)

В 2026 году стандартом является использование Helmfile внутри Argo CD через механизм **Config Management Plugins (CMP v2)**. Это позволяет Argo CD использовать логику Helmfile для генерации манифестов, сохраняя при этом преимущества контроля дрейфа конфигурации.

**Пример CMP конфигурации для Argo CD:**
```yaml
# sidecar контейнер в argocd-repo-server
- name: helmfile-cmp
  image: ghcr.io/helmfile/helmfile:v0.150.0
  command: [/var/run/argocd/argocd-cmp-server]
```

### Ссылки

*   [Обзор Helm](./helm_overview.md) — базовые знания о пакетном менеджере.
*   [Плагины Helm](./helm_plugins.md) — детали работы с `helm-diff` и `helm-secrets`.
*   [Структура Helm-чарта](./helm_chart_structure.md) — подготовка чарта.
*   [Официальная документация Helmfile](https://helmfile.readthedocs.io/) (англ.).

См. также:
*   [Argo CD: Custom Tooling](../../GitOps/ArgoCD/argocd_custom_tooling.md) — интеграция через CMP.
*   [Helmwave](./helmwave_overview.md) — альтернативный оркестратор.
