# Установка GitLab в Kubernetes через Helm

Руководство по развертыванию, настройке и поддержке платформы GitLab в кластере Kubernetes при помощи официального Helm-чарта.

> **Контекст:** Официальный чарт GitLab — полноценное решение для production-развертывания. Включает Ingress, cert-manager, Prometheus, Redis и другие зависимости. См. [Обзор Helm](../ToolsUtilities/Helm/helm_overview.md), [Структура Helm-чарта](../ToolsUtilities/Helm/helm_chart_structure.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **GitLab Helm Chart** | Официальный пакет шаблонов (`umbrella chart`) для развертывания всех компонентов GitLab (Rails, Sidekiq, Gitaly и др.). |
| **Subchart (Субчарт)** | Вложенный чарт для зависимостей (PostgreSQL, Redis, MinIO). Параметры субчартов настраиваются через корневой `values.yaml`. |
| **Global Scope** | Секция `global` в `values.yaml`, значения из которой используются всеми компонентами платформы (домен, настройки хранилища, SSL). |
| **Gitaly** | Сервис уровня хранения (Stateful), обеспечивающий доступ к Git-репозиториям по протоколу gRPC. |
| **Таймаут установки** | Максимальное время ожидания завершения установки (рекомендуется 600s+ из-за сложности платформы). |
| **StorageClass** | Объект для динамического выделения PersistentVolume. Требуется для хранения репозиториев, БД и кэша. |
| **KAS (Kubernetes Agent Server)** | Компонент GitLab для интеграции с кластерами через GitLab Agent. |

---

## Основные концепции

### Архитектура официального чарта

Официальный чарт (`gitlab/gitlab`) включает следующие ключевые сервисы:
- **GitLab Rails (Puma)** — основной веб-интерфейс и API.
- **Sidekiq** — обработка фоновых задач.
- **Gitaly** — управление Git-репозиториями (требует быстрых дисков).
- **PostgreSQL / Redis** — база данных и кэш (встроены как субчарты).
- **cert-manager** — автоматизация SSL/TLS через Let's Encrypt.

### Предварительные требования

| Компонент | Требование | Примечание |
| :--- | :--- | :--- |
| **Kubernetes** | >= 1.24 | Рекомендуется 1.26+ для поддержки современных API. |
| **Helm** | >= 3.9.4 | См. [Обзор Helm](../ToolsUtilities/Helm/helm_overview.md#установка-cli). |
| **StorageClass** | Обязателен | Поддержка динамического провижининга (NFS, Ceph, Cloud PV). |
| **CPU / RAM** | 4 ядра / 8 ГБ | Минимально для тестового запуска. Для Production: 8+ ядер / 32+ ГБ. |

### Ключевые параметры values.yaml

| Параметр | Описание | Пример значения |
| :--- | :--- | :--- |
| `global.hosts.domain` | Основной домен GitLab | `example.com` |
| `global.hosts.gitlab.name` | Полный хостнейм для UI | `gitlab.example.com` |
| `certmanager.install` | Установка встроенного cert-manager | `true` / `false` |
| `nginx-ingress.enabled` | Включение встроенного Ingress-контроллера | `true` / `false` |
| `postgresql.install` | Использование встроенной БД PostgreSQL | `false` для внешней RDS/БД. |

---

## Практические сценарии

### 1. Подготовка и изучение чарта

Перед установкой необходимо добавить репозиторий и рекомендуется изучить параметры по умолчанию:

```bash
# Добавление официального репозитория
helm repo add gitlab https://charts.gitlab.com/
helm repo update

# Скачивание и распаковка чарта для анализа
helm pull gitlab/gitlab --untar
cd gitlab
ls -la values.yaml
```

### 2. Базовая установка

```bash
# Создание выделенного пространства имен
kubectl create namespace gitlab

# Установка платформы с базовыми параметрами
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 600s \
  --set global.hosts.domain=example.com \
  --set global.hosts.gitlab.name=gitlab.example.com \
  --set certmanager-issuer.email=admin@example.com
```

### 3. Установка с внешним cert-manager и БД

Для production рекомендуется использовать внешние сервисы для стабильности.

**Пример values.yaml для интеграции с внешней БД:**

```yaml
global:
  hosts:
    domain: example.com
  psql:
    host: postgres.internal.db
    password:
      secret: gitlab-db-password
      key: password
certmanager:
  install: false # Использование существующего в кластере контроллера
postgresql:
  install: false # Отключение встроенного субчарта
```

### 4. Проверка состояния и получение пароля

```bash
# Список всех ресурсов и проверка статуса PVC
kubectl get all,pvc -n gitlab

# Получение начального пароля root (автоматически генерируется)
kubectl get secret -n gitlab gitlab-initial-root-password \
  -o jsonpath='{.data.password}' | base64 -d
```

### 5. Обновление GitLab

GitLab поддерживает обновления только по [путям обновления (Upgrade Paths)](https://docs.gitlab.com/ee/update/index.html#upgrade-paths). Никогда не перескакивайте через мажорные версии без промежуточных обновлений.

```bash
# Обновление до целевой версии
helm upgrade gitlab gitlab/gitlab \
  --namespace gitlab \
  -f custom-values.yaml \
  --version <version_tag>
```

### 6. Резервное копирование (Backup)

В Kubernetes бэкап метаданных выполняется через специальную задачу:

```bash
# Запуск Job для создания бэкапа в объектное хранилище
kubectl exec -it <webservice-pod> -n gitlab -- backup-utility
```

---

## Дополнительная информация

### Конфигурация для Production

Типичный файл `production-values.yaml`:

```yaml
global:
  hosts:
    domain: example.com
    https: true
  registry:
    enabled: false # При использовании внешнего Harbor
  ingress:
    configureCertmanager: true
    tls:
      enabled: true
gitlab-runner:
  install: false # Рекомендуется устанавливать отдельно
```

### Ограничения и рекомендации

| Аспект | Рекомендация |
| :--- | :--- |
| **Хранилище** | Всегда проверяйте доступность StorageClass. См. [Решение проблем с PVC](./gitlab_installation_troubleshooting.md). |
| **Доступ** | Для bare-metal используйте MetalLB или NodePort. См. [Методы доступа](./gitlab_kubernetes_access.md). |
| **Обновления** | Всегда делайте бэкап БД перед `helm upgrade`. |

### См. также

- [Архитектура GitLab](../../CI-CD/GitLab_CI/Concepts/gitlab_platform_architecture.md)
- [Решение проблем при установке](./gitlab_installation_troubleshooting.md)
- [Методы доступа к GitLab](./gitlab_kubernetes_access.md)
- [Установка GitLab Runner](./gitlab_runner_kubernetes_installation.md)
- [Установка в закрытом контуре](./gitlab_offline_kubernetes_installation.md)
- [Интеграция с Harbor](./k3s_dev_environment/gitlab_harbor_integration.md)
