# Обновление и плавный перезапуск (Rollout) ConfigMap

**Актуально для:** Kubernetes 1.28–1.33+

## Определения

**Обновление ConfigMap (ConfigMap Update)** — процесс внесения изменений в манифест или спецификацию данных объекта `kind: ConfigMap` через Kubernetes API (`kubectl apply`, `kubectl patch`, `kubectl edit` или вызовы REST API). Поведение системы при обновлении строго зависит от способа потребления данных рабочей нагрузкой (тома, переменные окружения, аргументы командной строки).

**Плавный перезапуск (Rollout Restart)** — управляемый процесс последовательного пересоздания подов (Pods) контроллером рабочей нагрузки (Deployment, StatefulSet, DaemonSet). Реализуется путем обновления аннотаций в шаблоне пода (`spec.template`), что порождает новую ревизию контроллера и запускает стратегию развертывания без прерывания обслуживания (Zero Downtime).

**Задержка распространения (Propagation Delay)** — временной интервал между успешной фиксацией обновленного объекта ConfigMap в распределенном хранилище `etcd` через `kube-apiserver` и фактическим появлением обновленных данных на файловой системе контейнера внутри пода.

**Горячая перезагрузка (Hot Reload)** — способность процесса внутри контейнера динамически перечитывать файлы конфигурации без завершения и перезапуска основного процесса (PID 1). Реализуется через подписку на события файловой системы ядра Linux (`inotify`), периодический опрос (polling) или получение внешнего триггера (POSIX-сигнал `SIGHUP`, локальный HTTP-эндпоинт `/-/reload`).

**Ревизия шаблона пода (Pod Template Revision)** — неизменяемый снимок спецификации шаблона пода (`spec.template`) контроллера. Для Deployment каждой ревизии соответствует дочерний объект `ReplicaSet`, для StatefulSet и DaemonSet — объект `ControllerRevision`. Изменение данных ConfigMap не меняет шаблон пода и автоматически ревизию не создает.

**Окно расхождения конфигураций (Config Skew Window)** — период времени при обновлении кластера или рабочей нагрузки, в течение которого реплики одного и того же приложения параллельно работают с разными версиями конфигурации (старой и новой). Возникает из-за асинхронности циклов синхронизации Kubelet на узлах либо во время поэтапного создания подов новой ревизии.

**Атомарная замена символических ссылок (Atomic Symlink Swap)** — механизм подсистемы Kubelet Volume Manager, при котором файлы смонтированного тома ConfigMap обновляются путем создания временного теневого каталога данных с таймштампом и мгновенной атомарной подмены символической ссылки `..data` через системный вызов `renameat()`.

**Хеш конфигурации (Configuration Checksum / Hash)** — вычисленная контрольная сумма (например, SHA-256) содержимого конфигурационного файла или объекта ConfigMap, внедряемая в аннотации шаблона пода (`spec.template.metadata.annotations`) либо в имя ресурса. Позволяет транслировать изменение внешнего конфига в мутацию шаблона пода.

**Бюджет сбоев подов (PodDisruptionBudget, PDB)** — объект политики Kubernetes API (`policy/v1`), ограничивающий количество одновременно недоступных реплик приложения при добровольных сбоях (eviction API: `kubectl drain`, обновление узлов, выселение подов).

**Контроллерная ревизия (ControllerRevision)** — ресурс API (`apps/v1`), хранящий неизменяемые исторические снимки состояния спецификации для контроллеров `StatefulSet` и `DaemonSet`, аналогичный по назначению объектам `ReplicaSet` для `Deployment`.

---

## Архитектура и принципы работы

### Механизм синхронизации Kubelet и Volume Manager

Синхронизация данных смонтированных ConfigMap на рабочих узлах выполняется фоновым демоном `kubelet` через внутренний компонент **Volume Manager**.

```
  ┌─────────────────────────────────────────────────────────────┐
  │                 Control Plane (etcd + API)                  │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                   Watch / Periodic Sync / Cache
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                      Kubelet Node                           │
  │  ┌───────────────────────────────────────────────────────┐  │
  │  │ Volume Manager (DesiredStateOfWorld / ActualState)    │  │
  │  └───────────────────────────┬───────────────────────────┘  │
  │                              │                              │
  │          Атомарная замена:   │ renameat()                   │
  │          ..data_tmp  ───────►│ ..data (symlink swap)        │
  │                              │                              │
  │                              ▼                              │
  │       /var/lib/kubelet/pods/<pod-uid>/volumes/.../          │
  │          ├── ..2026_10_13_12_00_00.123456789 (dir)          │
  │          ├── ..data ──► ..2026_10_13_12_00_00.123456789     │
  │          └── app.conf ──► ..data/app.conf                   │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                  Контейнер (Mount Namespace)
                                 ▼
                     /etc/config/app.conf
```

Kubelet отслеживает изменения объектов в API-сервере согласно параметру `configMapAndSecretChangeDetectionStrategy` в файле конфигурации `KubeletConfiguration`:
1. **Watch (по умолчанию):** Kubelet открывает долгоживущее HTTP/2-соединение Watch к API-серверу на каждый потребляемый ConfigMap. Изменения приходят незамедлительно в виде событий.
2. **Cache:** Kubelet кэширует объекты локально, обновляя кэш с периодичностью TTL (по умолчанию 1 минута).
3. **Get:** Kubelet выполняет прямой запрос `GET` к API-серверу при каждом запуске цикла синхронизации подов.

Несмотря на быструю доставку событий в стратегии `Watch`, фактическая перезапись директории на локальном диске узла инициируется только во время периодического цикла сверки подов Kubelet (параметр `syncFrequency`, по умолчанию 60 секунд), к которому добавляется псевдослучайный джиттер (коэффициент до 0.5):
$$T_{kubelet} = \text{syncFrequency} \times (1 \pm \text{jitter})$$

**Зависимость поведения от способа подключения конфигурации:**

| Способ подключения | Автоматическое обновление на диске/в памяти | Механизм доставки | Требуемое действие для применения |
| :--- | :--- | :--- | :--- |
| **Тома (Volumes / Projected)** | **Да** | Atomic Symlink Swap (`..data`) | Hot Reload процесса ИЛИ рестарт пода |
| **Переменные окружения (`env`, `envFrom`)** | **Нет** | Передача в `environ` при вызове `execve()` | Полное пересоздание пода |
| **Аргументы командной строки (`args: ["$(VAR)"]`)** | **Нет** | Разворачивание Kubelet до запуска PID 1 | Полное пересоздание пода |
| **Монтирование через `subPath` / `subPathExpr`** | **Нет** | Прямой Bind Mount на конкретный inode | Полное пересоздание пода |

> **Важно:** Монтирование через `subPath` связывает контейнер с конкретным inode файла на момент старта. Когда Kubelet выполняет замену симлинка каталога, inode смонтированного файла внутри контейнера остается прежним. Автоматическое обновление через `subPath` невозможно на уровне ядра Linux.

#### Низкоуровневая структура каталога и специфика inotify

При монтировании тома ConfigMap Kubelet создает в каталоге следующую структуру:
* `..2026_10_13_10_00_00.000000000` — директория с фактическими файлами конфигурации;
* `..data` — символическая ссылка, указывающая на актуальную директорию с таймштампом;
* `app.conf` — символическая ссылка, указывающая на `..data/app.conf`.

При получении обновления Kubelet:
1. Создает новый каталог `..2026_10_13_10_05_00.999999999` и записывает туда новые файлы.
2. Создает временную символическую ссылку `..data_tmp`, указывающую на новый каталог.
3. Выполняет атомарный системный вызов ядра `renameat("..data_tmp", "..data")`.
4. Удаляет старую директорию после успешного переключения.

**Критическая особенность для Hot Reload:**
Файл `app.conf` **не модифицируется напрямую** (событие ядра `IN_MODIFY` на файле `app.conf` не генерируется). Происходит удаление и замена ссылки `..data` (события `IN_MOVED_TO`, `IN_CREATE` или `IN_DELETE_SELF` на уровне каталога). Приложения и утилиты, отслеживающие только `IN_MODIFY` на конкретном целевом файле, не увидят обновление. Для корректной работы монитор обязан отслеживать саму смонтированную директорию или симлинк `..data`.

#### Проблема открытых файловых дескрипторов (Inode Caching)

Если процесс приложения открыл файл конфигурации (`open()`) при старте и держит файловый дескриптор открытым без повторного чтения с диска, ядро Linux сохраняет доступ к старому inode даже после того, как Kubelet удалил старый каталог. Для применения изменений процесс обязан выполнить повторное открытие файла (`close()` + `open()`) либо мапить файл в память с регулярной проверкой его валидности.

---

### Почему изменение ConfigMap не запускает Rollout автоматически

Архитектура Kubernetes построена на независимых контроллерах и концепции согласования желаемого состояния (Reconciliation Loop).

1. Контроллеры рабочих нагрузок (`Deployment`, `StatefulSet`, `DaemonSet`) отслеживают исключительно поле `spec.template` (шаблон пода).
2. Спецификация пода ссылается на ConfigMap по внешнему имени (`name: app-config`), не сохраняя внутри шаблона хеш или тело данных.
3. При изменении данных внутри объекта `ConfigMap` сам объект в etcd обновляется (инкрементируется его собственный `metadata.resourceVersion`), однако `spec.template` контроллера остается байт-в-байт неизменным.
4. Контроллер рабочей нагрузки не получает события изменения шаблона пода, поэтому:
   * Не создается новый объект `ReplicaSet` (для Deployment);
   * Не создается новый объект `ControllerRevision` (для StatefulSet/DaemonSet);
   * Кластер считает текущее состояние подов соответствующим декларации.

Пока оператор или автоматизированная система явно не инициируют мутацию шаблона пода (через `kubectl rollout restart`, смену хеша в аннотации или сторонний оператор вроде Reloader), поды продолжат работать без перезапуска.

---

### Особенности обновления по типам рабочих нагрузок

Механика реакции на обновление конфигурации различается в зависимости от контроллера:

| Контроллер | Механизм ревизий | Порядок обновления подов | Особенности обновления конфигурации |
| :--- | :--- | :--- | :--- |
| **Deployment** | `ReplicaSet` | Параллельно/пакетно по лимитам `maxSurge` и `maxUnavailable` | Быстрый выкат. При откате возвращается старый ReplicaSet, но если ConfigMap был перезаписан in-place, откат Deployment вернет старый код с новым (несовместимым) конфигом. |
| **StatefulSet** | `ControllerRevision` | Строго по индексам (от $N-1$ к 0) | Поддерживает канареечную раскатку через `spec.updateStrategy.rollingUpdate.partition`. Каждый под ждет полной готовности (Ready) перед переходом к следующему. |
| **DaemonSet** | `ControllerRevision` | По одному поду на узле | `maxSurge` недоступен (на одном узле не может быть запущено две реплики одного DaemonSet без специальных настроек). Только `maxUnavailable`. |
| **Job / CronJob** | Отсутствует | Поды создаются один раз до завершения | Не поддерживают Rollout. Изменения ConfigMap влияют только на вновь создаваемые Job. Работающие Job завершаются со старой конфигурацией. |

---

### Полная задержка применения конфигурации (End-to-End Latency)

Полная сквозная задержка $T_{total}$ доставки изменений в приложение через монтирование тома складывается из последовательных фаз:

$$T_{total} = T_{api} + T_{kubelet} + T_{cache} + T_{detect} + T_{app} + T_{rollout}$$

1. $T_{api}$ — фиксация транзакции в etcd API-сервером: обычно $< 50$ мс.
2. $T_{kubelet}$ — периодический цикл Kubelet Volume Manager: от 0 до 60 секунд (по умолчанию `syncFrequency = 60s`) плюс джиттер (до 30 секунд). Суммарно: **60–90 секунд**.
3. $T_{cache}$ — задержка локального кэша Kubelet (если активен режим `Cache`): до 60 секунд. При режиме `Watch` равна 0.
4. $T_{detect}$ — время обнаружения изменения приложением:
   * Для `inotify`: $< 10$ мс;
   * Для интервального опроса (polling): $0 \dots T_{poll}$ (например, 5–15 секунд).
5. $T_{app}$ — время валидации и инициализации конфигурации приложением: от 100 мс до нескольких секунд.
6. $T_{rollout}$ — если задействован Rollout Restart, к задержке добавляется время запуска новых подов:
   $$T_{rollout} = T_{schedule} + T_{image\_pull} + T_{startupProbe} + T_{readinessProbe} + T_{graceful\_shutdown}$$

**Вывод для SRE:** при монтировании томов с Hot Reload расчетное время ожидания применения конфигурации на всех узлах кластера составляет **не менее 60–90 секунд**. Любые автоматизированные пайплайны валидации должны учитывать этот тайминг перед проверкой статуса.

---

### Синхронность обновления и окно расхождения конфигураций (Config Skew Window)

Поскольку Kubelet на каждом узле кластера запускает цикл синхронизации независимо в собственное случайное время, обновление файлов томов происходит **неодновременно**.

```
Узел 1: [--- Kubelet Sync ---] ──► Том обновлен (v2) ──► Hot Reload
Узел 2: [-------- Ожидание цикла --------] ──────► Том обновлен (v2)
Узел 3: [--- Ожидание цикла ---] ────────► Том обновлен (v2)
          ▲
          │ Окно расхождения (Config Skew Window):
          │ Реплики на Узле 1 уже отдают логику v2,
          │ а реплики на Узлах 2 и 3 продолжают работать по v1.
```

В течение окна расхождения система находится в состоянии частичного обновления.

**Требования к проектированию конфигураций в SRE:**
1. **Принцип совместимости N-1 / N+1:** Любое изменение структуры файла конфигурации (переименование полей, удаление параметров, добавление обязательных секций) должно быть обратно совместимо. Приложение версии v1 обязано корректно работать с данными v2, а приложение v2 — не падать при чтении данных v1.
2. **Атомарность ключей:** Если два параметра взаимосвязаны (например, `DB_POOL_SIZE` и `DB_MAX_OVERFLOW`), они обязаны находиться в одном ConfigMap, иначе приложение рискует получить частично рассинхронизированный контекст.
3. **Безопасная смена сетевых адресов:** Изменение портов, эндпоинтов и токенов авторизации должно проводиться в два этапа: сначала добавление поддержки нового значения во все сервисы, и только после полной раскатки — переключение трафика.

---

## Практические сценарии

### Сценарий 1: Горячая перезагрузка через Native Sidecar (K8s 1.29+, GA v1.33)

**Контекст:** Приложение поддерживает перезагрузку конфигурации без рестарта контейнера по локальному HTTP-запросу `POST /-/reload` или сигналу `SIGHUP` (например, Nginx, Prometheus, Envoy, Alertmanager).
**Требования:** Kubernetes 1.29+ (Native Sidecars включены по умолчанию; в 1.33+ переведены в GA). Сайдкар объявляется в блоке `initContainers` со спецификацией `restartPolicy: Always`.

#### Манифест развертывания

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dynamic-app-config
  namespace: production
data:
  app.conf: |
    server_port: 8080
    log_level: info
    worker_connections: 1024
    cache_enabled: true
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dynamic-app
  namespace: production
  labels:
    app.kubernetes.io/name: dynamic-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app.kubernetes.io/name: dynamic-app
  template:
    metadata:
      labels:
        app.kubernetes.io/name: dynamic-app
    spec:
      shareProcessNamespace: true # Требуется для отправки сигналов SIGHUP между контейнерами пода
      initContainers:
      - name: configmap-reloader
        image: jimmidyson/configmap-reload:v0.14.0
        imagePullPolicy: IfNotPresent
        restartPolicy: Always # Ключевой параметр Native Sidecar: контейнер работает весь жизненный цикл пода
        args:
        - --volume-dir=/etc/config
        - --webhook-url=http://127.0.0.1:8080/-/reload
        - --webhook-method=POST
        - --webhook-status-code=200
        resources:
          limits:
            cpu: 100m
            memory: 64Mi
          requests:
            cpu: 10m
            memory: 16Mi
        volumeMounts:
        - name: config-volume
          mountPath: /etc/config
          readOnly: true
      containers:
      - name: application
        image: my-repo/web-service:v2.4.0
        ports:
        - containerPort: 8080
          name: http
        resources:
          limits:
            cpu: 500m
            memory: 512Mi
          requests:
            cpu: 100m
            memory: 128Mi
        volumeMounts:
        - name: config-volume
          mountPath: /etc/config
          readOnly: true
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
      volumes:
      - name: config-volume
        configMap:
          name: dynamic-app-config
          defaultMode: 0444
```

#### Пошаговое применение и валидация

```bash
# 1. Применение манифеста
kubectl apply -f dynamic-app.yaml
# → configmap/dynamic-app-config created
# → deployment.apps/dynamic-app created

# 2. Проверка статуса запуска нативного сайдкара
kubectl get pods -n production -l app.kubernetes.io/name: dynamic-app
# → NAME                           READY   STATUS    RESTARTS   AGE
# → dynamic-app-6d8b9f78b4-4k9l1   2/2     Running   0          35s
# → dynamic-app-6d8b9f78b4-m8x2z   2/2     Running   0          35s
# → dynamic-app-6d8b9f78b4-p4v9q   2/2     Running   0          35s

# 3. Обновление значения в ConfigMap
kubectl patch configmap dynamic-app-config -n production --type merge -p '{"data":{"app.conf":"server_port: 8080\nlog_level: debug\nworker_connections: 2048\ncache_enabled: true\n"}}'
# → configmap/dynamic-app-config patched

# 4. Мониторинг логов sidecar-контейнера (фиксация события inotify и вызов вебхука)
kubectl logs -n production -l app.kubernetes.io/name: dynamic-app -c configmap-reloader --tail=10 -f
# → 2026/10/13 12:15:32 Watching directory: "/etc/config"
# → 2026/10/13 12:16:45 Updating: /etc/config/app.conf
# → 2026/10/13 12:16:45 Performing webhook request (POST): http://127.0.0.1:8080/-/reload
# → 2026/10/13 12:16:45 Webhook returned status code: 200

# 5. Проверка, что поды НЕ пересоздавались (возраст и restartCount не изменились)
kubectl get pods -n production -l app.kubernetes.io/name: dynamic-app
# → NAME                           READY   STATUS    RESTARTS   AGE
# → dynamic-app-6d8b9f78b4-4k9l1   2/2     Running   0          2m15s
# → dynamic-app-6d8b9f78b4-m8x2z   2/2     Running   0          2m15s
# → dynamic-app-6d8b9f78b4-p4v9q   2/2     Running   0          2m15s
```

---

### Сценарий 2: Автоматический перезапуск через хеширование (GitOps)

**Контекст:** Приложение потребляет конфигурацию через переменные окружения (`env`, `envFrom`) или не поддерживает Hot Reload файлов тома. Изменение конфигурации обязано инициировать стандартный Rolling Update без ручного вмешательства инженера.

#### 1. Паттерн аннотации Checksum в Helm

В шаблоне Deployment контрольная сумма содержимого файла ConfigMap внедряется непосредственно в `spec.template.metadata.annotations`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "app.fullname" . }}
  labels:
    app.kubernetes.io/name: {{ include "app.name" . }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "app.name" . }}
  template:
    metadata:
      annotations:
        # При изменении любого байта в configmap.yaml хеш изменится, что запустит Rolling Update
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
      labels:
        app.kubernetes.io/name: {{ include "app.name" . }}
    spec:
      containers:
      - name: app
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        envFrom:
        - configMapRef:
            name: {{ include "app.fullname" . }}
```

> **Важно:** Подробный разбор краевых случаев Helm (хеширование каталогов через `Files.Glob`, динамические шаблоны `tpl`, поведение `helm rollback`) описан в [Автоматический перезапуск подов (Restart on Change)](../../ToolsUtilities/Helm/templating/scenarios/restart_on_change.md).

#### 2. Паттерн Name Hashing в Kustomize

Kustomize решает задачу фундаментальнее на уровне генерации манифестов: директива `configMapGenerator` добавляет к имени объекта суффикс на основе хеш-суммы содержимого (Content-Addressable Storage).

**Файл `kustomization.yaml`:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

configMapGenerator:
- name: api-gateway-config
  files:
  - configs/gateway.conf
  - configs/routes.json

resources:
- deployment.yaml
```

**Файл `deployment.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-gateway
spec:
  replicas: 2
  selector:
    matchLabels:
      app: api-gateway
  template:
    metadata:
      labels:
        app: api-gateway
    spec:
      containers:
      - name: gateway
        image: nginx:1.27-alpine
        volumeMounts:
        - name: cfg
          mountPath: /etc/gateway
      volumes:
      - name: cfg
        configMap:
          name: api-gateway-config # Kustomize автоматически заменит на api-gateway-config-<hash>
```

**Результат генерации (`kustomize build .`):**
* Создается объект `ConfigMap/api-gateway-config-7b2m8hf7kd`;
* В `Deployment` поле `volume.configMap.name` переписывается на `api-gateway-config-7b2m8hf7kd`;
* При правке `gateway.conf` имя меняется на `api-gateway-config-9k4f2d11mz`. Для Kubernetes это изменение шаблона пода, которое чисто инициирует Rolling Update.
* **Главное преимущество:** Старый ConfigMap остается в кластере, поэтому откат (`kubectl rollout undo`) мгновенно вернет поды к рабочей старой конфигурации без сбоев.

---

### Сценарий 3: Автоматизация перезапуска через контроллер Reloader

**Контекст:** Инфраструктура использует прямой `kubectl apply` или оператор, где Helm/Kustomize хеширование недоступно, либо конфигурация формируется внешними операторами.
**Решение:** Развертывание открытого контроллера Reloader от Stakater. Контроллер слушает события Kubernetes API и при изменении ConfigMap/Secret патчит аннотацию в зависимых Deployment/StatefulSet/DaemonSet.

#### Манифест с аннотациями Reloader

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: microservice-cfg
  namespace: backend
data:
  DATABASE_TIMEOUT: "5s"
  MAX_CONNECTIONS: "50"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: microservice
  namespace: backend
  annotations:
    # Вариант 1: Автоматический перезапуск при изменении ЛЮБОГО связанного ConfigMap/Secret
    reloader.stakater.com/auto: "true"
    # Вариант 2: Точечный перезапуск только при изменении конкретного ConfigMap
    # configmap.reloader.stakater.com/reload: "microservice-cfg"
spec:
  replicas: 2
  selector:
    matchLabels:
      app: microservice
  template:
    metadata:
      labels:
        app: microservice
    spec:
      containers:
      - name: service
        image: internal-registry/service:1.9.1
        envFrom:
        - configMapRef:
            name: microservice-cfg
```

#### Проверка реакции Reloader

```bash
# 1. Изменение ConfigMap
kubectl patch configmap microservice-cfg -n backend --type merge -p '{"data":{"MAX_CONNECTIONS":"100"}}'
# → configmap/microservice-cfg patched

# 2. Просмотр логов контроллера Reloader
kubectl logs -n reloader-system -l app.kubernetes.io/name: reloader --tail=5
# → Changes detected in ConfigMap "microservice-cfg" in namespace "backend"
# → Updating Deployment "microservice" in namespace "backend"

# 3. Проверка изменения аннотаций в шаблоне Deployment
kubectl get deployment microservice -n backend -o jsonpath='{.spec.template.metadata.annotations}'
# → {"microservice-cfg.reloader.stakater.com/reloadedAt":"2026-10-13T12:20:15Z"}

# 4. Контроль прохождения Rolling Update
kubectl rollout status deployment/microservice -n backend --timeout=60s
# → deployment "microservice" successfully rolled out
```

> **Архитектурная ссылка:** Полное описание установки и RBAC-прав Reloader приведено в [Установка Reloader](../../ToolsUtilities/reloader/reloader_installation.md).

---

### Сценарий 4: Ручное управление жизненным циклом и CI/CD автоматизация (kubectl rollout)

**Контекст:** Выкат конфигурации в CI/CD-пайплайнах (GitLab CI, GitHub Actions, Jenkins) с императивным контролем готовности и автоматическим откатом при сбоях.

#### Промышленный bash-скрипт раскатки конфигурации

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

NAMESPACE="production"
DEPLOYMENT_NAME="order-processor"
CONFIG_FILE="k8s/order-config.yaml"
TIMEOUT="300s"

echo "=== [1/4] Валидация манифестов (Client Dry-Run) ==="
kubectl apply -f "${CONFIG_FILE}" -n "${NAMESPACE}" --dry-run=client
# → configmap/order-config validated (dry run)

echo "=== [2/4] Применение обновленной конфигурации ==="
kubectl apply -f "${CONFIG_FILE}" -n "${NAMESPACE}"
# → configmap/order-config configured

echo "=== [3/4] Инициация Rolling Update ==="
# Добавляет аннотацию kubectl.kubernetes.io/restartedAt=<UTC timestamp> в spec.template
kubectl rollout restart deployment/"${DEPLOYMENT_NAME}" -n "${NAMESPACE}"
# → deployment.apps/order-processor restarted

echo "=== [4/4] Ожидание завершения Rollout с таймаутом ${TIMEOUT} ==="
if ! kubectl rollout status deployment/"${DEPLOYMENT_NAME}" -n "${NAMESPACE}" --timeout="${TIMEOUT}"; then
    echo "ОШИБКА: Rollout завершился неуспешно или превысил таймаут! Инициируется аварийный откат..."
    
    # Сбор событий пода для отладки в логах CI/CD
    kubectl get events -n "${NAMESPACE}" --field-selector involvedObject.name="${DEPLOYMENT_NAME}" --sort-by='.lastTimestamp' | tail -n 10
    
    # Откат к предыдущей ревизии
    kubectl rollout undo deployment/"${DEPLOYMENT_NAME}" -n "${NAMESPACE}"
    kubectl rollout status deployment/"${DEPLOYMENT_NAME}" -n "${NAMESPACE}" --timeout=120s
    exit 1
fi

echo "УСПЕХ: Обновление конфигурации успешно применено ко всем репликам."
```

#### Просмотр и управление ревизиями

```bash
# История ревизий с указанием причин изменений
kubectl rollout history deployment/order-processor -n production
# → REVISION  CHANGE-CAUSE
# → 1         Initial deployment
# → 2         ConfigMap update (db pool resize)

# Детальный просмотр спецификации конкретной ревизии
kubectl rollout history deployment/order-processor -n production --revision=2

# Приостановка раскатки для анализа промежуточного состояния
kubectl rollout pause deployment/order-processor -n production
# → deployment.apps/order-processor paused

# Возобновление раскатки
kubectl rollout resume deployment/order-processor -n production
# → deployment.apps/order-processor resumed
```

---

### Сценарий 5: Поэтапная (канареечная) раскатка конфигурации

#### 1. Тюнинг стратегии RollingUpdate в Deployment

Для критичных сервисов, где недопустима даже кратковременная потеря производительности, стратегия RollingUpdate настраивается на упреждающий запуск новых реплик:

```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1        # Запускать не более 1 дополнительного нового пода единовременно
      maxUnavailable: 0  # Ни один старый под не завершается, пока новый не станет Ready
```

#### 2. Ступенчатое обновление конфигурации в StatefulSet (Partition)

Для приложений с сохранением состояния (StatefulSet) контроллер поддерживает поле `partition`. Все реплики с порядковым номером (ordinal) $\ge \text{partition}$ обновляются, а поды с индексом $< \text{partition}$ остаются на старой версии:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: cassandra
  namespace: databases
spec:
  replicas: 5 # Поды: cassandra-0, cassandra-1, cassandra-2, cassandra-3, cassandra-4
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 4 # Будет обновлен ТОЛЬКО cassandra-4 (тестовый канареечный под)
  template:
    metadata:
      annotations:
        config-hash: "a8f5b2..."
```

**Порядок раскатки через partition:**
1. Установить `partition: 4` и применить новый конфиг. Обновится только `cassandra-4`.
2. Провести аудит логов и метрик канареечного пода `cassandra-4`.
3. Уменьшить `partition: 2`. Обновятся поды `cassandra-3` и `cassandra-2`.
4. Установить `partition: 0` для завершения выката на поды `cassandra-1` и `cassandra-0`.

---

## Операции и команды

### Сводная таблица команд управления и валидации

| Команда | Описание | Ожидаемый результат / Вывод |
| :--- | :--- | :--- |
| `kubectl rollout restart deploy/<name> -n <ns>` | Инициация пересоздания подов через обновление аннотации `restartedAt` | `deployment.apps/<name> restarted` |
| `kubectl rollout status deploy/<name> -n <ns> --timeout=180s` | Блокирующее ожидание успешного переключения всех реплик | `deployment "<name>" successfully rolled out` |
| `kubectl rollout history deploy/<name> -n <ns>` | Вывод списка сохраненных ревизий ReplicaSet | Список `REVISION` и `CHANGE-CAUSE` |
| `kubectl rollout undo deploy/<name> -n <ns> --to-revision=N` | Откат шаблона пода к указанной ревизии | `deployment.apps/<name> rolled back` |
| `kubectl rollout pause deploy/<name> -n <ns>` | Заморозка текущей раскатки (фиксация текущих подов) | `deployment.apps/<name> paused` |
| `kubectl rollout resume deploy/<name> -n <ns>` | Возобновление выполнения стратегии обновления | `deployment.apps/<name> resumed` |

### Команды низкоуровневой проверки файловой системы и процессов

```bash
# 1. Проверка структуры симлинков в смонтированном каталоге
kubectl exec -n production deploy/my-app -c application -- ls -la /etc/config
# → lrwxrwxrwx 1 root root ..data -> ..2026_10_13_12_00_00.999
# → lrwxrwxrwx 1 root root app.conf -> ..data/app.conf

# 2. Проверка фактического целевого каталога симлинка ..data
kubectl exec -n production deploy/my-app -c application -- readlink -f /etc/config/..data
# → /etc/config/..2026_10_13_12_00_00.999

# 3. Проверка открытых файловых дескрипторов процесса (детект утечки старого inode)
kubectl exec -n production deploy/my-app -c application -- ls -l /proc/1/fd/
# → lr-x------ 1 root root 64 /proc/1/fd/3 -> /etc/config/..2026_10_13_11_00_00.111/app.conf (deleted)
# Если в выводе присутствует маркер "(deleted)" — процесс читает старый удаленный inode!

# 4. Проверка значений переменных окружения в работающем процессе
kubectl exec -n production deploy/my-app -c application -- strings /proc/1/environ | grep -E 'LOG_LEVEL|DB_PORT'
# → LOG_LEVEL=debug
# → DB_PORT=5432

# 5. Проверка статуса PDB перед началом массовых работ
kubectl get pdb -n production -o custom-columns=NAME:.metadata.name,MIN_AVAIL:.spec.minAvailable,ALLOWED:.status.disruptionsAllowed
# → NAME         MIN_AVAIL   ALLOWED
# → my-app-pdb   2           1
```

---

## Диагностика и устранение неполадок

### Алгоритм локализации проблемы (Decision Tree)

```
Изменение ConfigMap применено в API
                │
                ▼
Каким способом данные передаются в контейнер?
 ├── Переменные env/envFrom / subPath
 │        │
 │        ▼
 │   Поды перезапускались?
 │    ├── НЕТ ──► Выполнить: kubectl rollout restart deployment/<name>
 │    └── ДА  ──► Проверить ошибки синтаксиса: CreateContainerConfigError
 │
 └── Том (Volumes)
          │
          ▼
     Прошло > 90 секунд?
      ├── НЕТ ──► Ожидать завершения цикла Kubelet syncFrequency (60-90с)
      └── ДА  ──► Проверить файл на узле: readlink -f /etc/config/..data
                   │
                   ├── Файл на диске СТАРЫЙ ──► Проверить Kubelet логи узла
                   │                            (FailedMount / cache delay)
                   └── Файл на диске НОВЫЙ
                               │
                               ▼
                        Приложение обновило поведение?
                         ├── ДА  ──► Успешно (Hot Reload отработал)
                         └── НЕТ ──► Процесс держит старый inode (deleted)
                                     ИЛИ inotify слушает файл вместо ..data
```

### Сводная таблица типовых неисправностей

| Симптом | Первопричина | Метод диагностики | Пошаговое решение |
| :--- | :--- | :--- | :--- |
| **Файлы в томе обновились, но приложение использует старую конфигурацию** | Процесс закешировал файл при старте, либо дескриптор указывает на удаленный inode `(deleted)`. | Выполнить `ls -l /proc/<PID>/fd` внутри контейнера. Поиск маркера `(deleted)`. | Реализовать переоткрытие файла в приложении при получении `SIGHUP` / события `inotify`, либо выполнить `kubectl rollout restart`. |
| **Переменные окружения (`env`, `envFrom`) не обновились** | Переменные окружения фиксируются при старте процесса в ядре Linux (`execve`). | `kubectl exec <pod> -- env`. Сравнить с данными в ConfigMap. | Выполнить `kubectl rollout restart deployment/<name>`. Для автоматизации внедрить Helm Checksum или Reloader. |
| **Поды рестартуют (`restartCount` растет), но конфигурация прежняя** | Kubelet перезапускает контейнер внутри того же пода (CrashLoop), не пересоздавая под целиком. Шаблон пода не менялся. | Проверить возраст пода (`AGE`) и `RESTARTS`. Проверить `restartedAt` в шаблоне. | Инициировать пересоздание пода контроллером: `kubectl rollout restart deployment/<name>`. |
| **Rollout завис со статусом `Progressing: False`** | Новые поды не могут пройти `readinessProbe` из-за невалидного синтаксиса нового конфига. Сработал `progressDeadlineSeconds`. | `kubectl rollout status deploy/<name>`, `kubectl describe deploy/<name>`. | Исправить синтаксис в ConfigMap. Выполнить `kubectl rollout undo deploy/<name>` для разблокировки трафика. |
| **Rollout завис при `kubectl drain` узлов кластера** | `PodDisruptionBudget` (PDB) запрещает удаление старых подов (`allowedDisruptions: 0`), пока новые поды еще инициализируются. | `kubectl get pdb -n <ns>`, `kubectl describe pdb <name>`. Поле `DisruptionsAllowed`. | Согласовать `maxUnavailable` в Deployment с PDB. Принудительно задать `unhealthyPodEvictionPolicy: AlwaysAllow` (K8s 1.30+). |
| **Под переходит в `CreateContainerConfigError`** | ConfigMap с указанным именем отсутствует в namespace, либо в ключе допущена опечатка. | `kubectl describe pod <pod-name>`. Поиск события `Warning FailedMount`. | Создать отсутствующий ConfigMap или исправить имя ключа в `valueFrom.configMapKeyRef.name`. |
| **Ошибка API: `field is immutable`** | Попытка отредактировать ConfigMap, у которого установлен флаг `immutable: true`. | `kubectl get cm <name> -o yaml \| grep immutable`. | Неизменяемые объекты нельзя править in-place. Создать новый ConfigMap с новым именем (суффиксом) и переключить рабочую нагрузку. |
| **Файл, подключенный через `subPath`, не обновляется** | `subPath` монтирует жесткий bind mount на inode файла, отключая механизм Atomic Symlink Swap. | `grep subPath deployment.yaml`. Проверить symlinks в контейнере (они отсутствуют). | Отказаться от `subPath` в пользу монтирования всего каталога, либо использовать перезапуск подов через Helm checksum / Reloader. |
| **Всплеск OOMKilled во время Rolling Update** | Из-за `maxSurge: 25%` суммарное потребление памяти подами превысило емкость узла или лимиты `ResourceQuota`. | `kubectl describe node` (секция Allocated resources), события `OOMKilled`. | Установить `maxSurge: 0`, `maxUnavailable: 1` для строгого соблюдения квоты по памяти в процессе выката. |
| **Sidecar `configmap-reload` не может послать `SIGHUP`** | Контейнеры пода изолированы по PID namespace, либо процессы запущены от несовместимых UID/GID. | Логи sidecar: `kill: operation not permitted` или `process not found`. | Добавить `spec.shareProcessNamespace: true` в под. Настроить запуск sidecar от того же пользователя (UID), что и основное приложение. |

---

## Рекомендации и лучшие практики

### 1. Архитектурная матрица выбора стратегии

| Стратегия | Допустимый простой | Скорость применения | Сложность реализации | Рекомендуемый сценарий |
| :--- | :--- | :--- | :--- | :--- |
| **Hot Reload (тома + inotify)** | Строго 0 мс | 60–90 секунд | Средняя | Прокси-серверы (Nginx, Envoy), Prometheus, Alertmanager, приложения с развитым HTTP API управления. |
| **Rolling Update (Helm Checksum)** | 0 мс (при `maxUnavailable: 0`) | Время старта подов | Низкая | Стандартные микросервисы, приложения на Spring Boot, Go, Node.js, использующие `env`/`envFrom`. |
| **Name Hashing (Kustomize)** | 0 мс | Время старта подов | Средняя | GitOps-пайплайны (Argo CD, Flux), где критична мгновенная возможность нативного `rollout undo`. |
| **Контроллер Reloader** | 0 мс | Время реакции API ($< 5$ с) + старт подов | Низкая | Кластеры без централизованного GitOps-генератора хешей, динамические секреты и конфигурации. |

### 2. Принцип обратной и прямой совместимости (N-1 / N+1)

В распределенной среде переключение конфигурации никогда не бывает мгновенным. При проектировании параметров соблюдайте правила:
* **Запрет ломающих удалений:** При удалении ключа конфигурации сначала выпустите версию кода, которая больше не требует данный ключ (делает его опциональным со значением по умолчанию). Только в следующем релизе удаляйте ключ из ConfigMap.
* **Двухфазное добавление:** Если новый параметр обязателен, сначала объявите его в ConfigMap со стандартным дефолтом, дождитесь распространения на все узлы, и только затем выкатывайте код, использующий данный параметр.
* **Смягчение таймингов:** Не меняйте критичные таймауты сетевых соединений радикально за одну итерацию (например, снижение таймаута с 30с до 1с вызовет шквал разрывов во время окна расхождения).

### 3. Согласование параметров надежности (Surge, PDB, Probes)

При настройке параметров развертывания обязательно согласуйте контроллеры:
1. **Лимиты развертывания:**
   ```yaml
   strategy:
     rollingUpdate:
       maxSurge: "25%"
       maxUnavailable: 0 # Гарантирует сохранение 100% емкости пула
   ```
2. **Согласование с PDB:** Если `replicas: 4` и `minAvailable: 3`, то `maxUnavailable` в Deployment не должен превышать 1 под. В противном случае контроллер может заблокировать сам себя при наложении планового обслуживания узлов (`drain`).
3. **Защита через Readiness Probes:**
   Приложение обязано переходить в статус `Ready: false`, если прочитанная конфигурация повреждена или не позволяет инициализировать критические модули. Это автоматически остановит дальнейший Rolling Update и предотвратит вывод из строя оставшихся здоровых подов.
4. **Таймаут грациозного завершения:**
   Устанавливайте `terminationGracePeriodSeconds` с запасом (по умолчанию 30с, для тяжелых соединений 60–120с), чтобы старые реплики успели дообслужить активные клиентские сессии.

### 4. Валидация в CI/CD (Pre-flight Checks)

Никогда не применяйте непроверенные файлы конфигураций в продуктивный контур:
* **Синтаксическая валидация:** Проверка YAML/JSON линтерами (`yamllint`, `kubeval`, `kubeconform`) в CI пайплайне.
* **Семантическая проверка приложения:** Использование утилит валидации (например, `nginx -t`, `promtool check config`) на этапе сборки до создания ConfigMap.
* **Server-side Dry-Run:** Выполнение предварительной проверки API-сервером:
  ```bash
  kubectl apply -f configmap.yaml --server-side --dry-run=server
  # → configmap/app-config serverside-applied (dry run)
  ```

### 5. Мониторинг и метрики Prometheus

Для раннего обнаружения сбоев развертывания конфигураций настройте следующие метрики и алерты:

```promql
# 1. Зависший Rollout (статус Progressing = False дольше 5 минут)
kube_deployment_status_condition{condition="Progressing", status="false"} == 1

# 2. Количество недоступных реплик при обновлении превышает допустимый порог
kube_deployment_status_replicas_unavailable > 0

# 3. Количество рестартов контейнера после обновления (CrashLoop)
increase(kube_pod_container_status_restarts_total[10m]) > 3

# 4. Ошибки синхронизации Kubelet Volume Manager
rate(kubelet_volume_manager_total_errors[5m]) > 0
```

### 6. Регламент экстренного отката (Emergency Rollback Runbook)

При обнаружении деградации сервиса после обновления конфигурации:
1. **Если использовался Name Hashing (Kustomize):**
   ```bash
   kubectl rollout undo deployment/<name> -n <ns>
   # Мгновенный откат к предыдущему ReplicaSet, ссылающемуся на старый рабочий ConfigMap.
   ```
2. **Если ConfigMap был обновлен in-place:**
   Откат только Deployment через `rollout undo` **не поможет**, так как старые поды подтянут уже испорченный ConfigMap!
   * Шаг 1: Восстановить манифест ConfigMap из Git (предыдущий коммит).
   * Шаг 2: Применить `kubectl apply -f configmap.yaml`.
   * Шаг 3: Выполнить `kubectl rollout restart deployment/<name>`.

---

## Дополнительная информация

**Связанные документы базы знаний:**
* [Способы использования ConfigMap в подах](./pod_usage.md) — детальный разбор Atomic Symlink Swap, стратегий Kubelet и монтирования томов.
* [Рекомендации и лучшие практики для ConfigMap](./best_practices.md) — стандарты именования, безопасность и паттерны разделения ответственности.
* [Неизменяемые (Immutable) ConfigMap](./immutable.md) — оптимизация Control Plane, защита от дрейфа и версионирование.
* [Готовые шаблоны ConfigMap](./practical_templates.md) — production-конфигурации для Nginx, Prometheus, PostgreSQL.
* [Работа с большими конфигурациями](./large_configs.md) — преодоление лимита etcd в 1 MiB.
* [Автоматический перезапуск подов (Restart on Change)](../../ToolsUtilities/Helm/templating/scenarios/restart_on_change.md) — детальный разбор паттернов хеширования в Helm.
* [Обзор Reloader](../../ToolsUtilities/reloader/reloader_overview.md) — архитектура и контроллеры автоматической перезагрузки.
* [Установка Reloader](../../ToolsUtilities/reloader/reloader_installation.md) — манифесты развертывания и RBAC для Reloader.
* [Управление жизненным циклом Deployment](../../Base/Deployment/lifecycle_management.md) — механика Rolling Update, паузы и отката.
* [Диагностика и устранение неполадок Deployment](../../Base/Deployment/troubleshooting.md) — разбор зависших обновлений и таймаутов.
* [PodDisruptionBudget (PDB)](../../Autoscaling/pod_disruption_budget.md) — защита рабочих нагрузок от деградации при добровольных сбоях.
* [Блокировка эвикции подов через PDB](../../Troubleshooting/Common_Errors/PodTerminating/pdb_blocking.md) — устранение конфликтов drain и rollout.