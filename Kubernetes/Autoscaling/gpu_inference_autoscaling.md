# GPU-инференс в Kubernetes: автоскейлинг, ускорение деплоя и инфраструктурные паттерны

**Актуально для:** Kubernetes 1.31–1.32 (DRA beta); NVIDIA Container Toolkit 1.17+; Triton Inference Server 24.x / vLLM 0.6+; KEDA 2.15+; containerd 2.0+

## Определения

* **Inference (инференс)** — исполнение скомпилированной модели на входных потоковых или пакетных данных в режиме долгоживущего сетевого сервиса (HTTP/gRPC) с жесткими требованиями к SLA (P95/P99 latency) и непрерывной доступности 24/7.
* **Inference Server (сервер инференса)** — специализированный сетевой демон (Triton Inference Server, vLLM), реализующий параллельную диспетчеризацию входящих очередей, управление жизненным циклом тензоров, выделение контекстов CUDA и передачу данных между памятью хоста (RAM) и видеопамятью (VRAM).
* **Dynamic Batching** — алгоритм планировщика инференс-сервера, агрегирующий индивидуальные асинхронные HTTP/gRPC-запросы в единый пакет (batch) в пределах заданного временного окна задержки (`max_queue_delay_microseconds`) для максимальной загрузки параллельных вычислительных ядер GPU.
* **Extended Resource (`nvidia.com/gpu`)** — целочисленный расширенный ресурс Kubernetes, регистрируемый `k8s-device-plugin`. Выделяется контейнерам строго дискретно (1, 2, 4 GPU); динамическое дробление на уровне нативного kube-scheduler без сторонних надстроек не поддерживается.
* **DCGM (Data Center GPU Manager)** — системный низкоуровневый фреймворк NVIDIA для мониторинга аппаратного состояния GPU (температура, энергопотребление, ошибки памяти ECC, процент времени исполнения ядер GPU — Duty Cycle). В Kubernetes экспортируется через `dcgm-exporter`.
* **Cold Start (холодный старт ворклоада)** — суммарная задержка от момента регистрации дефицита вычислительных мощностей до перевода новой реплики в статус `Ready`. Включает аллокацию физического узла, запуск драйверов, скачивание и распаковку образа, загрузку весов с диска в VRAM и прогрев кэша инференс-движка.
* **Startup Probe** — проба готовности инициализации контейнера в Kubernetes, блокирующая выполнение `livenessProbe` и `readinessProbe` на время продолжительной загрузки тяжелых артефактов весов в VRAM, предотвращая каскадные перезапуски подов по таймауту.
* **Warm Pool (горячий резерв)** — пул предварительно подготовленных вычислительных узлов со скачанными слоями контейнеров и смонтированными хранилищами, минимизирующий время добавления мощностей при резких всплесках нагрузки.

---

## Основные концепции и архитектура

### Архитектура инференс-сервиса в On-Premise инфраструктуре

В отличие от классических stateless веб-сервисов, инференс жестко привязан к аппаратным ускорителям и пропускной способности шины PCIe/NVLink. В on-premise инфраструктуре развертывание инференс-сервера (например, Triton или vLLM) опирается на следующий стек:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Входящий трафик (gRPC / HTTP)                   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                         ┌──────────▼──────────┐
                         │   Ingress / Envoy   │
                         └──────────┬──────────┘
                                    │
        ┌───────────────────────────┴───────────────────────────┐
        ▼                                                       ▼
┌───────────────────────────────┐       ┌───────────────────────────────┐
│ Pod: Triton Replica 1         │       │ Pod: Triton Replica 2         │
│  ├── Dynamic Batcher & Queue  │       │  ├── Dynamic Batcher & Queue  │
│  └── Model Instances (VRAM)   │       │  └── Model Instances (VRAM)   │
└───────────────┬───────────────┘       └───────────────┬───────────────┘
                │ Port 8002 (/metrics)                  │ Port 8002 (/metrics)
                └───────────────────────┬───────────────┘
                                        │
                         ┌──────────────▼─────────────┐
                         │     Prometheus Server      │
                         └──────────────┬─────────────┘
                                        │ PromQL Scrape
                ┌───────────────────────┴───────────────────────┐
                ▼                                               ▼
┌───────────────────────────────┐               ┌───────────────────────────────┐
│      Prometheus Adapter       │               │             KEDA              │
│   (Custom Metrics API)        │               │     (Prometheus Scaler)       │
└───────────────┬───────────────┘               └───────────────┬───────────────┘
                │                                               │
                └───────────────────────┬───────────────────────┘
                                        │ Scale Target
                         ┌──────────────▼─────────────┐
                         │   HPA (Horizontal Scale)   │
                         └──────────────┬─────────────┘
                                        │ Создание подов
                         ┌──────────────▼─────────────┐
                         │       kube-scheduler       │
                         └──────────────┬─────────────┘
                                        │ [Нет свободных nvidia.com/gpu]
                         ┌──────────────▼─────────────┐
                         │ Cluster Autoscaler (CAPI)  │
                         │   (Metal3 / Bare-Metal)    │
                         └────────────────────────────┘
```

### Почему VPA и стандартный HPA по CPU/Memory неприменимы

1. **Неделимость ресурсов GPU:** Vertical Pod Autoscaler (VPA) управляет ресурсами `cpu` и `memory`. Ресурс `nvidia.com/gpu` является расширенным (Extended Resource). Его нельзя динамически изменить внутри запущенного контейнера без пересоздания пода.
2. **Отсутствие корреляции CPU/RAM с реальной нагрузкой:** При обработке тяжелых матричных операций процессор хоста (CPU) может простаивать в ожидании прерываний от GPU, находясь на уровне утилизации 5–15%, в то время как очередь тензорных вычислений на GPU переполнена. Напротив, при потоковом парсинге запросов CPU может подниматься до 100%, пока вычислительные ядра GPU недозагружены из-за неэффективного батчинга.
3. **Статичность видеопамяти:** Инференс-серверы аллоцируют VRAM под веса моделей и контекстный кэш (KV-cache) сразу при старте процесса (часто 70–90% всей доступной физической VRAM). Метрика использования VRAM остается плоской константой независимо от того, обрабатывает сервис 1 запрос или 1000.

Следовательно, единственным рабочим механизмом автомасштабирования инференса является **горизонтальное масштабирование (HPA / KEDA)** по прикладным метрикам очередей и времени обработки.

### Конвейер холодного старта и временные задержки

При возникновении всплеска входящего трафика жизненный цикл добавления новой вычислительной реплики на физическом оборудовании проходит через последовательность узких горлышек:

| Фаза | Операция | Длительность (On-Premise) | Узкое место / Причина задержки |
|:---|:---|:---|:---|
| **1. Детектирование** | Скрейпинг метрик → PromQL-агрегация → HPA sync | 15–45 сек | Интервал `--horizontal-pod-autoscaler-sync-period`, интервал сбора Prometheus |
| **2. Планирование** | Оценка фильтров `kube-scheduler` | 1–5 сек | Отсутствие узлов с доступным ресурсом `nvidia.com/gpu` (переход в `Pending`) |
| **3. Провижининг узла** | Включение сервера через IPMI/PXE, boot ОС (Metal3 / CAPI) | 5–20 мин | Прохождение аппаратного POST, сетевая загрузка ядра, инициализация PCIe устройств |
| **4. GPU-стек хоста** | Запуск NVIDIA GPU Operator / Device Plugin | 1–3 мин | Загрузка модулей ядра (`nvidia.ko`, `nvidia_uvm.ko`), инициализация fabric manager, запуск CDI |
| **5. Скачивание образа** | Доставка OCI-образа инференс-сервера из Registry | 1–5 мин | Размер образа (15–30 ГБ: CUDA runtime, cuDNN, TensorRT, библиотеки бэкендов) |
| **6. Экстракция слоев** | Распаковка tar-архивов containerd на локальный диск | 2–6 мин | Последовательная декомпрессия gzip на один поток CPU, дисковые задержки блочного устройства |
| **7. Загрузка весов** | Копирование весов модели из хранилища в RAM хоста | 30–180 сек | Пропускная способность сети (NFS / CephFS / MinIO) или локального NVMe |
| **8. Аллокация VRAM** | Передача тензоров из RAM в VRAM через шину PCIe | 15–60 сек | Пропускная способность шины PCIe Gen4/Gen5 (16–32 ГБ/с на x16 линий) |
| **9. Инициализация и Warmup**| Запуск графа вычислений, компиляция ядра, Startup Probe | 10–60 сек | Валидация входных тензоров, прогрев CUDA context |

**Итоговый холодный старт:** от 3–5 минут (при наличии теплого узла) до 15–30 минут (при холодном включении bare-metal сервера).

---

## Выбор метрик для автомасштабирования

Использование некорректных метрик приводит к трэшингу (flapping) или критической деградации SLA.

### Парадокс утилизации GPU (`DCGM_FI_DEV_GPU_UTIL`)

Метрика `DCGM_FI_DEV_GPU_UTIL` (GPU Duty Cycle) показывает процент времени за прошедшую выборку (обычно 1 секунда), в течение которого хотя бы одно вычислительное ядро (SM) выполняло инструкцию.
* **Ложноположительное срабатывание:** 1 единичный последовательный запрос на выполнение неоптимизированной операции загружает SM на 100%, хотя пропускная способность карты свободна для параллельного батча. Масштабирование по этой метрике создаст избыточные дорогостоящие поды.
* **Ложноотрицательное срабатывание:** При интенсивном вводе-выводе и копировании данных по шине PCIe вычислительные ядра могут показывать 20–30% активности, в то время как очередь входящих запросов катастрофически растет из-за насыщения шины памяти.

### Оптимальные метрики масштабирования

| Метрика | Источник | Тип в PromQL / Описание | Порог срабатывания (SRE ориентир) |
|:---|:---|:---|:---|
| **Время нахождения в очереди** | Triton (`nv_inference_queue_duration_us`) | `rate(nv_inference_queue_duration_us[1m]) / rate(nv_inference_request_duration_us[1m])` | Превышение допустимой задержки очереди (> 20–50 мс) |
| **Количество запросов в очереди** | Triton (`nv_inference_pending_request_count`) / vLLM (`vllm:num_requests_waiting`) | `avg(nv_inference_pending_request_count)` или `sum(vllm:num_requests_waiting)` | Заполнение очереди выше емкости одного батча (> 5–10) |
| **P95 Latency обработки** | Ingress Controller / Service Mesh (Envoy) | `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[1m])) by (le))` | Превышение верхнего порога SLA сервиса (например, > 200 мс) |
| **Активные конкурентные запросы** | Triton (`nv_inference_active_request_count`) | `avg(nv_inference_active_request_count)` | Приближение к пределу параллельных инстансов модели |

---

## Архитектура хранения и оптимизация холодного старта

### 1. Отчуждение весов моделей от контейнерного образа

Хранение бинарных весов моделей внутри OCI-образа Docker является антипаттерном в SRE:
* Размер образа раздувается до 50–200 ГБ.
* Любое обновление инфраструктурных библиотек (Triton, CUDA, drivers) требует повторной сборки и перекачивания гигантских слоев на все узлы.
* Реестр образов (Harbor) испытывает экстремальную нагрузку на дисковую подсистему и сеть.

**Архитектурные паттерны доставки весов в On-Premise:**

```
                  ┌──────────────────────────────────────────────┐
                  │          Хранилище весов (On-Premise)        │
                  │        (CephFS / NFS / MinIO S3)             │
                  └───────┬──────────────────────────────┬───────┘
                          │                              │
                          │ ReadOnlyMany PVC             │ S3 Sync / Streaming
                          ▼                              ▼
              ┌───────────────────────┐      ┌───────────────────────┐
              │  Подход 1: Shared FS  │      │ Подход 2: Local NVMe  │
              │  Монтирование PVC     │      │ InitContainer кэширует│
              │  напрямую в /models   │      │ на hostPath / emptyDir│
              └───────────────────────┘      └───────────────────────┘
```

1. **Shared ReadOnlyMany PVC (CephFS / High-Performance NFS):**
   * Все поды монтируют один и тот же том.
   * Плюсы: нулевое время локального копирования при старте пода.
   * Минусы: при одновременном старте 10 подов сетевой интерфейс хранилища утилизируется на 100%, чтение весов замедляется.
2. **Локальный NVMe кэш на ноде (HostPath + InitContainer):**
   * Узлы кластера оснащаются локальными высокоскоростными NVMe-накопителями.
   * Init-контейнер проверяет контрольную сумму модели в локальном каталоге `/opt/model-cache`. Если веса отсутствуют — скачивает их из внутреннего MinIO S3 по высокоскоростной локальной сети (100GbE). Если присутствуют — под стартует мгновенно, читая данные из локального NVMe.

### 2. Оптимизация сжатия слоев: ZSTD вместо GZIP

Формат OCI по умолчанию использует сжатие GZIP, которое распаковывается в один поток CPU и становится главным узким местом при развертывании тяжелых образов с CUDA.

Использование компрессии Zstandard (ZSTD) ускоряет распаковку слоев containerd в 3–5 раз за счет эффективного многопоточного алгоритма декомпрессии при сравнимом коэффициенте сжатия:
* Сборка образа с флагами BuildKit:
  `--output type=image,name=<registry>/<image>,push=true,compression=zstd,compression-level=3,force-compression=true`
* Параметр `force-compression=true` принудительно перепаковывает унаследованные родительские слои базового образа CUDA в ZSTD.
* Поддержка containerd: containerd 1.6+ и 2.0+ нативно распаковывают слои `application/vnd.oci.image.layer.v1.tar+zstd`.

### 3. Ленивая загрузка слоев (Lazy Loading via eStargz / Nydus)

Снапшоттеры ленивой загрузки монтируют OCI-образ через виртуальную файловую систему (FUSE) и скачивают отдельные блоки файлов по требованию, позволяя контейнеру стартовать за доли секунды без полного скачивания образа.

**Ограничение для тяжелых GPU-библиотек:**
В отличие от микросервисов на Go/Node.js, GPU-инференс использует крупные динамические библиотеки (`libcudnn.so`, `libnvinfer.so`, `libtorch_cuda.so`), размер каждой из которых достигает сотен мегабайт и гигабайтов. При инициализации рантайм выполняет `dlopen()` и последовательно прочитывает библиотеки целиком в оперативную память. Это инициирует шквал случайных сетевых I/O запросов к реестру, сводя на нет выигрыш от FUSE-монтирования и нередко приводя к замедлению старта по сравнению с монолитным линейным скачиванием ZSTD-слоев.

### 4. P2P-дистрибуция образов (Dragonfly) и локальные кэширующие прокси

При одновременном масштабировании нескольких десятков GPU-подов центральный реестр артефактов (Harbor) становится точкой отказа.
* **Dragonfly (CNCF Incubating):** P2P-сеть распределения данных. Ноды кластера обмениваются уже скачанными частями слоев между собой по локальной сети внутри стойки (ToR switch) на скорости 40/100 Gbps, не перегружая центральный репозиторий.
* **Pre-pulling / Warm DaemonSets:** фоновый DaemonSet с низким приоритетом, заранее скачивающий актуальные версии образов инференс-сервера на все GPU-ноды кластера.

---

## Практические сценарии

### Сценарий 1: Развертывание Triton с Startup Probe, ресурсом `nvidia.com/gpu` и внешним хранилищем весов

Манифест промышленного развертывания с разделением проб доступности: длительный таймаут инициализации через `startupProbe` предотвращает убийство пода процессом kubelet до полной загрузки весов в VRAM.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: triton-inference
  namespace: ml-serving
  labels:
    app: triton-inference
spec:
  replicas: 2
  selector:
    matchLabels:
      app: triton-inference
  template:
    metadata:
      labels:
        app: triton-inference
    spec:
      containers:
      - name: triton-server
        image: cr.internal/ml/tritonserver:24.08-py3-zstd
        args:
        - "tritonserver"
        - "--model-repository=/models"
        - "--strict-model-config=false"
        - "--log-verbose=0"
        - "--exit-on-error=true"
        resources:
          limits:
            nvidia.com/gpu: 1
            cpu: "8"
            memory: 32Gi
          requests:
            nvidia.com/gpu: 1
            cpu: "4"
            memory: 16Gi
        ports:
        - containerPort: 8000
          name: http
        - containerPort: 8001
          name: grpc
        - containerPort: 8002
          name: metrics
        # Блокирует liveness/readiness проверки до 10 минут (60 * 10 сек)
        startupProbe:
          httpGet:
            path: /v2/health/ready
            port: 8000
          initialDelaySeconds: 15
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 60
        readinessProbe:
          httpGet:
            path: /v2/health/ready
            port: 8000
          periodSeconds: 5
          timeoutSeconds: 2
          failureThreshold: 3
        livenessProbe:
          httpGet:
            path: /v2/health/live
            port: 8000
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 3
        volumeMounts:
        - name: model-repository
          mountPath: /models
          readOnly: true
      volumes:
      - name: model-repository
        persistentVolumeClaim:
          claimName: nfs-model-store-pvc
          readOnly: true
```

### Сценарий 2: Автомасштабирование HPA через Prometheus Adapter по задержке очереди Triton

В данном сценарии рассчитывается среднее время нахождения запроса в очереди инференса на под.

1. **Конфигурация правила Prometheus Adapter (`config.yaml`):**

```yaml
rules:
  - seriesQuery: '{__name__=~"nv_inference_queue_duration_us",namespace!="",pod!=""}'
    resources:
      overrides:
        namespace: {resource: "namespace"}
        pod: {resource: "pod"}
    name:
      matches: "nv_inference_queue_duration_us"
      as: "triton_avg_queue_duration_ms"
    metricsQuery: >-
      (
        sum(rate(nv_inference_queue_duration_us{<<.LabelMatchers>>}[1m])) by (<<.GroupBy>>)
        /
        clamp_min(sum(rate(nv_inference_request_duration_us{<<.LabelMatchers>>}[1m])) by (<<.GroupBy>>), 0.001)
      ) / 1000
```

2. **Манифест HPA:**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: triton-inference-hpa
  namespace: ml-serving
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: triton-inference
  minReplicas: 2
  maxReplicas: 8
  metrics:
  - type: Pods
    pods:
      metric:
        name: triton_avg_queue_duration_ms
      target:
        type: AverageValue
        # Целевая средняя задержка ожидания в очереди — 50 мс
        averageValue: "50"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
    scaleDown:
      # Защита от трэшинга: длительное окно стабилизации scale-down
      stabilizationWindowSeconds: 300
      policies:
      - type: Pods
        value: 1
        periodSeconds: 60
```

### Сценарий 3: Автомасштабирование через KEDA ScaledObject по глубине очереди запросов

KEDA позволяет выполнять прямой PromQL-запрос к Prometheus без необходимости конфигурирования API Aggregation Layer и адаптеров, а также обеспечивает масштабирование в ноль (scale-to-zero) при полном отсутствии трафика.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: triton-queue-scaler
  namespace: ml-serving
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: triton-inference
  minReplicaCount: 1
  maxReplicaCount: 10
  cooldownPeriod: 300
  pollingInterval: 15
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 600
          policies:
          - type: Percent
            value: 20
            periodSeconds: 60
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus-k8s.monitoring.svc.cluster.local:9090
      metricName: triton_pending_requests
      # Порог: если среднее число запросов в очереди на реплику превышает 15
      threshold: '15'
      query: >-
        sum(nv_inference_pending_request_count{namespace="ml-serving",app="triton-inference"})
        /
        count(kube_pod_status_phase{namespace="ml-serving",pod=~"triton-inference-.*",phase="Running"})
```

### Сценарий 4: Сборка OCI-образа со сжатием ZSTD через Docker Buildx

Команда перепаковки базового GPU-образа со сжатием ZSTD уровня 3 (оптимальный баланс между размером и скоростью декомпрессии):

```bash
# Сборка и отправка в локальный репозиторий с принудительной конвертацией слоев в ZSTD
docker buildx build \
  --platform linux/amd64 \
  --output type=image,name=cr.internal/ml/tritonserver:24.08-py3-zstd,push=true,compression=zstd,compression-level=3,force-compression=true \
  -f Dockerfile .
# → [pushing layers] application/vnd.oci.image.layer.v1.tar+zstd
# → DONE
```

---

## Операции и команды

### Валидация состояния GPU-узлов в кластере

Проверка регистрации расширенного ресурса `nvidia.com/gpu` и доступности емкости на узлах:

```bash
# Проверка зарегистрированных GPU ресурсов на узлах кластера
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU_CAPACITY:.status.capacity.'nvidia\.com/gpu',GPU_ALLOCATABLE:.status.allocatable.'nvidia\.com/gpu'
# → NAME         GPU_CAPACITY   GPU_ALLOCATABLE
# → gpu-node-01  4              4
# → gpu-node-02  4              2
# → gpu-node-03  <none>         <none>
```

Проверка распределения GPU между запущенными подами:

```bash
# Поиск подов, удерживающих GPU на узле gpu-node-02
kubectl get pods -A --field-selector spec.nodeName=gpu-node-02 -o json | \
  jq -r '.items[] | select(.spec.containers[].resources.requests["nvidia.com/gpu"] != null) | [.metadata.namespace, .metadata.name] | @tsv'
# → ml-serving   triton-inference-7d98b58495-4k8xm
# → ml-serving   triton-inference-7d98b58495-w2l9p
```

### Проверка метрик инференс-сервера

Проверка прямого экспорта метрик процесса Triton через порт 8002:

```bash
# Запрос метрик Triton через временный curl-под
kubectl run curl-test --rm -i --restart=Never --image=curlimages/curl -- \
  curl -s http://triton-inference.ml-serving.svc.cluster.local:8002/metrics | grep -E "nv_inference_(queue|request)"
# → nv_inference_request_duration_us{model="model_a",version="1"} 45290123
# → nv_inference_queue_duration_us{model="model_a",version="1"} 1245080
# → nv_inference_pending_request_count{model="model_a",version="1"} 3
```

### Валидация Custom Metrics API

Проверка доступности кастомной метрики, транслируемой Prometheus Adapter в Aggregated API:

```bash
# Запрос списка доступных кастомных метрик подов
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/ml-serving/pods/*/triton_avg_queue_duration_ms" | jq .
# → {
# →   "kind": "MetricValueList",
# →   "apiVersion": "custom.metrics.k8s.io/v1beta1",
# →   "items": [
# →     {
# →       "describedObject": {
# →         "kind": "Pod",
# →         "name": "triton-inference-7d98b58495-4k8xm"
# →       },
# →       "metricName": "triton_avg_queue_duration_ms",
# →       "value": "24m"
# →     }
# →   ]
# → }
```

### Диагностика статуса масштабирования в KEDA и HPA

```bash
# Проверка состояния ScaledObject в KEDA
kubectl get scaledobject triton-queue-scaler -n ml-serving
# → NAME                  SCALETARGETKIND      SCALETARGETNAME    MIN   MAX   TRIGGERS     AUTHENTICATION   READY   ACTIVE   AGE
# → triton-queue-scaler   apps/v1/Deployment   triton-inference   1     10    prometheus                    True    True     4d

# Проверка событий сгенерированного HPA
kubectl describe hpa keda-hpa-triton-queue-scaler -n ml-serving
# → Reference:                                         Deployment/triton-inference
# → Metrics ( current / target ):                      12 / 15 (average value)
# → Min replicas:                                      1
# → Max replicas:                                      10
# → Deployment pods:                                   3 current / 3 desired
# → Conditions:
# →   Type            Status  Reason               Message
# →   ----            ------  ------               -------
# →   AbleToScale     True    ScaleDownStabilized  recent recommendations were higher than current one
# →   ScalingActive   True    ValidMetricFound     the HPA was able to successfully calculate a replica count
```

---

## Диагностика и устранение неполадок

### 1. Под бесконечно висит в статусе `Pending` с ошибкой `0/N nodes available: Insufficient nvidia.com/gpu`

* **Симптом:** HPA создает новую реплику пода, но она не запускается. В событиях пода (`kubectl describe pod`) ошибка планировщика.
* **Причина:** В кластере отсутствуют узлы со свободным целочисленным ресурсом `nvidia.com/gpu`. Все физические карты заняты другими ворклоадами, либо на узлах произошла фрагментация ресурсов (есть свободный CPU/RAM, но нет свободного GPU).
* **Диагностика:**
  ```bash
  # Проверка аллокации ресурсов на GPU нодах
  kubectl describe nodes -l accelerator=nvidia | grep -A 8 "Allocated resources:"
  # → nvidia.com/gpu  4 (100%)  4 (100%)
  ```
* **Решение:**
  1. Развернуть Cluster Autoscaler с провайдером On-Premise (Metal3/CAPI) для автоматического включения резервных серверов через IPMI.
  2. Использовать специализированный планировщик с поддержкой очередей и квот ([Kueue](../Scheduling/kueue.md)), чтобы предотвратить захват всех GPU низкоприоритетными задачами.
  3. Для небольших моделей внедрить технологии совместного использования GPU (Time-slicing / MIG / HAMi), см. [Шеринг GPU в Kubernetes](../Scheduling/gpu_sharing.md).

### 2. Под уходит в `CrashLoopBackOff` по таймауту `Liveness probe failed`

* **Симптом:** Контейнер успешно стартует, начинает загрузку весов модели, но через 30–60 секунд принудительно перезапускается kubelet-ом. В событиях: `Liveness probe failed: HTTP probe failed with statuscode: 503`.
* **Причина:** Веса модели загружаются в память несколько минут. Kubelet начинает выполнять `livenessProbe` сразу после старта контейнера. Поскольку сервер инференса еще не инициализировал модель, эндпоинт `/v2/health/live` возвращает ошибку или не отвечает, и kubelet убивает процесс по таймауту.
* **Решение:** Добавить `startupProbe` с высоким значением `failureThreshold` (например, `periodSeconds: 10`, `failureThreshold: 60`, что дает окну инициализации 10 минут). `livenessProbe` начнет выполняться только после того, как `startupProbe` завершится успехом.

### 3. Быстрое скачивание образа, но экстремально долгий старт контейнера (Extraction Bottleneck)

* **Симптом:** Событие `Pulling image` завершается за 40 секунд, но событие `Pulled image` и `Created container` появляются только через 6–8 минут.
* **Причина:** Слои базовых образов CUDA и Triton весят до 6–10 ГБ каждый и сжаты стандартным алгоритмом GZIP. Распаковка GZIP в containerd является однопоточным процессом, упирающимся в тактовую частоту одного ядра CPU и скорость синхронной записи блочного устройства.
* **Решение:**
  1. Пересобрать образы со сжатием ZSTD (`compression=zstd` в BuildKit). Декомпрессия ZSTD выполняется многопоточно и снижает задержку распаковки в 3–5 раз.
  2. Настроить локальный каталог containerd (`/var/lib/containerd`) на быстрый физический NVMe диск с файловой системой ext4/xfs и опцией монтирования `noatime`.

### 4. Трэшинг автоскейлинга (Flapping / Scaling Oscillation)

* **Симптом:** Реплики инференса непрерывно создаются и удаляются с интервалом в несколько минут.
* **Причина:** Очередь запросов кратковременно опустошается сразу после добавления новой реплики. Стандартный HPA мгновенно инициирует scale-down. Как только реплика удаляется, оставшиеся поды перегружаются, и цикл повторяется. Из-за высокой стоимости инициализации GPU подов это приводит к деградации сервиса.
* **Решение:** Настроить окно стабилизации `behavior.scaleDown.stabilizationWindowSeconds` на значение 300–600 секунд (5–10 минут) и ограничить максимальный шаг сжатия (`maxSurge`/`policies`), запрещая удаление более 1–2 подов за цикл.

### 5. Ошибка CUDA Out of Memory (OOM) без завершения пода ядром Linux

* **Симптом:** Сервер инференса возвращает клиентам ошибки HTTP 500 / gRPC Internal (`CUDA out of memory`), но контейнер не перезапускается, статус пода остается `Running`.
* **Причина:** Стандартный механизм Linux OOM Killer отслеживает только системную оперативную память хоста (RAM), лимитируемую через cgroups (`resources.limits.memory`). Переполнение видеопамяти (VRAM) на уровне GPU не приводит к генерации сигнала `SIGKILL` операционной системой.
* **Решение:**
  1. Настроить в Triton / vLLM флаг автоматического завершения процесса при критической ошибке выделения памяти (`--exit-on-error=true`).
  2. Ограничить размер контекстного кэша (KV-cache) и максимальный размер батча (`max_batch_size`) в конфигурации модели, чтобы пиковое потребление VRAM гарантированно укладывалось в физический объем GPU.
  3. Настроить alerting по метрике `nv_inference_compute_infer_failure_count` в Prometheus.

---

## Лучшие практики (Best Practices)

### 1. Компенсация задержек Bare-Metal через Warm Standby (Overprovisioning)

В on-premise инфраструктуре включение физического сервера занимает 5–15 минут. Чтобы сгладить пиковые нагрузки, разверните в кластере «холостые» поды-заполнители (Pause Pods) с отрицательным приоритетом:

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: overprovisioning-priority
value: -10
preemptionPolicy: PreemptLowerPriority
globalDefault: false
description: "Низкоприоритетный класс для удержания горячего резерва нод"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gpu-overprovisioning
  namespace: kube-system
spec:
  replicas: 2
  selector:
    matchLabels:
      app: gpu-overprovisioning
  template:
    metadata:
      labels:
        app: gpu-overprovisioning
    spec:
      priorityClassName: overprovisioning-priority
      containers:
      - name: pause
        image: registry.k8s.io/pause:3.10
        resources:
          limits:
            nvidia.com/gpu: 1
          requests:
            nvidia.com/gpu: 1
```

* **Механика:** Поды резервируют GPU на физических узлах. При появлении реального пода инференса с нормальным приоритетом `kube-scheduler` мгновенно вытесняет (preempt) pause-под. Реальный под стартует на уже прогретой ноде без задержки на включение железа, а вытесненный pause-под уходит в `Pending` и инициирует провижининг следующего резервного сервера через Cluster Autoscaler.

### 2. Защита от добровольных прерываний (PodDisruptionBudget)

Масштабирование вниз и обслуживание физических узлов (`kubectl drain`) не должны нарушать доступность инференс-сервиса:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: triton-inference-pdb
  namespace: ml-serving
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: triton-inference
```

* Обеспечивает наличие как минимум одной активной реплики с загруженной моделью при проведении регламентных работ на узлах. Подробнее — в [Pod Disruption Budget](./pod_disruption_budget.md).

### 3. Чек-лист оптимизации инференса для SRE / DevOps

- [ ] **Веса моделей:** вынесены на ReadOnlyMany том (CephFS/NFS) или локальный NVMe кэш хоста; веса отсутствуют в слоях контейнера.
- [ ] **Сжатие OCI-образа:** базовый образ пересобран с компрессией ZSTD (`compression=zstd,force-compression=true`).
- [ ] **Пробы контейнера:** настроен `startupProbe` с запасом времени не менее 5–10 минут на чтение весов в VRAM; `livenessProbe` защищен от ложных срабатываний.
- [ ] **Метрики автоскейлинга:** HPA/KEDA настроен по глубине очереди (`queue_duration` / `pending_requests`), а не по `DCGM_FI_DEV_GPU_UTIL`.
- [ ] **Стабилизация HPA:** параметр `behavior.scaleDown.stabilizationWindowSeconds` установлен не менее чем на 300–600 секунд.
- [ ] **Горячий резерв:** настроен Overprovisioning через низкоприоритетные pause-поды для компенсации длительного boot bare-metal серверов.
- [ ] **Мониторинг железа:** развернут `dcgm-exporter` со сбором показателей температуры, ошибок ECC и энергопотребления GPU.

---

## Дополнительная информация

* [Prometheus Adapter: настройка и интеграция с HPA](./HPA/prometheus_adapter_setup.md) — трансляция метрик Prometheus в Custom Metrics API.
* [Autoscaling в On-Premise / Bare-Metal средах](./on_premise_autoscaling.md) — провижининг физических узлов через Metal3, Ironic и Cluster API.
* [Cluster Autoscaler: глубокое погружение](./cluster_autoscaler_detailed.md) — механика расширения пулов нод и симуляция планировщика.
* [Шеринг GPU в Kubernetes](../Scheduling/gpu_sharing.md) — технологии разделения видеокарт: Time-slicing, MPS, MIG и виртуализация HAMi.
* [Kueue](../Scheduling/kueue.md) — управление очередями, квотами и справедливым распределением GPU-ресурсов в мультиарендных кластерах.
* [Обзор решений для планирования](../Scheduling/scheduling_solutions_overview.md) — сравнение специализированных планировщиков Kubernetes.
* [Device Manager и расширенные ресурсы](../Scheduling/device_manager.md) — механика регистрации расширенных ресурсов `nvidia.com/gpu` и Device Plugins.
* [GPU и ML-нагрузки в Dockerfile](../../Docker/Dockerfile/dockerfile-gpu-ml.md) — сборка образов, CDI, совместимость версий CUDA и драйверов.
* [GPU-диагностика и DCGM](../../Linux/Diagnostics/Hardware/gpu_diagnostics.md) — низкоуровневая диагностика ускорителей и экспорт метрик в Prometheus.
* [Pod Disruption Budget (PDB)](./pod_disruption_budget.md) — обеспечение непрерывной доступности ворклоадов при масштабировании и обслуживании узлов.
