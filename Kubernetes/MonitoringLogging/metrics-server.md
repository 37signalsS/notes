# Metrics Server: Мониторинг ресурсов кластера

## Определения

**Metrics Server** — легковесный агрегатор данных о потреблении ресурсов в кластере Kubernetes, работающий в оперативной памяти (in-memory). Он собирает метрики CPU и оперативной памяти с каждого узла через Summary API (`kubelet`) и предоставляет их через Metrics API (`metrics.k8s.io`).

**cAdvisor (Container Advisor)** — встроенный в `kubelet` инструмент с открытым исходным кодом от Google для мониторинга и анализа производительности контейнеров. cAdvisor собирает данные в реальном времени об использовании ресурсов (CPU, память, сеть, диск) непосредственно с уровня контейнеров и предоставляет их Metrics Server через Summary API.

Metrics Server не предназначен для долгосрочного хранения данных или сложной аналитики. Его основная роль — служить источником оперативных данных для механизмов автоматизации Kubernetes.

**Область применения:**
- Обеспечение работы команд `kubectl top nodes` и `kubectl top pods`.
- Источник данных для **Horizontal Pod Autoscaler (HPA)**.
- Предоставление данных для **Vertical Pod Autoscaler (VPA)**.

## Основные концепции

### Архитектура и отказоустойчивость (HA)
Metrics Server разворачивается как `Deployment` в пространстве имен `kube-system`. В крупных кластерах рекомендуется использовать режим высокой доступности:
- **Количество реплик**: Оптимально 2 реплики. Большее количество не дает преимуществ, так как каждая реплика опрашивает все узлы кластера.
- **Aggregator Routing**: Для балансировки запросов между репликами `kube-apiserver` должен быть запущен с флагом `--enable-aggregator-routing=true`.
- **Pod Disruption Budget**: Рекомендуется установить PDB с `maxUnavailable: 1`, чтобы гарантировать доступность Metrics API во время обслуживания узлов.

### Сбор данных и разрешение
- **Периодичность (Resolution)**: По умолчанию Metrics Server опрашивает узлы каждые 60 секунд. Для ускорения реакции автоскейлинга рекомендуется установить `--metric-resolution=15s`.
- **Регистрация API**: Metrics Server регистрируется в `kube-aggregator` как `APIService`. Если сервис недоступен, вызовы к `metrics.k8s.io` будут завершаться ошибкой.

### Масштабирование ресурсов
Потребление ресурсов Metrics Server растет линейно вместе с размером кластера.
**Формула расчета (на каждые 100 узлов):**
- **CPU**: Базовые 100m + 1m на каждый узел.
- **Memory**: Базовые 200Mi + 2Mi на каждый узел.
Для автоматического управления ресурсами самого Metrics Server рекомендуется использовать VPA в режиме `Initial`.

## Практические сценарии

### Установка и настройка

**Шаг 1: Стандартная установка**
```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

**Шаг 2: Настройка для Production (Helm)**
Рекомендуется использовать Helm-чарт для гибкой настройки флагов и HA:
```bash
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm install metrics-server metrics-server/metrics-server \
  --namespace kube-system \
  --set args={--metric-resolution=15s,--kubelet-preferred-address-types=InternalIP} \
  --set replicas=2
```

**Параметры для отладки (Dev/Local):**
Если `kubelet` использует самоподписанные сертификаты (например, в Minikube или `kubeadm` без настройки сертификатов), добавьте флаг:
`--kubelet-insecure-tls` — отключает проверку TLS-сертификатов узлов (не рекомендуется для продакшена).

### Проверка статуса
После установки необходимо убедиться, что API-сервис доступен:
```bash
kubectl get apiservice v1beta1.metrics.k8s.io
# → NAME                      SERVICE                      AVAILABLE   AGE
# → v1beta1.metrics.k8s.io    kube-system/metrics-server   True        1m
```

### Использование kubectl top
Данные становятся доступны через 1-2 минуты после запуска.

**Просмотр ресурсов узлов:**
```bash
kubectl top nodes
# → NAME        CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → control-1   150m         7%     1400Mi          36%
```

**Просмотр ресурсов подов:**
```bash
kubectl top pods -A --sort-by=cpu
# → NAMESPACE     NAME                              CPU(cores)   MEMORY(bytes)
# → kube-system   metrics-server-74c698c975-f86p9   2m           18Mi
```

## Решение проблем

### Ошибка ScalingActive в HPA
Если HPA показывает статус `ScalingActive: False` с сообщением `failed to get CPU utilization`, проверьте:
1. Доступность Metrics Server через `kubectl top pods`.
2. Наличие `requests` у контейнеров в нагруженном Deployment (HPA не может рассчитать процент использования без заданных запросов).
3. Флаги Metrics Server (особенно `--kubelet-preferred-address-types`).

### Metrics Server не запускается (CrashLoopBackOff)
Частая причина в облачных средах — отсутствие разрешающих правил в Security Groups для порта 4443 (или 10250 для входящего трафика от агрегатора).

## Дополнительная информация

### Отличие от Prometheus
Metrics Server предоставляет только мгновенные значения (snapshot) и не хранит историю.
- **Metrics Server**: Используется ядром Kubernetes для HPA/VPA.
- **Prometheus**: Используется для долгосрочного мониторинга, алертинга и визуализации в Grafana.
Для масштабирования на основе кастомных метрик (например, очереди RabbitMQ) используется **[Prometheus Adapter](../../Prometheus/overview.md)** или **[KEDA](../Autoscaling/keda/keda_concepts.md)**.

### Смежные темы
- **[HPA: Автомасштабирование подов](../Autoscaling/HPA/index.md)** — использование метрик для репликации.
- **[VPA: Вертикальное масштабирование](../Autoscaling/vpa_detailed.md)** — оптимизация лимитов и запросов.
- **[Monitoring Architecture](./kubernetes-monitoring-logging-architecture.md)** — обзор всех слоев мониторинга.
