# Helmfile: декларативный оркестратор для Helm

Helmfile — это инструмент для декларативного управления множеством Helm-релизов. Он позволяет описать желаемое состояние всей инфраструктуры приложений в одном или нескольких YAML-файлах, обеспечивая повторяемость и автоматизацию развёртывания.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Helmfile** | Декларативный оркестратор, автоматизирующий выполнение команд Helm для группы чартов |
| **State File (`helmfile.yaml`)** | Основной файл конфигурации, описывающий репозитории, релизы и параметры окружений |
| **Environment (Окружение)** | Именованный контекст (например, `production`, `staging`), позволяющий варьировать значения `values` для одних и тех же релизов |
| **Selector (Селектор)** | Механизм фильтрации релизов по именам или меткам для выборочного применения изменений |

---

## Основные концепции

### Ключевые возможности

1.  **Декларативность:** Описание "что" должно быть развёрнуто, а не "как". Helmfile сам определяет последовательность действий.
2.  **Многоуровневая шаблонизация:** Поддержка Go-шаблонов непосредственно в `helmfile.yaml`, что позволяет использовать логику, функции (например, `readFile`, `env`) и переменные окружения.
3.  **Управление окружениями:** Нативная поддержка разделения конфигураций между dev/stage/prod через блок `environments`.
4.  **Интеграция с плагинами:** Плодотворная работа с `helm-diff` (для предпросмотра изменений) и `helm-secrets` (для шифрования секретов через SOPS).
5.  **Хуки (Hooks):** Возможность запуска произвольных команд или скриптов до и после выполнения операций Helm.
6.  **Модульность:** Разделение больших конфигураций на части с использованием `bases`.

### Командный интерфейс

| Команда | Описание |
|---------|----------|
| `helmfile repos` | Добавление и обновление Helm-репозиториев, описанных в файле |
| `helmfile diff` | Сравнение текущего состояния кластера с желаемым (требуется плагин `helm-diff`) |
| `helmfile apply` | Синхронизация состояния: устанавливает, обновляет или удаляет релизы согласно конфигурации |
| `helmfile destroy` | Полное удаление всех ресурсов, описанных в текущем контексте |
| `helmfile lint` | Проверка синтаксиса шаблонов и чартов |

### Работа с окружениями

Helmfile позволяет определить переменные для разных окружений в блоке `environments`. При запуске команды указывается флаг `-e <name>`.

```yaml
environments:
  default:
    values:
      - domain: dev.example.com
  production:
    values:
      - domain: example.com
```

---

## Практические сценарии

### Комплексный пример helmfile.yaml

Пример демонстрирует использование окружений, секретов и глобальных настроек.

```yaml
# Глобальные настройки для всех релизов
helmDefaults:
  atomic: true
  wait: true
  timeout: 600

environments:
  staging:
  production:

repositories:
  - name: ingress-nginx
    url: https://kubernetes.github.io/ingress-nginx

releases:
  - name: nginx-ingress
    namespace: ingress-basic
    chart: ingress-nginx/ingress-nginx
    version: 4.7.0
    # Использование значений, специфичных для окружения
    values:
      - controller:
          service:
            annotations:
              external-dns.alpha.kubernetes.io/hostname: {{ .Values.domain }}
    # Подключение секретов (требуется helm-secrets)
    secrets:
      - secrets/{{ .Environment.Name }}/ingress-certs.yaml

  - name: my-app
    namespace: default
    chart: ./charts/my-app
    # Условная установка: только в production
    installed: {{ eq .Environment.Name "production" }}
    values:
      - ./config/{{ .Environment.Name }}/values.yaml
```

### Использование хуков (Hooks)

Хуки позволяют автоматизировать задачи, такие как уведомления в Slack или резервное копирование БД перед обновлением.

```yaml
releases:
  - name: database
    chart: bitnami/postgresql
    hooks:
      - events: ["presync"]
        showlogs: true
        command: "/bin/sh"
        args: ["-c", "echo 'Starting backup before sync...'"]
      - events: ["postsync"]
        command: "curl"
        args: ["-X", "POST", "-d", "text=DB updated", "https://hooks.slack.com/services/..."]
```

### Разделение конфигурации через Bases

Для упрощения поддержки больших проектов используется механизм `bases`.

```yaml
# helmfile.yaml
bases:
  - bases/repositories.yaml
  - bases/environments.yaml

releases:
  - name: prometheus
    chart: prometheus-community/kube-prometheus-stack
```

### Фильтрация через селекторы

Селекторы (метки) позволяют группировать релизы и управлять ими по отдельности.

```yaml
releases:
  - name: redis
    labels:
      tier: backend
  - name: frontend-app
    labels:
      tier: frontend
```

Применение изменений только для backend-компонентов:
```bash
helmfile -l tier=backend apply
```

---

## Дополнительная информация

### Сравнение с альтернативами

*   **[Helmwave](./helmwave_overview.md):** Написан на Go, предлагает более глубокую шаблонизацию всего файла конфигурации и улучшенную работу с зависимостями.
*   **Argo CD / Flux:** Инструменты GitOps, которые могут использовать Helmfile (через плагины) или работать с чартами напрямую. Helmfile чаще используется в CI/CD пайплайнах для push-модели деплоя.

### Ссылки

*   [Обзор Helm](./helm_overview.md) — базовые знания о пакетном менеджере.
*   [Плагины Helm](./helm_plugins.md) — детальное описание `helm-diff` и `helm-secrets`.
*   [Структура Helm-чарта](./helm_chart_structure.md) — как подготовить чарт для использования в Helmfile.
*   [Официальный репозиторий Helmfile](https://github.com/helmfile/helmfile) (англ.).
