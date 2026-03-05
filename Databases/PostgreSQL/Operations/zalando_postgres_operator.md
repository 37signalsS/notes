# Zalando Postgres Operator

## Определения

**Zalando Postgres Operator** — это приложение для Kubernetes, которое автоматизирует создание, синхронизацию и управление кластерами PostgreSQL. Оно расширяет API Kubernetes с помощью Custom Resource Definitions (CRD) для декларативного управления базами данных.

## Базовые концепции

### Способы развертывания приложений в Kubernetes

1. **Манифесты (Manifests):**
    * **Процесс:** Прямое описание ресурсов (Deployment, Service, ConfigMap и т.д.) в YAML-файлах.
    * **Плюсы:** Полный контроль, стандартный подход Kubernetes.
    * **Минусы:** Неудобно для управления множеством однотипных приложений. Изменение параметров требует ручного редактирования множества строк в разных файлах.

2. **Helm Charts:**
    * **Процесс:** Шаблонизация манифестов. Параметры выносятся в файл `values.yaml`, что упрощает настройку. Управление происходит с рабочей машины администратора.
    * **Плюсы:** Упрощает установку и обновление сложных приложений. Легко делиться и переиспользовать.
    * **Минусы:** Не следует парадигме Kubernetes "отправил манифест в кластер и забыл". Логика управления находится вне кластера.

3. **Операторы (Operators):**
    * **Процесс:** В кластер устанавливается специальное приложение (оператор), которое следит за кастомными ресурсами (CRD, например `kind: postgresql`). Получив такой манифест, оператор сам создает необходимые стандартные ресурсы (StatefulSet, Service и т.д.).
    * **Плюсы:** Полностью автоматизирует жизненный цикл приложения, включая сложные операции (обновления, бэкапы, восстановление). Работает по нативной для Kubernetes схеме. Упрощает манифест до описания высокоуровневых параметров.
    * **Минусы:** Разработка оператора — это полноценное программирование. Функционал ограничен тем, что заложили разработчики. Выйти за его пределы можно, только форкнув и изменив исходный код.

### Особенности Zalando Operator

* **Цель создания:** Написан для управления огромным количеством (1500+) кластеров PostgreSQL в Zalando.
* **Философия:** Упрощение развертывания множества однотипных кластеров за счет сокращения вариативности конфигурации.
* **Ограничения:** Функционал уступает гибкости ручного управления через манифесты, но достаточен для решения 95% типовых задач.

### Основные возможности

* **Кластеризация:** Развертывание кластера PostgreSQL с мастером и одной или несколькими репликами.
* **Доступ:** Автоматическое создание сервисов для доступа к мастеру (`-master`) и репликам (`-replica`). Для внешнего доступа предполагается использование `LoadBalancer`.
* **Резервное копирование:**
  * **Физическое:** Регулярные бэкапы (base backup + WAL) в облачные хранилища (S3, GCS). Встроенной поддержки NFS нет.
  * **Логическое:** Возможность делать бэкапы в виде SQL-файлов.
* **Восстановление и клонирование:** Возможность восстанавливаться из бэкапов и создавать новые кластеры (клоны) на их основе.
* **Standby-кластеры:** Создание кластеров в режиме read-only, которые накатывают бэкапы из основного кластера.
* **Connection Pooling:** Интеграция с **PgBouncer** для управления пулом соединений к мастеру или репликам.

## Практические сценарии

### 1. Установка и настройка оператора

Процесс установки основан на Helm.

**Шаг 1: Добавление репозиториев**

```bash
# Репозиторий самого оператора
helm repo add postgres-operator https://opensource.zalando.com/postgres-operator/charts/postgres-operator

# Репозиторий веб-интерфейса
helm repo add postgres-operator-ui https://opensource.zalando.com/postgres-operator/charts/postgres-operator-ui

helm repo update
```

**Шаг 2: Подготовка `values.yaml` для оператора**

Создайте файл `values.yaml` для настройки оператора.

```bash
helm show values postgres-operator/postgres-operator > operator-values.yaml
```

**Шаг 3: Конфигурация оператора**

Отредактируйте `operator-values.yaml`. Ключевые параметры:

```yaml
# values.yaml

# Версия оператора должна быть совместима с версией Kubernetes.
# Например, для K8s 1.26.x подходит оператор 1.10.0.
# image.tag: 1.10.0

# Включаем логи в формате JSON для удобства парсинга
logging:
  logFormat: json

# Убеждаемся, что CRD будут зарегистрированы
enableCrdRegistration: true

# ВАЖНО: Zalando использует несколько registry.
# Для образа Spilo (сам PostgreSQL) нужно указать правильный.
# Узнать последнюю версию можно через Swagger UI Zalando.
# https://opensource.zalando.com/postgres-operator/docs/reference/operator_api/
# На февраль 2026 актуальная версия 3.0-p1
configGeneral:
  spilo_docker_image: "registry.opensource.zalan.do/acid/spilo-15:3.0-p1"
  # Остальные параметры можно оставить по умолчанию

configKubernetes:
  # Домен вашего кластера
  cluster_domain: cluster.local

  # Включаем anti-affinity, чтобы поды PostgreSQL не запускались на одной ноде
  # Это настраивается здесь, а не в манифесте самого кластера!
  enable_pod_anti_affinity: true

  # Включаем readiness probe для подов базы данных
  readiness_probe_initial_delay_seconds: 5
  readiness_probe_period_seconds: 10
  readiness_probe_timeout_seconds: 5
  readiness_probe_failure_threshold: 3
  readiness_probe_success_threshold: 1

  # Оператор будет следить за всеми неймспейсами
  watched_namespace: '*'
```

**Шаг 4: Установка оператора**

```bash
helm install postgres-operator postgres-operator/postgres-operator \
  --namespace postgres-operator \
  --create-namespace \
  -f operator-values.yaml
```

### 2. Установка и настройка UI

Веб-интерфейс упрощает создание кластеров для команд, не знакомых с `kubectl`.

**Шаг 1: Подготовка `values.yaml` для UI**

```bash
helm show values postgres-operator-ui/postgres-operator-ui > ui-values.yaml
```

**Шаг 2: Конфигурация UI**

Отредактируйте `ui-values.yaml`.

```yaml
# ui-values.yaml

# ВАЖНО: На февраль 2026 версия UI 1.10.0 работает нестабильно.
# Рекомендуется использовать 1.9.0, которая совместима с оператором 1.10.0.
image:
  tag: 1.9.0

# Настройки для подключения к API оператора
env:
  # Указываем, где находится API оператора
  - name: "OPERATOR_API_URL"
    value: "http://postgres-operator.postgres-operator.svc.cluster.local:8080"
  
  # Неймспейс, в котором UI будет по умолчанию создавать кластеры
  - name: "TARGET_NAMESPACE"
    value: "postgres-operator"

# Настройка Ingress для доступа к UI
ingress:
  enabled: true
  # Класс вашего Ingress-контроллера
  ingressClassName: nginx
  hosts:
    - host: pg-operator-ui.your.domain
      paths:
        - path: /
          pathType: ImplementationSpecific
```

**Шаг 3: Установка UI**

```bash
helm install postgres-operator-ui postgres-operator-ui/postgres-operator-ui \
  --namespace postgres-operator \
  -f ui-values.yaml
```

### 3. Пример манифеста кластера

После установки оператора можно создавать кластеры с помощью простого манифеста.

```yaml
# my-cluster.yaml
apiVersion: "postgresql.zalando.com/v1"
kind: postgresql
metadata:
  name: my-first-cluster
  namespace: postgres-operator
spec:
  teamId: "acid" # Обязательное поле, даже если не используется
  volume:
    size: "5Gi"
  numberOfInstances: 2 # 1 мастер и 1 реплика
  users:
    # Ключ - имя пользователя
    zalando:
      - superuser
      - createdb
  databases:
    # Ключ - имя базы, значение - владелец
    mydatabase: zalando
  postgresql:
    version: "15" # Версия PostgreSQL
  # Запросы и лимиты для подов
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
```

**Развертывание:**

```bash
kubectl apply -f my-cluster.yaml
```

## Дополнительная информация

### Управление пользователями

* **`enable_admin_role_for_users`:** Параметр в `values.yaml` оператора, который по умолчанию дает всем создаваемым пользователям права администратора.
* **`postgresql-team` CRD:** Позволяет управлять командами и их членами централизованно, однако это усложнение, которое не всегда нужно.

### Связанные концепции

* **Резервное копирование:** Подробнее о стратегиях бэкапов см. **[Резервное копирование и восстановление](../Concepts/backup_and_recovery.md)**.
* **Альтернативные операторы:** Сравнение с CloudNativePG доступно в разделе **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)**.

### Возможные проблемы и их решения

* **UI не работает:** Версия UI `1.10.0` может работать нестабильно. Решение — откатиться на `1.9.0`, как показано в примере выше.
* **Ограниченный функционал:** Если вам нужна возможность, которую оператор не поддерживает (например, бэкап на NFS), у вас три пути:
    1. Написать "костыль" вокруг оператора.
    2. Форкнуть репозиторий оператора и дописать нужный функционал на Go.
    3. Использовать другой инструмент (например, CloudNativePG или ручные манифесты).
