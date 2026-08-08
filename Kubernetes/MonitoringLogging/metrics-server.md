# Metrics Server: Мониторинг ресурсов кластера

## Определения

**Metrics Server** — масштабируемый, эффективный источник метрик использования ресурсов контейнеров для Kubernetes. Работает в оперативной памяти (in-memory) и не хранит исторические данные. Является реализацией **Resource Metrics API**.

**cAdvisor (Container Advisor)** — встроенный в `kubelet` компонент, который читает метрики напрямую из `cgroups` (control groups) ядра Linux. cAdvisor собирает данные об использовании ресурсов (CPU, память) с уровня контейнеров и предоставляет их Metrics Server через Kubelet Summary API (порт 10250).

**Resource Metrics API (`metrics.k8s.io`)** — стандартный API Kubernetes, через который Metrics Server отдает данные агрегатору. Этот API критичен для работы механизмов автоскейлинга.

**Область применения:**
- Обеспечение работы команд CLI `kubectl top nodes` и `kubectl top pods`.
- Основной, "нативный" источник данных для **[Horizontal Pod Autoscaler (HPA)](../Autoscaling/HPA/index.md)** при масштабировании по CPU и RAM.
- Предоставление данных для **[Vertical Pod Autoscaler (VPA)](../Autoscaling/vpa_detailed.md)**.

> **Важно:** Metrics Server собирает метрики _только_ по CPU и Memory. Для масштабирования по кастомным метрикам (RPS, длина очереди, HTTP-задержки) требуется **Prometheus Adapter** или **KEDA**.

## Основные концепции

### Место в конвейере данных (Pipeline)
Поток данных телеметрии выглядит следующим образом:
`Linux cgroups → kubelet (cAdvisor) → Metrics Server → Kube API Server (Aggregator Layer) → HPA / VPA`

В отличие от Prometheus, который собирает метрики раз в 15-60 секунд и добавляет задержку на индексацию, Metrics Server оптимизирован для **минимальной задержки (Low Latency)**. Именно поэтому HPA по умолчанию использует его — это предотвращает эффект staleness (устаревания) при принятии решений об экстренном масштабировании.

### Архитектура и отказоустойчивость (HA)
Metrics Server разворачивается как `Deployment` в пространстве имен `kube-system`. В крупных (Production) кластерах рекомендуется использовать режим высокой доступности:
- **Количество реплик**: Оптимально 2 реплики. Большее количество не дает преимуществ, так как _каждая_ реплика опрашивает все узлы кластера независимо, что может создать лишнюю нагрузку на kubelet.
- **Aggregator Routing**: Для балансировки запросов между репликами `kube-apiserver` должен быть запущен с флагом `--enable-aggregator-routing=true`.
- **Pod Disruption Budget (PDB)**: Обязательно установите PDB с `maxUnavailable: 1`, чтобы гарантировать доступность Metrics API во время обновления узлов (Node Drain).

### Масштабирование ресурсов (VPA)
Потребление ресурсов Metrics Server растет пропорционально количеству узлов и подов в кластере.
**Формула расчета (на каждые 100 узлов):**
- **CPU**: Базовые 100m + 1m на каждый узел.
- **Memory**: Базовые 200Mi + 2Mi на каждый узел.
Поскольку кластер может динамически расти, рекомендуется использовать [VPA](../Autoscaling/vpa_detailed.md) в режиме `Auto` или `Initial` исключительно для пода Metrics Server, чтобы он автоматически получал больше RAM и не падал по OOM (Out Of Memory).

## Практические сценарии

### Установка и настройка (Helm)
Рекомендуется использовать Helm-чарт, так как он позволяет легко настроить параметры высокой доступности и разрешения метрик.

```bash
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm repo update

# Пример values.yaml для Production:
# metrics-server-values.yaml
replicas: 2
apiService:
  create: true
args:
  # Частота опроса kubelet (влияет на скорость HPA)
  - --metric-resolution=15s
  # Приоритет IP-адресов узлов (важно в облаках, чтобы избегать внешних IP)
  - --kubelet-preferred-address-types=InternalIP
  # - --kubelet-insecure-tls # Раскомментируйте ТОЛЬКО для Dev/Minikube!
resources:
  requests:
    cpu: 100m
    memory: 200Mi
  limits:
    memory: 500Mi # Защита узла от утечек
```

```bash
helm install metrics-server metrics-server/metrics-server \
  --namespace kube-system \
  --create-namespace \
  -f metrics-server-values.yaml
```

### Проверка статуса (Troubleshooting)

После установки данные становятся доступны через 1-2 минуты.

**1. Проверка регистрации API:**
Самый важный шаг. Если APIService не зарегистрирован или `AVAILABLE` равен `False`, HPA работать не будет.
```bash
kubectl get apiservice v1beta1.metrics.k8s.io
# → NAME                      SERVICE                      AVAILABLE   AGE
# → v1beta1.metrics.k8s.io    kube-system/metrics-server   True        1m
```

**2. Просмотр ресурсов:**
```bash
# Ресурсы узлов
kubectl top nodes
# → NAME        CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → control-1   150m         7%     1400Mi          36%

# Ресурсы подов с сортировкой
kubectl top pods -A --sort-by=cpu
```

## Решение проблем

### Ошибка "ScalingActive: False" в HPA
Если `kubectl describe hpa <name>` показывает причину `failed to get CPU utilization`, проверьте:
1. Заданы ли `resources.requests` у контейнеров целевого приложения (HPA не может рассчитать проценты, если нет базы для расчета).
2. Статус APIService (`kubectl get apiservice v1beta1.metrics.k8s.io`). Если он False, смотрите логи Metrics Server.

### Metrics Server не запускается (CrashLoopBackOff / TLS errors)
Если в логах (`kubectl logs -n kube-system deploy/metrics-server`) видны ошибки `x509: cannot validate certificate`:
- **Причина**: Kubelet использует самоподписанные сертификаты (типично для `kubeadm`, k3s или локальных сред).
- **Решение**: Добавить флаг `--kubelet-insecure-tls` в `args` Helm-чарта. В Production средах следует настроить доверие к CA узлов или использовать валидные сертификаты Kubelet.

### Ошибки таймаутов (Timeout) от Aggregator
Если `kubectl top` зависает и падает с Timeout:
- **Причина**: `kube-apiserver` (Control Plane) не может установить сетевое соединение с подом Metrics Server.
- **Решение**: Проверьте правила брандмауэра (Security Groups в AWS/GCP). `kube-apiserver` (через Egress) должен иметь доступ к порту пода Metrics Server (обычно 4443).

## Дополнительная информация

### Отличие от Prometheus и cAdvisor
- **cAdvisor** — это агент-сборщик на узле.
- **Metrics Server** — это агрегатор данных от cAdvisor со всех узлов, создающий единый API реального времени для HPA. Он *не хранит* историю.
- **Prometheus** — это база данных временных рядов (TSDB). Собирает данные для визуализации (Grafana), долгосрочной аналитики, расчетов бюджетов (FinOps) и сложных алертов.

### Смежные темы
- **[HPA: Автомасштабирование подов](../Autoscaling/HPA/index.md)** — глубокое погружение в горизонтальное масштабирование.
- **[Monitoring Architecture](./kubernetes-monitoring-logging-architecture.md)** — обзор архитектуры мониторинга и интеграция с Prometheus.
- **[Troubleshooting HPA](../Troubleshooting/Common_Errors/hpa_troubleshooting.md)** — детальный разбор ошибок `ScalingActive`.
