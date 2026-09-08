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
| **Gitaly** | Сервис уровня хранения (Stateful), обеспечивающий доступ к Git-репозиториям по протоколу gRPC. Требует быстрых дисков (SSD/NVMe) для операций с Git. |
| **Таймаут установки** | Максимальное время ожидания завершения установки (рекомендуется 600s+ из-за сложности платформы и последовательного запуска компонентов). |
| **StorageClass** | Объект для динамического выделения PersistentVolume. Требуется для хранения репозиториев, БД и кэша. Без корректного StorageClass поды останутся в `Pending`. |
| **KAS (Kubernetes Agent Server)** | Компонент GitLab для интеграции с кластерами через GitLab Agent. Обеспечивает защищённый gRPC-туннель для CI/CD. |
| **helm upgrade --install** | Идемпотентная команда: устанавливает релиз, если его нет, или обновляет существующий. Является «золотым стандартом» для CI/CD, безопаснее `helm install` (не требует удаления перед повторным запуском). |
| **--atomic** | Флаг `helm upgrade`, откатывающий релиз при ошибке установки. Гарантирует, что кластер не останется в промежуточном состоянии. Рекомендуется для production. |
| **--wait** | Флаг `helm upgrade`, заставляющий Helm ожидать готовности всех ресурсов (Pods, PVC, Services) перед завершением команды. Без него команда вернётся сразу после отправки манифестов в API. |
| **helm template** | Команда для рендеринга шаблонов чарта в YAML-манифесты без применения в кластер. Используется для проверки генерируемых ресурсов, передачи в `kubectl apply`, CI/CD-пайплайны и GitOps. |
| **helm diff** | Плагин Helm, показывающий差异 между текущим состоянием релиза и предстоящими изменениями. Обязателен перед `helm upgrade` в production для предотвращения нежелательных изменений. |
| **Shared Secrets** | Набор ключей и паролей (rails-secret, gitaly-token, otp_key_base и др.), которые должны быть идентичны во всех компонентах GitLab для корректного взаимодействия. Генерируются автоматически при первой установке и хранятся в Secrets Kubernetes. |
| **Database Migrations Job** | Kubernetes Job (`gitlab-migrations`), выполняющий миграции схемы базы данных перед запуском основных сервисов. Если завершается с ошибкой, webservice и sidekiq не перейдут в `Ready`. |
| **PodDisruptionBudget (PDB)** | Объект Kubernetes, ограничивающий количество одновременно недоступных подов при добровольных нарушениях (drain узла, обновление). Критичен для GitLab — обеспечивает доступность Webservice и Sidekiq при обслуживании кластера. |
| **ResourceQuota** | Объект Kubernetes, ограничивающий суммарные ресурсы (CPU, RAM, количество подов) в namespace. Предотвращает исчерпание ресурсов кластера компонентами GitLab. |
| **LimitRange** | Объект Kubernetes, задающий дефолтные `requests` и `limits` для подов в namespace. Упрощает конфигурацию ресурсов для компонентов GitLab. |

---

## Основные концепции

### Архитектура официального чарта

Официальный чарт (`gitlab/gitlab`) — umbrella chart, объединяющий множество субчартов. Каждый компонент развертывается как отдельный Deployment или StatefulSet со своей Service, PVC и настройками ресурсов.

**Ключевые сервисы:**

| Компонент | Тип | Назначение | Примечания |
| :--- | :--- | :--- | :--- |
| **GitLab Webservice (Puma)** | Deployment | Основной веб-интерфейс и REST API | Горизонтальное масштабирование через replicas |
| **Sidekiq** | Deployment | Обработка фоновых задач (email, CI/CD, webhook) | Требует доступа к Redis и PostgreSQL |
| **Gitaly** | StatefulSet | Управление Git-репозиториями (gRPC) | Требует быстрых дисков (SSD/NVMe), хранит данные в PVC |
| **GitLab Shell** | Deployment | SSH-доступ к Git-репозиториям | Работает совместно с Gitaly |
| **KAS (Kubernetes Agent Server)** | Deployment | Интеграция с кластерами через GitLab Agent | Защищённый gRPC-туннель |
| **Registry** | Deployment | Хранение Docker-образов | Может быть отключен при использовании внешнего реестра |
| **Webservice (Workhorse)** | Deployment | Reverse proxy, маршрутизация, кэширование | Сидит перед Puma, обрабатывает статику |
| **PostgreSQL** | StatefulSet (субчарт) | Основная БД | Встроенный или внешний |
| **Redis** | StatefulSet (субчарт) | Кэш и очередь задач | Встроенный или внешний |
| **MinIO** | StatefulSet (субчарт) | Объектное хранилище (S3-совместимое) | LFS, артефакты, backup. Может быть заменён на внешний S3 |
| **cert-manager** | Deployment (субчарт) | Автоматизация SSL/TLS | Выпуск сертификатов Let's Encrypt или внутреннего CA |
| **nginx-ingress** | Deployment (субчарт) | Ingress-контроллер | Маршрутизация HTTP/HTTPS трафика |
| **Prometheus** | StatefulSet (субчарт) | Сбор метрик | Мониторинг всех компонентов GitLab |

### Цепочка зависимостей при запуске

Компоненты GitLab должны запускаться в строго определённом порядке. Нарушение последовательности приводит к ошибкам и CrashLoopBackOff.

**Порядок старта:**
```text
1. StorageClass / PVC (Gitaly, PostgreSQL, Redis, MinIO)
2. PostgreSQL и Redis (базы данных)
3. MinIO (объектное хранилище)
4. gitlab-migrations (Job миграций БД) — КРИТИЧЕСКИЙ БЛОКЕР
5. Gitaly (Git-сервис)
6. GitLab Webservice (Puma + Workhorse)
7. Sidekiq (фоновые задачи)
8. KAS, Registry, Pages (зависимые сервисы)
```

Если `gitlab-migrations` не завершится успешно, основные поды приложения не перейдут в состояние `Ready`. Это типичная причина зависания установки.

### Жизненный цикл Helm-релиза

```text
helm upgrade --install (создание/обновление)
    │
    ├── Рендеринг шаблонов (values.yaml + чарт)
    ├── Проверкаdiff (если установлен helm-diff)
    ├── Отправка манифестов в Kubernetes API
    ├── Ожидание готовности (флаг --wait)
    ├── Проверка health-check'ов подов
    │
    ├── УСПЕХ → релиз обновлён
    └── НЕУДАЧА (--atomic) → автоматический откат
```

**Ключевые команды жизненного цикла:**

| Команда | Назначение | Когда использовать |
| :--- | :--- | :--- |
| `helm upgrade --install` | Идемпотентная установка/обновление | Основной способ, CI/CD |
| `helm upgrade --atomic` | Обновление с автоматическим откатом при ошибке | Production, критичные изменения |
| `helm rollback <revision>` | Откат на предыдущую ревизию | После неудачного обновления |
| `helm diff upgrade` | Просмотр изменений перед применением | Перед каждым upgrade в production |
| `helm template` | Рендеринг манифестов без применения | Отладка, GitOps, проверка шаблонов |
| `helm lint` | Проверка синтаксиса чарта | CI/CD, перед deploy |
| `helm list` | Список установленных релизов | Мониторинг, аудит |
| `helm history <release>` | История ревизий релиза | Диагностика, выбор ревизии для отката |
| `helm uninstall` | Удаление релиза | Завершение экспериментов, очистка |

### Предварительные требования

| Компонент | Требование | Примечание |
| :--- | :--- | :--- |
| **Kubernetes** | >= 1.24 | Рекомендуется 1.29+ для поддержки современных API и Gateway API. |
| **Helm** | >= 3.9.4 | Рекомендуется 3.14+ для поддержки SSA в `helm upgrade --install`. См. [Обзор Helm](../ToolsUtilities/Helm/helm_overview.md#установка-cli). |
| **StorageClass** | Обязателен | Поддержка динамического провижининга (NFS, Ceph). Без него PVC останутся в `Pending`. |
| **CPU / RAM** | 4 ядра / 8 ГБ | Минимально для тестового запуска. Для Production: 8+ ядер / 32+ ГБ. |
| **Disk** | 50+ ГБ SSD | Минимум для Gitaly + PostgreSQL + MinIO. Для production: 200+ ГБ. |
| **Network** | L3 связность между подами | Ingress-контроллер должен быть доступен извне. |

### Ключевые параметры values.yaml

| Параметр | Описание | Пример значения |
| :--- | :--- | :--- |
| `global.hosts.domain` | Основной домен GitLab | `example.com` |
| `global.hosts.gitlab.name` | Полный хостнейм для UI | `gitlab.example.com` |
| `global.hosts.https` | Включение HTTPS | `true` (production), `false` (тесты) |
| `global.ingress.configureCertmanager` | Автоматическая интеграция с cert-manager | `true` |
| `certmanager.install` | Установка встроенного cert-manager | `true` / `false` |
| `certmanager-issuer.email` | Email для Let's Encrypt | `admin@example.com` |
| `nginx-ingress.enabled` | Включение встроенного Ingress-контроллера | `true` / `false` |
| `postgresql.install` | Использование встроенной БД PostgreSQL | `false` для внешней БД |
| `global.psql.host` | Адрес внешней PostgreSQL | `postgres.internal.db` |
| `global.psql.password.secret` | Kubernetes Secret с паролем БД | `gitlab-db-password` |
| `registry.enabled` | Включение Container Registry | `false` при внешнем реестре (Harbor) |
| `global.registry.enabled` | Отключение интеграции Registry в UI | `false` |
| `gitlab-runner.install` | Установка встроенного GitLab Runner | `false` (рекомендуется отдельная установка) |
| `prometheus.install` | Установка встроенного Prometheus | `true` / `false` |
| `global.appConfig.gravatar.enabled` | Avatars через Gravatar | `false` для оффлайн-сред |

### Требования к хранилищу по компонентам

| Компонент | Тип хранилища | Мин. размер | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Gitaly** | ReadWriteOnce, быстрый диск | 50 ГБ | SSD/NVMe, `storageClassName` с IOPS > 3000 |
| **PostgreSQL** | ReadWriteOnce | 80 ГБ (дефолт) | SSD, регулярные снимки (pg_dump) |
| **Redis** | ReadWriteOnce | 5 ГБ | SSD, допустимо уменьшение для dev |
| **MinIO** | ReadWriteOnce | 50 ГБ | HDD допустимо, зависит от объёма LFS/артефактов |
| **Registry** | ReadWriteOnce | 50 ГБ | SSD для чтения/записи слоёв образов |

> **Важно:** Gitaly — наиболее требовательный к I/O компонент. Медленные диски приводят к тайм-аутам при `git push/pull` и индексации. Используйте выделенный StorageClass с высоким IOPS.

### Масштабирование ресурсов по окружениям

| Параметр | Test / Dev | Staging | Production |
| :--- | :--- | :--- | :--- |
| **CPU (Webservice)** | 0.5 ядра | 2 ядра | 4+ ядер |
| **RAM (Webservice)** | 1 ГБ | 4 ГБ | 8+ ГБ |
| **Replicas (Webservice)** | 1 | 2 | 3+ |
| **Replicas (Sidekiq)** | 1 | 1 | 2+ |
| **Gitaly** | 1 replica | 1 replica | 2+ (Gitaly Cluster) |
| **PostgreSQL** | Встроенная | Внешняя или HA | Внешняя с репликацией |
| **Redis** | Встроенная | Внешняя | Внешняя с sentinel/cluster |
| **Prometheus** | Отключен | Встроенная | Встроенная или внешняя |
| **cert-manager** | Self-signed | Let's Encrypt | Let's Encrypt или Custom CA |

### Управление секретами

GitLab Helm-чарт автоматически генерирует и хранит секреты в Kubernetes Secrets. Понимание механизма критично для диагностики и переустановки.

**Типы секретов:**

| Секрет | Назначение | Генерация |
| :--- | :--- | :--- |
| `gitlab-initial-root-password` | Пароль пользователя root | Автоматическая, одноразовая |
| `gitlab-rails-secret` | Ключи шифрования сессий и токенов | Автоматическая, **не перегенерировать** |
| `gitlab-gitaly-secret` | Аутентификация между Gitaly и Webservice | Автоматическая |
| `gitlab-db-password` | Пароль подключения к PostgreSQL | Генерируется или указывается в values |
| `gitlab-redis-password` | Пароль подключения к Redis | Генерируется или указывается в values |
| `gitlab-minio-secret` | Ключи доступа к MinIO (S3) | Генерируется или указывается в values |
| `gitlab-gitlab-shell-host-keys` | SSH-ключи хоста | Автоматическая |

> **Критично:** При переустановке GitLab **без удаления PVC** секреты и данные сохраняются. Если секреты были удалены или повреждены, компоненты не смогут взаимодействовать — потребуется полная переустановка с очисткой PVC.

**Просмотр секретов:**
```bash
# Список всех секретов GitLab
kubectl get secrets -n gitlab -l release=gitlab

# Просмотр пароля root (только для диагностики!)
kubectl get secret -n gitlab gitlab-initial-root-password \
  -o jsonpath='{.data.password}' | base64 -d && echo

# Просмотр всех ключей rails-secret
kubectl get secret -n gitlab gitlab-rails-secret -o yaml
```

### Helm hooks в GitLab чарте

Чарт использует Helm hooks для последовательного выполнения критичных операций:

| Hook | Компонент | Назначение |
| :--- | :--- | :--- |
| `pre-install` / `pre-upgrade` | `gitlab-migrations` | Миграции БД перед запуском сервисов |
| `post-install` | `gitlab-initial-root-password` | Генерация начального пароля root |
| `pre-install` | TLS-секреты | Создание/обновление TLS-сертификатов |
| `pre-upgrade` | `gitlab-backup` | Бэкап перед обновлением (опционально) |

Просмотр активных хуков:
```bash
kubectl get jobs -n gitlab -l "helm.sh/hook"
```

### Режимы проверки изменений

**Dry-run** — рендеринг и валидация без фактического применения:
```bash
# Валидация шаблонов (без отправки в API)
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --dry-run \
  --debug

# Вывод всех манифестов в stdout
helm template gitlab gitlab/gitlab \
  --namespace gitlab \
  -f values.yaml > rendered.yaml
```

**Diff** — сравнение текущего состояния с предстоящими изменениями:
```bash
# Требуется плагин: helm plugin install https://github.com/databus23/helm-diff
helm diff upgrade gitlab gitlab/gitlab \
  --namespace gitlab \
  -f values.yaml

# Автоматическое одобрение изменений
helm diff upgrade gitlab gitlab/gitlab \
  --namespace gitlab \
  -f values.yaml \
  --allow-unreleased
```

> **Рекомендация:** Всегда выполняйте `helm diff` перед `helm upgrade` в production. Это позволяет выявить нежелательные удаления ресурсов, изменение масштаба или конфигурации.

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

**Анализ параметров чарта:**
```bash
# Просмотр всех значений по умолчанию (с комментариями)
cat values.yaml | head -200

# Поиск конкретного параметра
grep -n "global.hosts" values.yaml
grep -n "postgresql" values.yaml
grep -n "certmanager" values.yaml

# Подсчёт количества параметров
grep -c ":" values.yaml
# → Typically 500+ parameters
```

**Шаблонирование для анализа ресурсов:**
```bash
# Рендеринг всех манифестов для проверки
helm template gitlab ./gitlab \
  --namespace gitlab \
  -f custom-values.yaml > rendered.yaml

# Подсчёт количества ресурсов каждого типа
grep "^kind:" rendered.yaml | sort | uniq -c | sort -rn
# →  15 Deployment
# →  10 Service
# →   8 PersistentVolumeClaim
# →   5 Secret
# →   ...

# Проверка конкретного компонента
grep -A 20 "kind: Deployment" rendered.yaml | grep -A 20 "name: gitlab-webservice"
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

**Валидация после установки:**
```bash
# Проверка статуса Helm-релиза
helm status gitlab -n gitlab
# → NAME: gitlab
# → STATUS: deployed
# → REVISION: 1

# Ожидание готовности всех подов (не блокирующая проверка)
kubectl get pods -n gitlab -w

# Проверка, что миграции завершились успешно
kubectl get jobs -n gitlab -l "app=migrations"
# → gitlab-migrations-xxx   1/1     Completed

# Проверка PVC
kubectl get pvc -n gitlab
# → gitlab-gitaly-0          Bound   pvc-xxx   50Gi   RWO   standard   5m
# → gitlab-postgresql-0      Bound   pvc-xxx   80Gi   RWO   standard   5m
```

### 3. Установка с внешним cert-manager и БД

Для production рекомендуется использовать внешние сервисы для стабильности и управления.

**Пример values.yaml для интеграции с внешней БД:**

```yaml
global:
  hosts:
    domain: example.com
    gitlab:
      name: gitlab.example.com
      https: true
  psql:
    host: postgres.internal.db
    port: 5432
    database: gitlabhq_production
    username: gitlab
    password:
      secret: gitlab-db-password
      key: password
    # SSL-подключение к БД (рекомендуется для production)
    sslmode: require
    sslrootcert:
      secret: gitlab-db-ca
      key: ca.crt
certmanager:
  install: false  # Использование существующего в кластере контроллера
postgresql:
  install: false  # Отключение встроенного субчарта
redis:
  install: false  # Отключение встроенного Redis (при внешнем)
global:
  redis:
    host: redis.internal.db
    port: 6379
    password:
      secret: gitlab-redis-password
      key: redis-password
```

**Создание секретов для внешних сервисов:**
```bash
# Секрет пароля PostgreSQL
kubectl create secret generic gitlab-db-password \
  --from-literal=password='YOUR_STRONG_PASSWORD' \
  -n gitlab

# Секрет CA-сертификата PostgreSQL (если используется SSL)
kubectl create secret generic gitlab-db-ca \
  --from-file=ca.crt=/path/to/ca.crt \
  -n gitlab

# Секрет пароля Redis
kubectl create secret generic gitlab-redis-password \
  --from-literal=redis-password='YOUR_REDIS_PASSWORD' \
  -n gitlab
```

### 4. Установка с отключёнными компонентами (dev-окружение)

Для экономии ресурсов в dev-окружениях можно отключить ресурсоёмкие компоненты:

```yaml
# dev-values.yaml
global:
  hosts:
    domain: gitlab.dev.local
    gitlab:
      name: gitlab.dev.local
      https: false
  ingress:
    configureCertmanager: false
certmanager:
  install: false
certmanager-issuer:
  install: false
nginx-ingress:
  enabled: true
  controller:
    replicaCount: 1
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
postgresql:
  primary:
    persistence:
      size: 10Gi  # Уменьшение с дефолтных 80ГБ
redis:
  master:
    persistence:
      size: 1Gi
minio:
  persistence:
    size: 10Gi
prometheus:
  install: false  # Отключение метрик для экономии RAM
gitlab-runner:
  install: false  # Установка отдельно
registry:
  enabled: false  # Использование внешнего реестра
# Уменьшение ресурсов подов
gitlab:
  webservice:
    resources:
      requests:
        cpu: 250m
        memory: 1Gi
      limits:
        cpu: 1
        memory: 2Gi
  sidekiq:
    resources:
      requests:
        cpu: 250m
        memory: 1Gi
      limits:
        cpu: 1
        memory: 2Gi
  gitaly:
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        cpu: 500m
        memory: 1Gi
```

```bash
# Установка dev-окружения
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  -f dev-values.yaml \
  --timeout 600s \
  --wait
```

### 5. Полный production values.yaml

Масштабируемая конфигурация для production-среды с внешними зависимостями:

```yaml
# production-values.yaml
global:
  hosts:
    domain: example.com
    gitlab:
      name: gitlab.example.com
      https: true
  ingress:
    configureCertmanager: true
    tls:
      enabled: true
  shell:
    port: 2222  # Альтернативный порт для SSH (избежание конфликта с портом 22 узлов)
  psql:
    host: postgres-primary.db.svc.cluster.local
    port: 5432
    database: gitlabhq_production
    username: gitlab
    password:
      secret: gitlab-db-password
      key: password
    sslmode: require
  redis:
    host: redis-master.db.svc.cluster.local
    port: 6379
    password:
      secret: gitlab-redis-password
      key: redis-password
  registry:
    enabled: false  # Использование Harbor
  appConfig:
    gravatar:
      enabled: false  # Отключение Gravatar (ᴹ-hours загрузки страниц)

certmanager:
  install: false  # Внешний cert-manager

certmanager-issuer:
  install: true
  email: admin@example.com

nginx-ingress:
  enabled: true
  controller:
    replicaCount: 2
    service:
      type: LoadBalancer
    resources:
      requests:
        cpu: 200m
        memory: 256Mi
      limits:
        cpu: 1
        memory: 512Mi

postgresql:
  install: false

redis:
  install: false

minio:
  install: true
  persistence:
    size: 100Gi

gitlab-runner:
  install: false  # Рекомендуется устанавливать отдельно

prometheus:
  install: true
  persistentVolume:
    size: 50Gi

# Ресурсы компонентов GitLab
gitlab:
  webservice:
    replicaCount: 3
    resources:
      requests:
        cpu: 500m
        memory: 3Gi
      limits:
        cpu: 4
        memory: 8Gi
    puma:
      workerTimeout: 60
  sidekiq:
    replicaCount: 2
    resources:
      requests:
        cpu: 500m
        memory: 3Gi
      limits:
        cpu: 4
        memory: 8Gi
  gitaly:
    resources:
      requests:
        cpu: 200m
        memory: 1Gi
      limits:
        cpu: 2
        memory: 4Gi
  gitlab-shell:
    replicaCount: 2
  kas:
    enabled: true
```

### 6. Проверка состояния и получение пароля

```bash
# Список всех ресурсов и проверка статуса PVC
kubectl get all,pvc -n gitlab

# Получение начального пароля root (автоматически генерируется)
kubectl get secret -n gitlab gitlab-initial-root-password \
  -o jsonpath='{.data.password}' | base64 -d && echo

# Проверка статуса всех компонентов
kubectl get deploy,sts -n gitlab

# Проверка Ingress-правил
kubectl get ingress -n gitlab

# Проверка сертификатов
kubectl get certificates -n gitlab

# Просмотр логов Webservice (для диагностики)
kubectl logs -n gitlab -l app=webservice --tail=50

# Проверка доступности (изнутри кubectl-хоста)
curl -sk https://gitlab.example.com -o /dev/null -w "%{http_code}\n"
# → 200
```

### 7. Dry-run и валидация перед изменением

```bash
# Dry-run: валидация шаблонов без фактического применения
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  -f production-values.yaml \
  --dry-run \
  --debug 2>&1 | tee dry-run-output.txt

# Проверка вывода на ошибки
grep -i "error\|warning\|failed" dry-run-output.txt

# Diff: сравнение текущего состояния с предстоящими изменениями
helm diff upgrade gitlab gitlab/gitlab \
  --namespace gitlab \
  -f production-values.yaml

# Линтинг чарта
helm lint gitlab/gitlab \
  -f production-values.yaml
```

### 8. Обновление GitLab

GitLab поддерживает обновления только по [путям обновления (Upgrade Paths)](https://docs.gitlab.com/ee/update/index.html#upgrade-paths). Никогда не перескакивайте через мажорные версии без промежуточных обновлений.

**Пошаговая процедура обновления:**
```bash
# 1. Бэкап перед обновлением (обязательно!)
kubectl exec -it $(kubectl get pod -n gitlab -l app=webservice -o jsonpath='{.items[0].metadata.name}') \
  -n gitlab -- backup-utility

# 2. Просмотр текущей версии
helm list -n gitlab
# → gitlab   gitlab   1   ...   17.2.0

# 3. Проверка diff перед обновлением
helm diff upgrade gitlab gitlab/gitlab \
  --namespace gitlab \
  --version <new_version_tag> \
  -f production-values.yaml

# 4. Обновление до целевой версии
helm upgrade gitlab gitlab/gitlab \
  --namespace gitlab \
  -f production-values.yaml \
  --version <version_tag> \
  --timeout 600s \
  --wait

# 5. Проверка после обновления
kubectl get pods -n gitlab
helm status gitlab -n gitlab
```

**Откат при проблемах:**
```bash
# Просмотр истории ревизий
helm history gitlab -n gitlab
# → REVISION  STATUS     Chart      App Version  Description
# → 1        superseded gitlab-7.x 17.2.0       Install complete
# → 2        deployed   gitlab-8.x 17.4.0       Upgrade complete

# Откат на предыдущую ревизию
helm rollback gitlab 1 -n gitlab

# Откат с ожиданием готовности
helm rollback gitlab 1 -n gitlab --wait --timeout 600s
```

### 9. Namespace isolation (ResourceQuota и LimitRange)

Для предотвращения исчерпания ресурсов кластера компонентами GitLab:

```yaml
# gitlab-namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: gitlab
  labels:
    app.kubernetes.io/name: gitlab
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: gitlab-quota
  namespace: gitlab
spec:
  hard:
    requests.cpu: "16"
    requests.memory: 64Gi
    limits.cpu: "32"
    limits.memory: 128Gi
    persistentvolumeclaims: "20"
    pods: "50"
    services.loadbalancers: "2"
    services.nodeports: "5"
---
apiVersion: v1
kind: LimitRange
metadata:
  name: gitlab-limits
  namespace: gitlab
spec:
  limits:
    - type: Container
      default:
        cpu: "1"
        memory: 2Gi
      defaultRequest:
        cpu: 250m
        memory: 512Mi
      max:
        cpu: "8"
        memory: 16Gi
      min:
        cpu: 50m
        memory: 64Mi
    - type: PersistentVolumeClaim
      max:
        storage: 200Gi
      min:
        storage: 1Gi
```

```bash
# Применение перед установкой GitLab
kubectl apply -f gitlab-namespace.yaml
```

### 10. Мониторинг встроенного Prometheus

GitLab Helm-чарт включает субчарт Prometheus для сбора метрик всех компонентов.

```yaml
# Включение Prometheus в values.yaml
prometheus:
  install: true
  persistentVolume:
    size: 50Gi
  alertmanager:
    enabled: true
  server:
    retention: 15d
    resources:
      requests:
        cpu: 200m
        memory: 1Gi
      limits:
        cpu: 1
        memory: 4Gi
```

**Проверка Prometheus:**
```bash
# Проверка подов Prometheus
kubectl get pods -n gitlab -l release=gitlab-prometheus

# Доступ к Prometheus UI (port-forward)
kubectl port-forward -n gitlab svc/gitlab-prometheus-server 9090:80 &
# → Откройте http://localhost:9090

# Просмотр метрик GitLab
curl -s http://localhost:9090/api/v1/query?query=puma_workers
```

**Настройка алертов (primer):**
```yaml
# alertmanager-rules.yaml
groups:
  - name: gitlab-alerts
    rules:
      - alert: GitLabWebserviceDown
        expr: up{job="gitlab-webservice"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "GitLab Webservice is down"
          description: "GitLab Webservice has been down for more than 2 minutes."

      - alert: GitLabGitalyHighLatency
        expr: histogram_quantile(0.95, rate(gitaly_seconds_bucket[5m])) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Gitaly high latency"
          description: "Gitaly p95 latency is above 1 second."

      - alert: GitLabPVCUsageHigh
        expr: (kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes) > 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "PVC usage above 85%"
          description: "PersistentVolumeClaim {{ $labels.persistentvolumeclaim }} is {{ $value | humanizePercentage }} full."
```

### 11. Резервное копирование и восстановление

**Создание бэкапа:**
```bash
# Запуск Job для создания бэкапа в объектное хранилище
kubectl exec -it $(kubectl get pod -n gitlab -l app=webservice -o jsonpath='{.items[0].metadata.name}') \
  -n gitlab -- backup-utility

# Проверка завершения Job
kubectl get jobs -n gitlab -l app=backup

# Бэкап PostgreSQL (если используется внешняя БД)
pg_dump -h postgres.internal.db -U gitlab -d gitlabhq_production -Fc > gitlab-db-backup.dump

# Бэкап Gitaly (репозитории)
kubectl cp gitlab/gitlab-gitaly-0:/home/git/repositories /backup/gitaly-repos
```

**Автоматизация бэкапов через CronJob:**
```yaml
# gitlab-backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: gitlab-backup
  namespace: gitlab
spec:
  schedule: "0 2 * * *"  # Ежедневно в 2:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: registry.gitlab.com/gitlab-org/build/cng/gitlab-backup-cli:latest
              command:
                - /bin/sh
                - -c
                - backup-utility
              env:
                - name: GITLAB_BACKUP_UPLOAD_CONNECTION
                  value: |
                    provider: AWS
                    region: us-east-1
                    endpoint: "https://minio.internal"
                    aws_access_key_id: "backup-key"
                    aws_secret_access_key: "backup-secret"
          restartPolicy: OnFailure
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
```

**Восстановление из бэкапа:**
```bash
# 1. Остановка Webservice и Sidekiq
kubectl scale deployment gitlab-webservice -n gitlab --replicas=0
kubectl scale deployment gitlab-sidekiq -n gitlab --replicas=0

# 2. Копирование бэкапа в под
kubectl cp /path/to/backup.tar gitlab/gitlab-webservice-0:/tmp/backup.tar

# 3. Восстановление
kubectl exec -it gitlab-webservice-0 -n gitlab -- \
  backup-utility restore BACKUP=backup

# 4. Запуск миграций
kubectl exec -it gitlab-webservice-0 -n gitlab -- \
  bundle exec rake db:migrate

# 5. Перезапуск сервисов
kubectl scale deployment gitlab-webservice -n gitlab --replicas=3
kubectl scale deployment gitlab-sidekiq -n gitlab --replicas=2
```

---

## Дополнительная информация

### Таблица размерности ресурсов (Sizing Guide)

Размеры ресурсов зависят от количества активных пользователей и интенсивности использования CI/CD.

| Параметр | Тест / Dev (1-10 пользователей) | Staging (10-50) | Production (50-500) | Production (500+) |
| :--- | :--- | :--- | :--- | :--- |
| **CPU (Webservice)** | 0.5 - 1 ядро | 2 ядра | 4 ядра | 8+ ядер |
| **RAM (Webservice)** | 1 - 2 ГБ | 4 ГБ | 8 ГБ | 16+ ГБ |
| **Replicas (Webservice)** | 1 | 2 | 3 | 5+ |
| **CPU (Sidekiq)** | 0.5 - 1 ядро | 1 ядро | 2 ядра | 4+ ядер |
| **RAM (Sidekiq)** | 1 - 2 ГБ | 2 ГБ | 4 ГБ | 8+ ГБ |
| **Replicas (Sidekiq)** | 1 | 1 | 2 | 3+ |
| **CPU (Gitaly)** | 0.25 ядра | 0.5 ядра | 1 ядро | 2+ ядер |
| **RAM (Gitaly)** | 0.5 ГБ | 1 ГБ | 2 ГБ | 4+ ГБ |
| **Disk (Gitaly)** | 20 ГБ SSD | 50 ГБ SSD | 100 ГБ SSD | 200+ ГБ NVMe |
| **Disk (PostgreSQL)** | 10 ГБ | 50 ГБ | 100 ГБ | 200+ ГБ |
| **Disk (MinIO)** | 10 ГБ | 50 ГБ | 100 ГБ | 500+ ГБ |
| **Total CPU кластера** | 4 ядра | 8 ядер | 16 ядер | 32+ ядер |
| **Total RAM кластера** | 8 ГБ | 16 ГБ | 64 ГБ | 128+ ГБ |

> **Формула оценки:** На каждого активного пользователя GitLab требуется примерно 200-400 МБ RAM и 0.1-0.2 ядра CPU. CI/CD-нагрузка может увеличивать потребление в 2-5 раз.

### Требования к хранилищу по компонентам

| Компонент | Мин. размер (dev) | Рекомендуемый (prod) | Тип диска | IOPS | Примечание |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Gitaly** | 20 ГБ | 100+ ГБ | SSD/NVMe | > 3000 | Критичен к IOPS — медленные диски = тайм-ауты `git push/pull` |
| **PostgreSQL** | 10 ГБ | 100+ ГБ | SSD | > 1000 | Требует регулярных pg_dump бэкапов |
| **Redis** | 1 ГБ | 5 ГБ | SSD | > 500 | Допустимо уменьшение для dev, но без SSD будут задержки |
| **MinIO** | 10 ГБ | 100+ ГБ | HDD/SSD | > 300 | Зависит от объёма LFS и артефактов CI/CD |
| **Registry** | 10 ГБ | 100+ ГБ | SSD | > 500 | Слои образов требуют быстрого чтения |
| **Prometheus** | 5 ГБ | 50 ГБ | SSD | > 300 | Хранение метрик, зависит от retention |
| **PostgreSQL (WAL)** | — | 10+ ГБ | SSD | > 1000 | Write-Ahead Log, критичен для производительности |

### Проверка StorageClass

```bash
# Просмотр доступных StorageClass
kubectl get storageclass
# → NAME                 PROVISIONER                    RECLAIMPOLICY   VOLUMEBINDINGMODE   AGE
# → standard (default)   k8s.io/no-provisioner          Delete          WaitForFirstConsumer   10d

# Проверка default StorageClass
kubectl get sc -o jsonpath='{.items[*].metadata.annotations.storageclass\.kubernetes\.io/is-default-class}'

# Проверка capacity существующих PV
kubectl get pv
```

### Безопасность (Security Hardening)

**Pod Security Standards (рекомендуется для production):**

```yaml
# gitlab-namespace-security.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: gitlab
  labels:
    # Запрет привилегированных контейнеров
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

**NetworkPolicy для GitLab:**

```yaml
# gitlab-network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: gitlab-isolation
  namespace: gitlab
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              app.kubernetes.io/name: ingress-nginx
      ports:
        - port: 80
        - port: 443
        - port: 8181  # KAS
  egress:
    # DNS
    - to: []
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # HTTPS (Let's Encrypt, webhooks, registry)
    - to: []
      ports:
        - port: 443
          protocol: TCP
    # PostgreSQL (внешняя БД)
    - to: []
      ports:
        - port: 5432
          protocol: TCP
    # Redis (внешний)
    - to: []
      ports:
        - port: 6379
          protocol: TCP
```

**Шифрование секретов (Encryption at Rest):**

```bash
# Проверка включённого шифрования etcd
kubectl get --raw /metrics | grep apiserver_encryption_config_controller_reconciliations_total

# Создание EncryptionConfiguration (требуется Kubernetes 1.27+)
# Размещается на control plane: /etc/kubernetes/encryption-config.yaml
```

### Типичные ошибки при установке и их решения

Более подробное руководство по диагностике см. в [Решение проблем при установке](./gitlab_installation_troubleshooting.md).

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в `Pending`** | PVC не может быть provisioned | `kubectl describe pvc <name> -n gitlab` — проверьте StorageClass |
| **Pod в `CrashLoopBackOff`** | OOMKilled или невалидная конфигурация | `kubectl logs <pod> -n gitlab --previous` — проверьте логи предыдущего запуска |
| **`gitlab-migrations` в `Error`** | Ошибка миграции БД | Проверьте логи: `kubectl logs -l app=migrations -n gitlab` |
| **502 Bad Gateway** | Webservice не готов | `kubectl get pods -l app=webservice -n gitlab` — увеличьте `readinessProbe` |
| **SSL: "Unknown Authority"** | Самоподписанный сертификат | `global.hosts.https: false` для тестов или настройте cert-manager |
| **SSH: "Connection refused"** | Порт 22 занят на узле | `global.shell.port: 2222` — альтернативный порт |
| **Registry: "unauthorized"** | Нет доступа к registry | Personal Access Token с `read_registry`/`write_registry` scopes |
| **Shared Secrets Mismatch** | Расхождение ключей при переустановке | Удалите PVC и установите заново (для dev) |
| **Gitaly: "timeout"` | Медленный диск | Используйте SSD/NVMe с IOPS > 3000 |

### Диагностический чек-лист

```bash
# 1. Статус Helm-релиза
helm status gitlab -n gitlab

# 2. Все поды GitLab
kubectl get pods -n gitlab

# 3. Поды с ошибками
kubectl get pods -n gitlab --field-selector=status.phase!=Running

# 4. Все PVC и их статус
kubectl get pvc -n gitlab

# 5. События кластера (ошибки планирования, OOM, etc.)
kubectl get events -n gitlab --sort-by='.lastTimestamp' | tail -20

# 6. Ingress-правила
kubectl get ingress -n gitlab -o yaml

# 7. Сертификаты
kubectl get certificates -n gitlab
kubectl describe certificate -n gitlab

# 8. Lоги ключевых компонентов
kubectl logs -n gitlab -l app=webservice --tail=30
kubectl logs -n gitlab -l app=gitaly --tail=30
kubectl logs -n gitlab -l app=sidekiq --tail=30

# 9. Проверка доступности (curl)
curl -sk https://gitlab.example.com -o /dev/null -w "HTTP: %{http_code}\n"

# 10. Проверка DNS
nslookup gitlab.example.com
nslookup registry.example.com
```

### Disaster Recovery (Восстановление после сбоя)

**Сценарий 1: Потеря пода (автоматическое восстановление):**
```bash
# Kubernetes автоматически перезапускает поды
kubectl get pods -n gitlab -w  # Мониторинг автоматического восстановления

# Принудительный перезапуск пода
kubectl delete pod <pod-name> -n gitlab
```

**Сценарий 2: Потеря узла (drain и перепланирование):**
```bash
# Безопасное обслуживание узла
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --grace-period=600

# После обслуживания
kubectl uncordon <node>
```

**Сценарий 3: Полное восстановление кластера:**
```bash
# 1. Удаление старого релиза (данные в PVC сохраняются)
helm uninstall gitlab -n gitlab

# 2. Удаление старых секретов (если повреждены)
kubectl delete secrets -n gitlab -l release=gitlab

# 3. Переустановка с теми же values.yaml
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  -f production-values.yaml \
  --timeout 600s

# 4. Если PVC сохранены — данные восстановятся автоматически
kubectl get pvc -n gitlab
```

**Сценарий 4: Восстановление PostgreSQL:**
```bash
# Восстановление из pg_dump
kubectl exec -it $(kubectl get pod -n db -l app=postgresql -o jsonpath='{.items[0].metadata.name}') \
  -n db -- pg_restore -U gitlab -d gitlabhq_production /tmp/gitlab-db-backup.dump

# Перезапуск Sidekiq (для обработки очереди)
kubectl rollout restart deployment gitlab-sidekiq -n gitlab
```

### Логирование

**Настройка агрегации логов GitLab:**

```yaml
# gitlab-logging-values.yaml — включение stdout/stderr логов
gitlab:
  webservice:
    logging:
      level: info
      format: json  # Структурированные логи для парсинга
  sidekiq:
    logging:
      level: info
      format: json
  gitaly:
    logging:
      level: info
      format: json
```

**Просмотр логов:**
```bash
# Логи Webservice (Puma)
kubectl logs -n gitlab -l app=webservice -c webservice --tail=100

# Логи Sidekiq
kubectl logs -n gitlab -l app=sidekiq --tail=100

# Логи Gitaly
kubectl logs -n gitlab -l app=gitaly --tail=100

# Логи KAS (Kubernetes Agent Server)
kubectl logs -n gitlab -l app=kas --tail=100

# Фильтрация по уровню
kubectl logs -n gitlab -l app=webservice --tail=1000 | grep -i "error\|warn"
```

### Ограничения и рекомендации

| Аспект | Рекомендация |
| :--- | :--- |
| **Хранилище** | Всегда проверяйте доступность StorageClass. См. [Решение проблем с PVC](./gitlab_installation_troubleshooting.md). |
| **Доступ** | Для bare-metal используйте MetalLB или NodePort. См. [Методы доступа](./gitlab_kubernetes_access.md). |
| **Обновления** | Всегда делайте бэкап БД перед `helm upgrade`. Используйте `helm diff` для проверки. |
| **--atomic** | Используйте `--atomic` в production для автоматического отката при ошибке. |
| **Ресурсы** | Всегда задавайте `requests` и `limits` для всех компонентов. Без этого планировщик может разместить поды на узлах с недостаточными ресурсами. |
| **Gitaly** | Используйте выделенный StorageClass с высоким IOPS для Gitaly. Медленные диски — основная причина тайм-аутов. |
| **Бэкапы** | Автоматизируйте бэкапы через CronJob. Храните бэкапы вне кластера (объектное хранилище). |
| **Мониторинг** | Настройте алерты на unavailable pods, certificate expiration, PVC usage. |

### См. также

- [Методы доступа к GitLab](./gitlab_kubernetes_access.md)
- [Решение проблем при установке](./gitlab_installation_troubleshooting.md)
- [Установка GitLab Runner](./gitlab_runner_kubernetes_installation.md)
