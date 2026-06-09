# Установка GitLab в Kubernetes через Helm

Руководство по развертыванию GitLab в кластере Kubernetes при помощи официального Helm-чарта.

> **Контекст:** Официальный чарт GitLab — полноценное решение для production-развертывания. Включает Ingress, cert-manager, Prometheus, Redis и другие зависимости. См. [Обзор Helm](../ToolsUtilities/Helm/helm_overview.md), [Структура Helm-чарта](../ToolsUtilities/Helm/helm_chart_structure.md).

---

## Определения

| Термин | Описание |
|--------|----------|
| **GitLab Helm Chart** | Официальный Helm-чарт для развертывания GitLab в Kubernetes. Включает компоненты: GitLab Rails, Sidekiq, Gitaly, PostgreSQL, Redis, Ingress, cert-manager |
| **Таймаут установки** | Максимальное время ожидания завершения установки. Рекомендуется 600s (10 минут) из-за сложности платформы |
| **StorageClass** | Объект для динамического выделения PersistentVolume. Требуется для хранения данных (репозитории, БД, кэш) |
| **Values-файл** | YAML-файл для переопределения параметров чарта при установке |

---

## Основные концепции

### Архитектура официального чарта

Официальный чарт GitLab (`gitlab/gitlab`) включает следующие ключевые сервисы:

- **GitLab Rails** — основной веб-интерфейс и API.
- **Sidekiq** — обработка фоновых задач.
- **Gitaly** — управление Git-репозиториями.
- **PostgreSQL / Redis** — база данных и кэш.
- **cert-manager** — автоматизация SSL/TLS (опционально).

### Предварительные требования

| Компонент | Требование | Примечание |
|-----------|------------|------------|
| **Kubernetes** | >= 1.24 | Рекомендуется 1.26+ |
| **Helm** | >= 3.9.4 | См. [Обзор Helm](../ToolsUtilities/Helm/helm_overview.md#установка-cli) |
| **StorageClass** | Обязателен | NFS, Ceph или облачные PV |
| **CPU / RAM** | 4 ядра / 8 ГБ | Минимально для тестового запуска |

### Ключевые параметры values.yaml

| Параметр | Описание | Пример значения |
|----------|----------|-----------------|
| `global.hosts.domain` | Основной домен GitLab | `example.com` |
| `global.hosts.gitlab.name` | Полный хостнейм | `gitlab.example.com` |
| `certmanager.install` | Установка cert-manager | `true` / `false` |
| `nginx-ingress.enabled` | Встроенный Ingress | `true` / `false` |

---

## Практические сценарии

### Добавление репозитория GitLab

```bash
# Добавление официального репозитория
helm repo add gitlab https://charts.gitlab.com/

# Обновление локального кэша чартов
helm repo update
```

### Подготовка и изучение чарта

Перед установкой рекомендуется загрузить чарт для анализа параметров:

```bash
# Скачивание и распаковка чарта
helm pull gitlab/gitlab --untar

# Просмотр структуры и параметров по умолчанию
cd gitlab
ls -la
cat values.yaml
```

### Базовая установка

```bash
# Создание выделенного пространства имен
kubectl create namespace gitlab

# Установка платформы
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 600s \
  --set global.hosts.domain=example.com \
  --set global.hosts.gitlab.name=gitlab.example.com
```

### Установка с внешним cert-manager

Если управление сертификатами осуществляется внешним компонентом:

```bash
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 600s \
  --set global.hosts.domain=example.com \
  --set certmanager.install=false \
  --set certmanager-issuer.email=admin@example.com
```

### Проверка состояния развертывания

```bash
# Список всех ресурсов в namespace
kubectl get all -n gitlab

# Проверка статуса подов и хранилищ
kubectl get pods,pvc -n gitlab
```

### Получение начального пароля root

Начальный пароль генерируется автоматически и хранится в секрете:

```bash
# Извлечение пароля из секрета
kubectl get secret -n gitlab gitlab-initial-root-password \
  -o jsonpath='{.data.password}' | base64 -d
```

> **Важно:** Используйте логин `root`. После первого входа система потребует сменить пароль.

---

## Дополнительная информация

### Конфигурация для Production

Типичный файл `production-values.yaml`:

```yaml
global:
  hosts:
    domain: example.com
    https: true
    gitlab:
      name: gitlab.example.com
  registry:
    enabled: false # При использовании внешнего Harbor
  ingress:
    configureCertmanager: true
    tls:
      enabled: true

certmanager:
  install: true

gitlab-runner:
  install: false # Рекомендуется устанавливать отдельно
```

### Ограничения и рекомендации

| Аспект | Рекомендация |
|--------|--------------|
| **Хранилище** | Всегда проверяйте доступность StorageClass. См. [Решение проблем с PVC](./gitlab_installation_troubleshooting.md) |
| **Доступ** | Для bare-metal используйте MetalLB или NodePort. См. [Методы доступа](./gitlab_kubernetes_access.md) |
| **Runner** | Устанавливайте Runner как отдельный релиз. См. [Установка GitLab Runner](./gitlab_runner_kubernetes_installation.md) |

### См. также

- [Архитектура GitLab](../../CI-CD/GitLab_CI/Concepts/gitlab_platform_architecture.md)
- [Решение проблем при установке](./gitlab_installation_troubleshooting.md)
- [Методы доступа к GitLab](./gitlab_kubernetes_access.md)
- [Установка GitLab Runner](./gitlab_runner_kubernetes_installation.md)
- [Установка в закрытом контуре](./gitlab_offline_kubernetes_installation.md)
- [Интеграция с Harbor](./k3s_dev_environment/gitlab_harbor_integration.md)
