# Манифест Kubernetes Deployment и лучшие практики

**Актуально для:** Kubernetes 1.30–1.32+

Руководство по созданию отказоустойчивых, безопасных и масштабируемых манифестов для stateless-приложений: полный разбор полей объекта `Deployment`, шаблона пода, практические сценарии применения, команды управления и эксплуатация в контексте DevOps, SRE и системного администрирования.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes (v1.30+ для полной поддержки актуальных возможностей и PSA Restricted, v1.16+ для стабильной API-группы `apps/v1`).
- Установленный и настроенный CLI-клиент `kubectl` с правами оператора на чтение и модификацию ресурсов (`get`, `apply`, `describe`, `diff`, `annotate`, `rollout`, `scale`). Флаг `--record` окончательно удален в v1.24; документирование причин ревизий выполняется через аннотацию `kubernetes.io/change-cause`.
- Манифесты, зафиксированные в системе контроля версий (Git) — фундамент воспроизводимости, аудита и автоматизированного отката.
- Базовое понимание взаимосвязи абстракций ядра: [Deployment](./index.md), [ReplicaSet](../replicaset.md) и [Pod](../Pod/pod_overview.md).
- Инструменты статической валидации манифестов: `kubeconform` (см. [Kubeconform](../../ToolsUtilities/kubeconform_overview.md)) или `kubectl diff` с доступом к API-серверу.
- Настроенные политики окружения: [ResourceQuota и LimitRange](../../Scheduling/qos_limit_and_requests.md), [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md) и [Pod Security Standards](../../Security/pod_security_context.md).

## 1. Определения

**Манифест Deployment** — декларативная спецификация желаемого состояния stateless-нагрузки в формате YAML/JSON, описывающая конфигурацию запуска контейнеров, требования к вычислительным ресурсам, сетевые порты, проверки жизнедеятельности, топологию размещения и правила проведения обновлений.

**Production-манифест** — манифест, соответствующий промышленным стандартам безопасности (профиль Pod Security Standards Restricted, изоляция привилегий), надежности (гарантированные классы QoS, триада проб, топологическое распределение) и наблюдаемости (стандартизированные метки SIG-Apps, аннотации метрик).

**Шаблон пода (PodTemplateSpec)** — вложенная структура `spec.template`, определяющая спецификацию создаваемых подов. Любое изменение содержимого `spec.template` меняет хеш ревизии (`pod-template-hash`) и инициирует создание нового `ReplicaSet`.

**Селектор меток (Label Selector)** — неизменяемое после создания правило выборки (`spec.selector`), связывающее контроллер `Deployment` с его дочерними подами. Поля `spec.selector.matchLabels` обязаны строго совпадать с `spec.template.metadata.labels`.

**Стратегия обновления (Deployment Strategy)** — логика ротации реплик при изменении шаблона пода:
- `RollingUpdate` — постепенная замена старых экземпляров новыми с контролем всплеска (`maxSurge`) и допустимого снижения мощности (`maxUnavailable`).
- `Recreate` — полная остановка всех старых подов перед запуском новых (вызывает даунтайм, применяется при несовместимости версий или монопольном захвате данных).

**Глубина истории ревизий (revisionHistoryLimit)** — количество неактивных объектов `ReplicaSet` (смасштабированных в 0), сохраняемых контроллером в `etcd` для возможности мгновенного отката (`kubectl rollout undo`).

**Таймаут прогресса (progressDeadlineSeconds)** — максимальное время ожидания завершения фазы обновления, по истечении которого контроллер переводит условие `Progressing` в статус `False` с причиной `ProgressDeadlineExceeded` (при этом контроллер не производит автоматический откат самостоятельно).

**Контекст безопасности (Security Context)** — параметры ограничения привилегий Linux (UID/GID, Capabilities, Seccomp, Read-only Root Filesystem), задаваемые на уровне пода (`PodSecurityContext`) и каждого контейнера индивидуально (`SecurityContext`).

**Плавное завершение (Graceful Shutdown)** — регламентированный цикл вывода пода из эксплуатации: синхронизация удаления из сетевых эндпоинтов, выполнение хука `lifecycle.preStop`, отправка сигнала `SIGTERM` и ожидание в течение `terminationGracePeriodSeconds` перед принудительным `SIGKILL`.

## 2. Базовые концепции и архитектура

### Механизм контроллера и цикл согласования

В архитектуре Kubernetes объект `Deployment` представляет собой контроллер более высокого порядка над `ReplicaSet`:

```text
Deployment Controller (kube-controller-manager)
       │
       ▼  (управляет ревизиями через spec.template)
   ReplicaSet (новая версия: pod-template-hash-B) ──► Pods [v2]
   ReplicaSet (старая версия: pod-template-hash-A) ──► Pods [v1] (масштабируется в 0)
```

1. **Декларативное состояние:** Пользователь отправляет манифест в `kube-apiserver`.
2. **Reconciliation Loop:** Цикл согласования контроллера `Deployment` сравнивает спецификацию (`spec`) и текущий статус (`status`).
3. **Генерация хеша шаблона:** При модификации `spec.template` вычисляется 32-битный FNV-хеш от структуры шаблона пода, который записывается в метку `pod-template-hash` нового `ReplicaSet`.
4. **Управление репликами:** Контроллер Deployment управляет только счетчиком `spec.replicas` в связанных `ReplicaSet`. Сами контейнеры создаются и контролируются демоном `kubelet` через контроллер `ReplicaSet`.

### Полная структура манифеста

Манифест `Deployment` состоит из четко разграниченных секций:

```text
apiVersion: apps/v1            # Стабильная API-группа для рабочих нагрузок
kind: Deployment               # Тип ресурса
metadata:                      # Идентификация, пространство имен, метаданные
  name, namespace, labels, annotations
spec:                          # Желаемое состояние контроллера Deployment
  replicas                     # Количество экземпляров
  selector                     # Связующий селектор (неизменяем)
  strategy                     # Параметры ротации (RollingUpdate / Recreate)
  revisionHistoryLimit         # Число сохраняемых старых ReplicaSet (дефолт: 10)
  progressDeadlineSeconds      # Лимит времени на успешный rollout (дефолт: 600)
  minReadySeconds              # Время стабилизации пода перед признанием Available
  paused                       # Флаг приостановки процесса выкатки
  template:                    # Шаблон пода (PodTemplateSpec)
    metadata:                  # Метки и аннотации конкретных подов
      labels, annotations
    spec:                      # Спецификация пода (PodSpec)
      securityContext          # Безопасность на уровне пода
      priorityClassName        # Приоритет вытеснения планировщика
      terminationGracePeriodSeconds # Время на корректное завершение
      automountServiceAccountToken  # Отключение токена API K8s
      dnsConfig, topologySpreadConstraints, affinity, tolerations
      initContainers           # Подготовительные контейнеры и native sidecars
      containers:              # Основные рабочие контейнеры
        image, ports, env, resources, securityContext, probes, volumeMounts
      volumes                  # Тома (emptyDir, configMap, secret, projected)
status:                        # Фактическое состояние (генерируется контроллером)
```

### Эталонный Production-манифест

Ниже приведен эталонный манифест для stateless веб-сервиса, развертываемого в корпоративном/on-premise кластере. Манифест полностью удовлетворяет требованиям **Pod Security Standards (Restricted)**, гарантирует класс качества обслуживания **Guaranteed** по памяти, содержит защиту от сбоев DNS, корректный дренаж сетевых соединений и топологическое распределение по узлам.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-frontend
  namespace: production
  labels:
    app.kubernetes.io/name: frontend
    app.kubernetes.io/instance: frontend-prod
    app.kubernetes.io/version: "1.4.2"
    app.kubernetes.io/component: web
    app.kubernetes.io/part-of: core-portal
    app.kubernetes.io/managed-by: manual
  annotations:
    kubernetes.io/change-cause: "Релиз 1.4.2: обновление рантайма, фикс утечки памяти"
    prometheus.io/scrape: "true"
    prometheus.io/port: "8080"
    prometheus.io/path: "/metrics"
spec:
  replicas: 3
  revisionHistoryLimit: 5
  progressDeadlineSeconds: 600
  minReadySeconds: 15
  selector:
    matchLabels:
      app.kubernetes.io/name: frontend
      app.kubernetes.io/instance: frontend-prod
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    metadata:
      labels:
        app.kubernetes.io/name: frontend
        app.kubernetes.io/instance: frontend-prod
        app.kubernetes.io/version: "1.4.2"
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
        prometheus.io/path: "/metrics"
    spec:
      # Изоляция прав на уровне пода (PSA Restricted compliant)
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        fsGroupChangePolicy: "OnRootMismatch"
        seccompProfile:
          type: RuntimeDefault

      # Отключение монтирования ServiceAccount токена (защита от кражи credentials)
      automountServiceAccountToken: false

      # Приоритет планирования и тайминги завершения
      priorityClassName: high-priority-workload
      terminationGracePeriodSeconds: 60

      # Оптимизация резолвинга DNS для снижения нагрузки на CoreDNS
      dnsConfig:
        options:
        - name: ndots
          value: "2"
        - name: single-request-reopen

      # Равномерное распределение подов по хостам для отказоустойчивости
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: "kubernetes.io/hostname"
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app.kubernetes.io/name: frontend
            app.kubernetes.io/instance: frontend-prod

      containers:
      - name: web-app
        image: registry.internal/frontend:1.4.2
        imagePullPolicy: IfNotPresent

        ports:
        - name: http
          containerPort: 8080
          protocol: TCP

        # Переменные окружения из ConfigMap и Secret
        envFrom:
        - configMapRef:
            name: app-frontend-config
        - secretRef:
            name: app-frontend-secrets

        # Управление вычислительными ресурсами
        # Память: requests == limits (QoS Guaranteed по памяти, защита от OOMKill)
        # CPU: requests гарантируют резерв, limits ограничивают всплески
        resources:
          requests:
            cpu: "250m"
            memory: "512Mi"
            ephemeral-storage: "100Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
            ephemeral-storage: "250Mi"

        # Hardening контейнера (минимальные привилегии)
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL

        # Монтирование изменяемых путей для readOnlyRootFilesystem
        volumeMounts:
        - name: tmp-dir
          mountPath: /tmp
        - name: cache-dir
          mountPath: /var/cache/app

        # Жизненный цикл: задержка выключения для синхронизации EndpointSlice / iptables
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"]

        # Триада проверок (Health Checks)
        startupProbe:
          httpGet:
            path: /healthz/startup
            port: http
          failureThreshold: 30
          periodSeconds: 5
          timeoutSeconds: 2

        readinessProbe:
          httpGet:
            path: /healthz/ready
            port: http
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 2
          successThreshold: 1
          failureThreshold: 3

        livenessProbe:
          httpGet:
            path: /healthz/live
            port: http
          initialDelaySeconds: 10
          periodSeconds: 15
          timeoutSeconds: 2
          failureThreshold: 3

      volumes:
      - name: tmp-dir
        emptyDir:
          sizeLimit: 100Mi
      - name: cache-dir
        emptyDir:
          sizeLimit: 150Mi
```

### Ключевые поля объекта Deployment (spec)

| Поле | Тип | Значение по умолчанию | Назначение и эксплуатационные рекомендации |
| :--- | :--- | :--- | :--- |
| `apiVersion` | `string` | — | Для Deployment всегда `apps/v1`. Все устаревшие версии (`extensions/v1beta1`, `apps/v1beta1`) полностью удалены из API K8s. |
| `kind` | `string` | — | Обязательное строковое значение `Deployment`. |
| `metadata.name` | `string` | — | Уникальный идентификатор в рамках `namespace`. Формат: `DNS-1123 subdomain` (только строчные латинские буквы, цифры, дефис). |
| `metadata.namespace` | `string` | `default` | Пространство имен. Всегда указывайте явно для предотвращения случайного деплоя в `default`. |
| `spec.replicas` | `integer` | `1` | Желаемое количество экземпляров пода. Для обеспечения HA задавайте минимум 2 (оптимально 3+). Изменение значения масштабирует существующий ReplicaSet без создания новой ревизии. |
| `spec.selector` | `object` | — | Обязательное поле связки контроллера с подами. **Неизменяемо после создания объекта**. Попытка изменить селектор вызовет ошибку `field is immutable`. |
| `spec.strategy` | `object` | `RollingUpdate` | Механизм обновления. Поддерживает `RollingUpdate` (рекомендуется для 99% веб-сервисов) и `Recreate` (используется при невозможности параллельной работы версий, например при несовместимости схемы данных). |
| `spec.strategy.rollingUpdate.maxSurge` | `int_or_string` | `25%` | Максимальное количество подов, создаваемых сверх `replicas`. При значении в процентах округляется **вверх**. Значение `1` или `25%` гарантирует наличие дополнительных мощностей при обновлении. |
| `spec.strategy.rollingUpdate.maxUnavailable` | `int_or_string` | `25%` | Максимальное число подов, которые могут быть недоступны во время выкатки. Округляется **вниз**. Для бесперебойной работы (Zero Downtime) устанавливайте в `0`. Оба параметра (`maxSurge` и `maxUnavailable`) не могут быть одновременно равны `0`. |
| `spec.revisionHistoryLimit` | `integer` | `10` | Количество сохраняемых в `etcd` неактивных `ReplicaSet`. Рекомендуется снижать до `3–5`. Значения 10+ засоряют базу данных `etcd` и замедляют листинг ресурсов. |
| `spec.progressDeadlineSeconds` | `integer` | `600` | Время в секундах, в течение которого контроллер ожидает завершения фазы обновления. Если за это время новые поды не стали Available, выставляется `Progressing=False` (`ProgressDeadlineExceeded`). Таймер не останавливает rollout и не выполняет откат самостоятельно. |
| `spec.minReadySeconds` | `integer` | `0` | Минимальное время (в секундах), в течение которого новый под должен находиться в состоянии `Ready` без падений контейнеров, чтобы считаться доступным (`Available`). Для продакшена выставляйте `15–60` для исключения маскировки ранних падений приложения (flapping/crashloop). |
| `spec.paused` | `boolean` | `false` | Установка в `true` замораживает процесс ротации. Все изменения шаблона фиксируются, но контроллер не запускает создание новых подов. Применяется для пакетирования множественных изменений. |

### Ключевые поля шаблона пода (Pod Spec)

| Поле | Уровень | Назначение и специфика DevOps / SRE |
| :--- | :--- | :--- |
| `spec.securityContext` | Pod | Глобальные настройки ядра Linux: `runAsNonRoot: true`, `runAsUser`, `runAsGroup`, `fsGroup`, `seccompProfile.type: RuntimeDefault`. Обеспечивает изоляцию процесса от root-пользователя хоста. |
| `spec.priorityClassName` | Pod | Управляет вытеснением (preemption) при дефиците ресурсов на узле. Критические сервисы должны использовать `priorityClassName` с высоким весом, чтобы Kubelet не вытеснял их первыми при MemoryPressure. |
| `spec.automountServiceAccountToken` | Pod | По умолчанию `true`. При значении `false` отключает внедрение JWT-токена в `/var/run/secrets/kubernetes.io/serviceaccount`, предотвращая эксплуатацию прав API-сервера в случае компрометации контейнера. |
| `spec.terminationGracePeriodSeconds` | Pod | Таймаут (по умолчанию 30с) на штатное завершение приложения перед принудительным `SIGKILL`. Должен рассчитываться по формуле: `время preStop + максимальное время дренажа соединений + запас (5-10с)`. |
| `spec.restartPolicy` | Pod | Для `Deployment` допускается **исключительно** значение `Always` (устанавливается по умолчанию). Значения `OnFailure` и `Never` запрещены валидатором API. |
| `spec.topologySpreadConstraints` | Pod | Правила равномерного распределения реплик по доменам отказа (узлы, серверные стойки, локации). Обеспечивает устойчивость к выходу из строя оборудования. |
| `spec.affinity` | Pod | `podAntiAffinity` (запрет запуска реплик на одном хосте) и `nodeAffinity` (гибкая привязка к группам нод с определенными метками железа). |
| `spec.dnsConfig` | Pod | Тюнинг параметров DNS-клиента в `/etc/resolv.conf`. `ndots: 2` кардинально сокращает паразитные запросы резолвера ко внутренним доменным суффиксам кластера. |
| `containers[].image` | Container | URL образа. Строго запрещено использовать тег `:latest`. Обязательно фиксировать стабильный семантический тег (например, `1.4.2`) или SHA256-дайджест. |
| `containers[].imagePullPolicy` | Container | `IfNotPresent` экономит сетевой трафик узлов. `Always` скачивает образ при каждом старте (по умолчанию для `:latest` или при отсутствии тега). `Never` использует только локальный кэш ноды. |
| `containers[].resources` | Container | `requests` (гарантия планировщика для шедулинга) и `limits` (жесткий потолок). Превышение `limits.memory` приводит к немедленному уничтожению контейнера процессом OOMKiller (Exit Code 137). Превышение `limits.cpu` приводит к троттлингу через механизмы Linux CFS Quota. |
| `containers[].securityContext` | Container | Изоляция процесса: `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, `capabilities.drop: ["ALL"]`. Предотвращает изменение бинарных файлов и повышение прав. |
| `containers[].lifecycle.preStop` | Container | Хук, выполняемый **до** отправки `SIGTERM`. Команда `sleep 15` компенсирует задержку обновления iptables/IPVS и контроллеров Ingress во всем кластере. |
| `containers[].startupProbe` | Container | Проверка первичного старта. Блокирует выполнение `readiness` и `liveness` проверок до успешного прохождения. Критична для сервисов с долгим запуском (Java/Spring, прогрев кэшей). |
| `containers[].readinessProbe` | Container | Проверка готовности обрабатывать трафик. При сбое Kubelet исключает под из `EndpointSlice` сервиса, не перезапуская процесс. Обязательна для бесперебойного RollingUpdate. |
| `containers[].livenessProbe` | Container | Проверка жизнеспособности процесса. При сбое контейнер перезапускается Kubelet. **Запрещено** проверять внешние зависимости (БД, брокеры), чтобы избежать каскадных перезапусков. |
| `initContainers` | Pod | Последовательно запускаемые контейнеры перед стартом основных. В K8s 1.29+ поддерживаются **Native Sidecars** (`initContainers` с `restartPolicy: Always`). |

### Метаданные, стандартные метки и аннотации

Следование спецификации стандартных меток Kubernetes (SIG-Apps) критично для централизованного мониторинга, трассировки и скриптов автоматизации.

```yaml
labels:
  app.kubernetes.io/name: frontend           # Имя приложения
  app.kubernetes.io/instance: frontend-prod  # Уникальный идентификатор инстанса
  app.kubernetes.io/version: "1.4.2"         # Версия сборки / коммита
  app.kubernetes.io/component: web           # Архитектурный компонент (web, worker, api)
  app.kubernetes.io/part-of: core-portal     # Родительская система / микросервисный контур
  app.kubernetes.io/managed-by: helm         # Инструмент управления (manual, helm, kustomize)
```

**Рекомендуемые аннотации:**
- `kubernetes.io/change-cause` — документирует причину изменения ревизии (отображается в выводе `kubectl rollout history`).
- `prometheus.io/scrape: "true"`, `prometheus.io/port`, `prometheus.io/path` — классический механизм обнаружения метрик для Prometheus.
- `deployment.kubernetes.io/revision` — системная аннотация с монотонно возрастающим номером текущей ревизии (управляется контроллером, только для чтения).

### Конфигурация: ConfigMap и Secret

Существует три основных метода доставки конфигурационных данных в поды:

1. **Массовое подключение через `envFrom`:**
   Все ключи ConfigMap или Secret экспортируются как переменные окружения.
   ```yaml
   envFrom:
   - configMapRef:
       name: app-config
   - secretRef:
       name: app-secrets
   ```

2. **Точечное внедрение через `env.valueFrom`:**
   Выборка отдельных ключей с возможностью переопределения имени переменной.
   ```yaml
   env:
   - name: DATABASE_HOST
     valueFrom:
       configMapKeyRef:
         name: app-config
         key: db-host
   - name: DATABASE_PASSWORD
     valueFrom:
       secretKeyRef:
         name: app-secrets
         key: db-pass
   ```

3. **Монтирование в виде томов (Volume Mounts):**
   Рекомендуемый метод для сложных конфигурационных файлов и сертификатов:
   ```yaml
   volumeMounts:
   - name: config-files
     mountPath: /etc/app/config
     readOnly: true
   volumes:
   - name: config-files
     configMap:
       name: app-config
   ```

**Архитектурное правило изменения конфигурации:** В Kubernetes изменение содержимого объекта `ConfigMap` или `Secret` **не модифицирует `spec.template`** объекта Deployment, а следовательно, **не инициирует автоматический Rollout**. Поды, использующие переменные окружения, продолжат работать со старыми значениями вплоть до перезапуска. Для гарантированного обновления применяются:
- Ручной перезапуск: `kubectl rollout restart deployment/<name>`.
- Паттерн хеш-аннотации в шаблоне пода (при изменении конфига в CI/CD обновляется аннотация `configmap-hash`, что меняет `spec.template` и триггерит Rollout). Детальный разбор см. в [Обновление и Rollout ConfigMap](../ConfigMap/update_and_rollout.md).

## 3. Практические сценарии и конфигурация

### Валидация манифеста перед применением

Статическая проверка манифестов исключает синтаксические ошибки и конфликты с политиками кластера до попадания в продакшен.

```bash
# 1. Локальная синтаксическая валидация без обращения к API-серверу
kubectl apply -f deployment.yaml --dry-run=client
# → deployment.apps/app-frontend created (dry run)

# 2. Серверная валидация (проверка схемы, полей и Admission Controllers: PSA, OPA, Kyverno)
kubectl apply -f deployment.yaml --dry-run=server
# → deployment.apps/app-frontend created (server dry run)

# 3. Детальный аудит различий желаемого и текущего состояния в кластере
kubectl diff -f deployment.yaml
# → Возвращает unified diff между текущим объектом в etcd и локальным файлом

# 4. Офлайн-валидация схемы через kubeconform (в пайплайнах CI/CD)
kubeconform -strict -summary -schema-location default deployment.yaml
# → deployment.yaml - Valid
```

### Бесперебойное обновление (Zero-Downtime Rolling Update)

Для обеспечения непрерывной доступности сервиса (0 секунд даунтайма) при релизе конфигурация RollingUpdate настраивается в строгом соответствии с формулой: `maxUnavailable: 0` и `maxSurge: 1`.

```yaml
spec:
  replicas: 4
  minReadySeconds: 20
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
```

**Механика процесса:**
1. Контроллер создает **один** новый под сверх лимита `replicas` (всего 5 подов в кластере).
2. Новый под стартует, проходит `startupProbe` и начинает опрашиваться `readinessProbe`.
3. После успешного ответа пробы готовности под удерживается в течение `minReadySeconds: 20`. Это предотвращает преждевременное удаление старых реплик, если сервис падает под нагрузкой через несколько секунд после старта.
4. Только после признания нового пода `Available` контроллер отправляет сигнал на завершение **одному** старому поду.
5. Процесс повторяется итеративно для всех реплик.

### Чистое завершение (Graceful Shutdown) и предотвращение ошибок 502/504

При удалении пода возникает сетевая гонка (race condition):
- `kube-apiserver` параллельно отправляет команду на удаление в `kubelet` и контроллеры `EndpointSlice`.
- Удаление IP-адреса пода из цепочек `iptables`/`IPVS` на всех рабочих узлах и обновление апстримов Ingress-контроллера занимает от 2 до 10 секунд.
- Если приложение завершит процесс немедленно по сигналу `SIGTERM`, клиенты продолжат получать ошибки `502 Bad Gateway` или `Connection Refused` на запросы, маршрутизируемые на старый IP.

Решение: внедрение хука `preStop` с задержкой и достаточного окна `terminationGracePeriodSeconds`.

```yaml
spec:
  terminationGracePeriodSeconds: 45
  containers:
  - name: web-app
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 15"]
```

**Последовательность шагов Kubelet:**
1. Pod переводится в статус `Terminating` и исключается из сервисных Endpoints.
2. Выполняется хук `preStop` (блокирует отправку сигналов на 15 секунд; за это время сеть кластера перестает направлять новые запросы на данный под).
3. Приложению отправляется `SIGTERM` — процесс закрывает существующие соединения (keep-alive drain).
4. Если приложение не завершилось за `terminationGracePeriodSeconds` (45с), ядро отправляет `SIGKILL`.
Подробный теоретический анализ см. в [Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md).

### Равномерное распределение подов (Topology Spread Constraints)

Для On-Premise инфраструктуры критично не допустить сосредоточения всех реплик приложения на одном физическом сервере или в одной стойке.

```yaml
spec:
  template:
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: "kubernetes.io/hostname"
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app.kubernetes.io/name: frontend
```

- `topologyKey: "kubernetes.io/hostname"` — распределяет поды строго по разным физическим нодам.
- `maxSkew: 1` — максимальная разница в числе подов между любыми двумя хостами не превышает 1.
- `whenUnsatisfiable: DoNotSchedule` — жесткое ограничение: если подходящего свободного узла нет, под останется в статусе `Pending`, но не нарушит топологию. Для мягкого режима используйте `ScheduleAnyway`.

### Таргетирование вычислительных узлов (NodeSelector и Taints/Tolerations)

При наличии в кластере выделенных пулов серверов (например, высокопроизводительных узлов под веб-трафик или нод со специальными дисками) используются селекторы и толерантности:

```yaml
spec:
  template:
    spec:
      # Привязка только к нодам с соответствующей меткой
      nodeSelector:
        node-role.internal/workload: high-io

      # Разрешение запускаться на нодах с наложенным taint
      tolerations:
      - key: "dedicated"
        operator: "Equal"
        value: "frontend-pool"
        effect: "NoSchedule"

      # Запрет размещения подов на одном хосте через anti-affinity
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchLabels:
                  app.kubernetes.io/name: frontend
              topologyKey: "kubernetes.io/hostname"
```

Детальный разбор планировщика см. в [Affinity и Anti-Affinity](../../Scheduling/affinity.md) и [Taints и Tolerations](../../Scheduling/taints_and_tolerations.md).

### Подготовка окружения и миграции (initContainers и Native Sidecars)

Секция `initContainers` позволяет выполнять подготовительные действия (проверка доступности СУБД, применение миграций) до запуска основного приложения.

```yaml
spec:
  template:
    spec:
      initContainers:
      - name: wait-for-db
        image: registry.internal/network-tools:1.0.0
        command: ['sh', '-c', 'until nc -z -v -w5 db.internal 5432; do echo waiting for db; sleep 2; done;']
        resources:
          requests: { cpu: "50m", memory: "64Mi" }
          limits: { cpu: "100m", memory: "64Mi" }

      # Native Sidecar (начиная с Kubernetes 1.29+ / GA в 1.30+)
      # Запускается до основного контейнера и работает параллельно на протяжении жизни пода
      - name: log-collector-sidecar
        image: registry.internal/fluent-bit:3.0.0
        restartPolicy: Always
        resources:
          requests: { cpu: "50m", memory: "128Mi" }
          limits: { cpu: "100m", memory: "128Mi" }
```

> **Важно:** При параллельном запуске нескольких реплик `Deployment` запуск миграций БД внутри обычного `initContainers` может вызвать состояние гонки (race condition). Для миграций предпочтительно использовать отдельный `Job` или реализовывать распределенные блокировки (advisory locks) на уровне СУБД. См. [Паттерны Sidecar](../Pod/pod_sidecar_patterns.md).

## 4. Операции и команды

Сводная таблица ключевых команд системного администратора и инженера SRE для управления жизненным циклом манифестов Deployment:

| Задача | Команда | Ожидаемый результат / Назначение |
| :--- | :--- | :--- |
| **Генерация каркаса** | `kubectl create deployment web --image=registry.internal/app:1.0 --dry-run=client -o yaml` | Выводит валидный манифест в stdout без создания объекта в кластере. |
| **Инспекция схемы** | `kubectl explain deployment.spec.strategy.rollingUpdate` | Интерактивная документация конкретных полей схемы API из кластера. |
| **Декларативный деплой** | `kubectl apply -f deployment.yaml` | Создание или обновление объекта в etcd. |
| **Server-Side Apply** | `kubectl apply --server-side -f deployment.yaml --field-manager=sre-team` | Атомарный учет владения полями, исключает конфликты при нескольких контроллерах. |
| **Сравнение изменений** | `kubectl diff -f deployment.yaml` | Просмотр diff перед применением конфигурации. |
| **Обновление образа** | `kubectl set image deployment/app-frontend web-app=registry.internal/frontend:1.4.3` | Патчит образ контейнера и инициирует немедленный Rollout. |
| **Фиксация причины** | `kubectl annotate deployment/app-frontend kubernetes.io/change-cause="Релиз 1.4.3"` | Добавляет аннотацию причины в текущую ревизию. |
| **Статус выкатки** | `kubectl rollout status deployment/app-frontend --timeout=120s` | Блокирует терминал до успешного завершения rollout (гейт для CI/CD). |
| **История ревизий** | `kubectl rollout history deployment/app-frontend` | Список всех сохраненных ревизий с текстом `CHANGE-CAUSE`. |
| **Инспекция ревизии** | `kubectl rollout history deployment/app-frontend --revision=2` | Детальный просмотр спецификации шаблона пода конкретной ревизии. |
| **Откат к предыдущей** | `kubectl rollout undo deployment/app-frontend` | Возврат к шаблону пода предыдущей ревизии. |
| **Откат к конкретной** | `kubectl rollout undo deployment/app-frontend --to-revision=1` | Принудительный откат на указанную версию ревизии. |
| **Пауза выкатки** | `kubectl rollout pause deployment/app-frontend` | Приостановка текущего обновления для внесения дополнительных правок. |
| **Возобновление** | `kubectl rollout resume deployment/app-frontend` | Снятие паузы и продолжение процесса Rollout. |
| **Перезапуск подов** | `kubectl rollout restart deployment/app-frontend` | Плавный перезапуск без смены конфигурации (обновление ConfigMap/Secret). |
| **Масштабирование** | `kubectl scale deployment/app-frontend --replicas=5` | Изменение количества запущенных подов без создания новой ревизии. |

Детальное руководство по операциям жизненного цикла см. в [Управление жизненным циклом Deployment](./lifecycle_management.md).

## 5. Диагностика и устранение неполадок

### Матрица типовых сбоев уровня манифеста

| Симптом / Ошибка | Первопричина в манифесте | Команда диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **`ProgressDeadlineExceeded`** | Обновление зависло дольше `progressDeadlineSeconds`: падают пробы `readinessProbe`, нехватка ресурсов или `ImagePullBackOff`. | `kubectl describe deploy <name>` (блок Conditions) | Устранить причину сбоя новых подов или выполнить `kubectl rollout undo`. |
| **`CrashLoopBackOff`** | Неверные параметры запуска (`command`, `args`), ошибка приложения, отсутствие прав на чтение конфигов. | `kubectl logs <pod> --previous` | Проверить аргументы контейнера, переменные окружения и права доступа. |
| **`OOMKilled` (Exit 137)** | Потребление памяти превысило `resources.limits.memory`. | `kubectl describe pod <pod> \| grep -A3 Last\ State` | Увеличить `limits.memory` в манифесте; устранить утечки памяти в коде. |
| **`CreateContainerConfigError`** | В `envFrom` или `volumeMounts` указан несуществующий `ConfigMap` или `Secret`, либо неверный ключ `keyRef`. | `kubectl get events --field-selector involvedObject.name=<pod>` | Создать недостающий ресурс или исправить имена в секциях `configMapRef`/`secretRef`. |
| **`CreateContainerError`** | Включен `readOnlyRootFilesystem: true`, но приложение пытается писать логи или PID-файлы в `/tmp` или `/run` без томов. | `kubectl describe pod <pod>` | Смонтировать `emptyDir` в каталоги записи (`/tmp`, `/var/run`, `/var/log`). |
| **`ImagePullBackOff`** | Опечатка в имени/теге образа, либо для частного реестра не настроен `imagePullSecrets`. | `kubectl describe pod <pod> \| grep -E "(Failed\|BackOff)"` | Проверить тег в `image`; добавить секрет реестра в `imagePullSecrets`. |
| **`Field is immutable`** | Попытка изменить поле `spec.selector` через `kubectl apply`. | `kubectl apply -f deployment.yaml` (возвращает 422 Unprocessable) | Селектор неизменяем. Требуется удалить Deployment (`--cascade=orphan`) и пересоздать заново. |
| **Под завис в `Pending`** | Запрошенные `requests.cpu`/`memory` превышают емкость узлов, либо конфликт `topologySpreadConstraints` / `nodeSelector`. | `kubectl describe pod <pod> \| grep -A5 Events` | Скорректировать `requests`; проверить наличие подходящих нод без taints. |
| **Зависание при квотах** | `maxSurge: 1` требует создания дополнительного пода, на который не хватает ресурсов в `ResourceQuota`. | `kubectl describe quota -n <namespace>` | Уменьшить `maxSurge` до `0` (с `maxUnavailable: 1`) или запросить расширение квоты. |

### Быстрый диагностический сценарий для администратора

```bash
# 1. Проверка условий и статуса прогресса Deployment
kubectl describe deployment app-frontend | grep -A8 Conditions
# → Type           Status  Reason
# → Progressing    True    NewReplicaSetAvailable
# → Available      True    MinimumReplicasAvailable

# 2. Выявление новых и старых ReplicaSet
kubectl get rs -l app.kubernetes.io/name=frontend
# → NAME                      DESIRED   CURRENT   READY   AGE
# → app-frontend-7f6f8d6f5d   3         3         3       5m   ← Актуальный
# → app-frontend-5c6b7c8d9e   0         0         0       2d   ← Старый (архив)

# 3. Инспекция сбойных подов конкретной ревизии
kubectl get pods -l app.kubernetes.io/name=frontend --field-selector=status.phase!=Running

# 4. Просмотр логов предыдущего аварийного завершения
kubectl logs -l app.kubernetes.io/name=frontend --previous --tail=100
```

Полный алгоритм анализа сложных сбоев см. в **[Устранение неполадок Deployment](./troubleshooting.md)** и **[Сложные сценарии диагностики](./advanced_troubleshooting_scenarios.md)**.

## 6. Лучшие практики (Best Practices)

### 1. Принцип неизменяемости артефактов (Immutability)
- **Строгий запрет тега `:latest`:** Использование `:latest` нарушает воспроизводимость среды, кэширует непредсказуемые слои на узлах и делает невозможным откат ревизий.
- **Фиксация тегов:** Используйте семантическое версионирование (`app:1.4.2`) или SHA256-дайджесты образов (`app@sha256:...`) для критических сред.

### 2. Детерминированное управление ресурсами (QoS)
- **Обязательные requests и limits:** Никогда не выпускайте в продакшен манифесты без блока `resources`.
- **Гарантированная память (Guaranteed QoS):** Для критичных сервисов устанавливайте `requests.memory == limits.memory`. Это исключает внезапное завершение процесса по OOM при нехватке физической памяти на узле.
- **Осторожность с limits по CPU:** В высоконагруженных системах с высокими требованиями к SLA по latency жесткие `limits.cpu` могут вызывать микрозадержки из-за троттлинга CFS Quota (CFS throttled time). Рассматривайте вариант установки только гарантированных `requests.cpu` без верхнего лимита либо устанавливайте лимит с двукратным запасом.
- **Лимиты временного хранилища:** Ограничивайте `ephemeral-storage` (через requests/limits и `sizeLimit` в `emptyDir`), чтобы логи или временные файлы приложения не переполнили диск хоста (`DiskPressure`). См. [Управление ресурсами и QoS](../../Scheduling/qos_limit_and_requests.md).

### 3. Комплексная безопасность (Hardening by Design)
- **Pod Security Standards (Restricted):**
  - Запрет root: `runAsNonRoot: true`, явные `runAsUser` и `runAsGroup` (UID > 10000).
  - Запрет эскалации привилегий: `allowPrivilegeEscalation: false`.
  - Защита файловой системы: `readOnlyRootFilesystem: true`. Все временные каталоги (`/tmp`, кэш) монтируйте как отдельные `emptyDir`.
  - Сброс привилегий ядра: `capabilities: drop: ["ALL"]`.
  - Системные вызовы: `seccompProfile.type: RuntimeDefault`.
  - Защита API K8s: `automountServiceAccountToken: false`.
  Подробнее: [Hardening манифестов Deployment](./deployment_security_hardening.md) и [Pod Security Context](../../Security/pod_security_context.md).

### 4. Корректная триада проб (Health Checks)
- **`readinessProbe`:** Обязательна для каждого рабочего контейнера. Без нее RollingUpdate не знает, когда новый под готов принимать трафик, и удаляет старые поды до фактического старта приложения.
- **`startupProbe`:** Обязательна для приложений, время старта которых превышает 10 секунд. Предотвращает убийство приложения пробой `livenessProbe` до окончания инициализации.
- **`livenessProbe`:** Не должна выполнять тяжелых операций и проверять внешние сервисы (базы данных, очереди). Ее задача — детектировать внутренний deadlock процесса. См. [Пробы в Kubernetes](../probes.md).

### 5. Безопасные параметры Rollout
- **`minReadySeconds`:** Всегда выставляйте `15–60` секунд. Это дает защитный интервал для обнаружения крашей при старте под трафиком.
- **`revisionHistoryLimit`:** Устанавливайте `3–5`. Значение по умолчанию (10) создает избыточную нагрузку на метаданные кластера в `etcd`.
- **Защита от сбоев оборудования:** Комбинируйте `topologySpreadConstraints` или `podAntiAffinity` с объектом [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md), чтобы гарантировать доступность сервиса при плановом дренаже нод (`kubectl drain`).

### 6. Документирование и CI/CD проверки
- **Change Cause:** Фиксируйте понятные комментарии через аннотацию `kubernetes.io/change-cause`.
- **Автоматизированный аудит:** Включайте валидаторы `kubeconform` и линтеры безопасности в пайплайны CI/CD. Чеклист готовности см. в [Production Checklist](./production_checklist.md).

## 7. Дополнительная информация

### Ограничения и особенности архитектуры (Edge Cases)

1. **Неизменяемость селектора (`spec.selector`):** Поле неизменяемо с момента создания объекта. Если требуется изменить метки селектора, единственный путь — удаление Deployment с ключом `--cascade=orphan` (чтобы не убить запущенные поды) и повторный `apply` нового манифеста.
2. **Ограничение `restartPolicy`:** В Deployment разрешено использовать только `restartPolicy: Always`. Если требуется запустить разовую задачу с завершением процесса, используйте `Job` или `CronJob`.
3. **Обновление ConfigMap/Secret без Rollout:** Модификация существующих объектов конфигурации не инициирует обновление подов. Для доставки новых конфигураций без даунтайма требуется перезапуск через `kubectl rollout restart` или автоматизация через операторы (например, Stakater Reloader) либо версионирование имён конфигов.
4. **Поведение при `replicas: 0`:** Обновление шаблона пода при нулевом количестве реплик завершается мгновенно, так как поды не создаются. При последующем увеличении `replicas` сразу запустятся поды новой ревизии.
5. **Дедлок квот при `maxSurge`:** Если в `ResourceQuota` пространства имен исчерпан лимит CPU или памяти, создание дополнительного пода при `maxSurge: 1` будет заблокировано Admission Controller. Обновление зависнет до вмешательства администратора.
6. **Конфликт HPA и поля `spec.replicas`:** Если для Deployment настроен Horizontal Pod Autoscaler, удалите поле `spec.replicas` из базового манифеста в Git (или настройте игнорирование изменений в CD-инструменте), иначе каждый коммит будет сбрасывать масштабирование HPA до фиксированного значения.
7. **Нюансы монтирования `subPath`:** Файлы из `ConfigMap`/`Secret`, смонтированные в контейнер с флагом `subPath`, **не обновляются автоматически** Kubelet при изменении источника (ограничение монтирования томов ядра Linux).
8. **Арифметика округления:** При расчете процентных долей `maxSurge` всегда округляется вверх до целого числа, а `maxUnavailable` — всегда вниз. При малом числе реплик (например, 2 или 3) рекомендуется указывать абсолютные целочисленные значения для исключения неожиданного поведения.

### См. также

- [Kubernetes Deployment: Обзор](./index.md) — концепции контроллера, архитектура и жизненный цикл.
- [Управление жизненным циклом Deployment](./lifecycle_management.md) — команды отката, паузы, ревизии и rollover.
- [Устранение неполадок Deployment](./troubleshooting.md) — углубленный траблшутинг зависших и аварийных обновлений.
- [Сложные сценарии диагностики](./advanced_troubleshooting_scenarios.md) — разбор редких и комплексных инцидентов.
- [Hardening манифестов Deployment](./deployment_security_hardening.md) — детальная настройка безопасности и PSA Restricted.
- [Production Checklist Deployment](./production_checklist.md) — чеклист готовности манифеста к промышленной эксплуатации.
- [Продвинутые стратегии отката](./advanced_rollback_strategies.md) — безопасные откаты при нарушении миграций данных.
- [Обновление и Rollout ConfigMap](../ConfigMap/update_and_rollout.md) — доставка изменений конфигураций в поды.
- [Пробы в Kubernetes](../probes.md) — детальный тюнинг проверок startup, readiness и liveness.
- [QoS, Limits и Requests](../../Scheduling/qos_limit_and_requests.md) — механизмы Linux cgroups, CFS Quota и OOMKiller.
- [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md) — защита сервиса при обслуживании узлов кластера.