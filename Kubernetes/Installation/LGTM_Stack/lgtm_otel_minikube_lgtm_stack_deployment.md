# Развертывание стека LGTM на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)** (текущий)
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

---

## Перед началом работы

Данное руководство предполагает, что окружение уже подготовлено в соответствии с **[Предварительными требованиями](./lgtm_otel_minikube_prerequisites_environment.md)**. Перед продолжением убедитесь:

1. **Docker** запущен и доступен:
   ```bash
   docker info >/dev/null 2>&1 && echo "Docker OK" || echo "Docker не запущен"
   # → Expected: Docker OK
   ```

2. **Minikube** запущен с требуемыми ресурсами:
   ```bash
   minikube status
   # → Expected: Running
   
   minikube config get cpus
   # → Expected: 4 (или больше)
   
   minikube config get memory
   # → Expected: 8192 (или больше)
   ```

3. **kubectl** подключен к кластеру:
   ```bash
   kubectl cluster-info
   # → Expected: Kubernetes control plane is running at https://192.168.49.2:8443
   
   kubectl get nodes
   # → Expected: 1 node, status Ready
   ```

4. **Helm** установлен и может работать с кластером:
   ```bash
   helm version
   # → Expected: v3.16+ (или новее)
   
   helm list -A
   # → Expected: (пустой список или список уже установленных чартов)
   ```

5. **Ingress-контроллер** включен (необходим для доступа к сервисам):
   ```bash
   minikube addons list | grep ingress
   # → Expected: ingress: enabled
   ```

> **Важно:** Если какой-либо из пунктов не выполнен, вернитесь к **[Предварительным требованиям](./lgtm_otel_minikube_prerequisites_environment.md)** и завершите настройку окружения.

---

## Определения

**Стек LGTM** — это интегрированное решение для реализации [наблюдаемости (observability)](../../../Concepts/Observability_and_Monitoring/observability_definitions.md) от Grafana Labs. Название образовано от первых букв компонентов: **L**oki (логи), **G**rafana (визуализация), **T**empo (трассировки), **M**imir (метрики). В данном руководстве для работы с метриками используется Prometheus как более легковесная альтернатива для Minikube.

**kube-prometheus-stack** — основной Helm-чарт для развертывания экосистемы мониторинга на базе Prometheus Operator в Kubernetes. Включает в себя Prometheus, Alertmanager, Grafana и набор экспортеров (Node Exporter, kube-state-metrics). Подробнее: **[kube-prometheus-stack: Обзор](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**.

**Loki** — система сбора и хранения логов, оптимизированная по стоимости за счет индексации только метаданных. Подробнее: **[Loki: Обзор](../../../Loki/loki_overview.md)**.

**Tempo** — высокомасштабируемое распределенное хранилище трассировок. Подробнее: **[Tempo: Обзор](../../../Tempo/index.md)**.

**Grafana** — универсальная платформа для визуализации всех типов сигналов телеметрии (метрики, логи, трейсы). Подробнее: **[Grafana: Обзор](../../../Grafana/grafana_overview.md)**.

**Alertmanager** — компонент для обработки алертов, отправляемых Prometheus, их группировки, дедупликации и маршрутизации в каналы уведомлений.

**Grafana Alloy** — универсальный агент (наследник Grafana Agent) для сбора и передачи телеметрии, рекомендуемый для современных инсталляций (2025–2026 гг.). Подробнее: **[Grafana Alloy: Обзор](../../../Grafana/grafana_alloy_overview.md)**.

**Кросс-сигнальная корреляция** — механизм связывания различных типов данных: переход от метрик к трассировкам (**Exemplars**), извлечение TraceID из логов (**Derived Fields**) и поиск логов, соответствующих конкретным спанам (**Traces to Logs**).

---

## Основные концепции

### Архитектура стека LGTM в Minikube

```text
┌───────────────────────────────────────────────────────────────────┐
│                        Minikube Cluster                           │
│                                                                   │
│  ┌──────────────────┐     ┌─────────────────┐     ┌───────────┐   │
│  │    Grafana       │     │    Prometheus   │     │Alertmanager│   │
│  │   (UI + DS)      │◀────│  (Metrics DB)   │◀────│ (Alerts)  │   │
│  │                  │     │   + Exemplars   │     └───────────┘   │
│  │  ┌────────────┐  │     └────────┬────────┘           ▲         │
│  │  │    Loki    │  │              │                    │         │
│  │  │   (Logs)   │  │              ▼                    │         │
│  │  └────────────┘  │     ┌─────────────────┐    ┌──────┴─────┐   │
│  │  ┌────────────┐  │     │  Kube-State-    │    │   Node     │   │
│  │  │    Tempo   │  │     │    Metrics      │    │ Exporter   │   │
│  │  │  (Traces)  │  │     └─────────────────┘    └────────────┘   │
│  └────────┬─────────┘                                             │
│           │                                                       │
│           ▼                                                       │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │               Ingress Controller (nginx)                  │   │
│  │                                                           │   │
│  │  grafana.test -> Grafana:3000 (TLS: grafana-tls)          │   │
│  │  loki.test    -> Loki:3100    (TLS: loki-tls)             │   │
│  │  tempo.test   -> Tempo:3200   (TLS: tempo-tls)            │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### Состав и версии компонентов (на август 2026 г.)

| Компонент | Helm-чарт | Версия чарта | Репозиторий |
| :--- | :--- | :--- | :--- |
| **K8s Monitoring** | `kube-prometheus-stack` | 88.6.2 | `prometheus-community` |
| **Alertmanager** | (в составе стека) | 0.30.x | `prometheus-community` |
| **Kube-State-Metrics** | (в составе стека) | 2.15.x | `prometheus-community` |
| **Node Exporter** | (в составе стека) | 1.10.x | `prometheus-community` |
| **Loki** | `loki` | 18.11.4 | `oci://ghcr.io/grafana-community/helm-charts/loki` |
| **Tempo** (Monolithic) | `tempo` | 2.3.0 | `oci://ghcr.io/grafana-community/helm-charts/tempo` |
| **Grafana** | `grafana` (в составе стека) | 12.9.0 | `grafana` |

### Ресурсные требования

Для стабильной работы всего стека на Minikube рекомендуются следующие параметры:

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Prometheus** | 200m / 1000m | 512Mi / 2Gi |
| **Grafana** | 100m / 500m | 256Mi / 512Mi |
| **Loki** | 100m / 500m | 256Mi / 512Mi |
| **Tempo** | 100m / 500m | 128Mi / 512Mi |

**Минимальные параметры Minikube:** `--cpus 4 --memory 8192mb`. Для полноценного использования с распределенным Tempo и Loki рекомендуется `--memory 12288mb`.

---

## Практические сценарии

### Сценарий 1: Развертывание ядра мониторинга (Prometheus + Grafana)

**Цель:** Установить Prometheus Operator и Grafana с преднастроенными источниками данных и корреляцией.

#### Шаг 1: Подготовка репозиториев

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
# → "prometheus-community" has been added to your repositories

helm repo add grafana https://grafana.github.io/helm-charts
# → "grafana" has been added to your repositories

helm repo update
# → Hang tight while we grab the latest from your chart repositories...
# → ...Successfully got an update from the "grafana" chart repository
# → ...Successfully got an update from the "prometheus-community" chart repository
# → Update Complete. ⎈Happy Helming!⎈
```

#### Шаг 2: Установка kube-prometheus-stack

```bash
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --version 88.6.2 \
  -f - <<EOF
prometheus:
  prometheusSpec:
    enableFeatures:
      - exemplars
      - otlp-write-receiver
    retention: 2d
    storageSpec:
      volumeClaimTemplate:
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 5Gi

grafana:
  enabled: true
  adminPassword: prom-operator
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - grafana.test
    tls:
      - secretName: grafana-tls
        hosts:
          - grafana.test
  additionalDataSources:
    - name: Loki
      type: loki
      uid: loki
      url: http://loki.loki:3100
      jsonData:
        derivedFields:
          - datasourceUid: tempo
            matcherRegex: "traceID=(\\\\w+)"
            name: TraceID
            url: '\${__value.raw}'
    - name: Tempo
      type: tempo
      uid: tempo
      url: http://tempo.tempo:3200
      jsonData:
        serviceMap:
          datasourceUid: prometheus
        nodeGraph:
          enabled: true
        tracesToLogs:
          datasourceUid: loki
          filterByTraceID: true
          lokiSearch: true
        tracesToMetrics:
          datasourceUid: prometheus
          tags: '{job="agent-example-app"}'
        lokiSearch:
          datasourceUid: loki
    - name: Prometheus
      type: prometheus
      uid: prometheus
      url: http://prometheus-operated.monitoring:9090
      jsonData:
        exemplars:
          - datasourceUid: tempo
            internal: true
EOF
```

> **Примечание:** Включение `exemplars` позволяет переходить от точек на графиках метрик сразу к соответствующим трассировкам в Tempo при наличии TraceID в метках метрик (что делает OTel Collector). `otlp-write-receiver` позволяет Prometheus принимать метрики по протоколу OTLP напрямую.

**Валидация:**

```bash
# Проверка статуса релиза
helm status prometheus -n monitoring
# → NAME: prometheus
# → LAST DEPLOYED: ...
# → NAMESPACE: monitoring
# → STATUS: deployed

# Проверка запуска подов
kubectl get pods -n monitoring
# → Expected: Все поды в статусе Running (5-7 подов)

# Ожидание готовности Prometheus
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=prometheus -n monitoring --timeout=300s
```

---

### Сценарий 2: Развертывание Loki и Tempo с использованием OCI

**Цель:** Дополнить стек современными версиями систем хранения логов и трассировок.

#### Шаг 1: Установка Loki (OCI)

```bash
helm upgrade --install loki oci://ghcr.io/grafana-community/helm-charts/loki \
  --namespace loki \
  --create-namespace \
  --version 18.11.4 \
  -f - <<EOF
loki:
  auth_enabled: false
  commonConfig:
    replication_factor: 1
  storage:
    type: 'filesystem'
singleBinary:
  replicas: 1
read:
  replicas: 0
write:
  replicas: 0
backend:
  replicas: 0
gateway:
  enabled: true
  ingress:
    enabled: true
    hosts:
      - host: loki.test
        paths:
          - path: /
            pathType: Prefix
EOF
```

**Валидация Loki:**

```bash
# Проверка статуса релиза
helm status loki -n loki
# → NAME: loki
# → LAST DEPLOYED: ...
# → NAMESPACE: loki
# → STATUS: deployed

# Проверка запуска подов
kubectl get pods -n loki
# → Expected: loki-0 в статусе Running

# Проверка готовности Loki
kubectl exec -n loki loki-0 -- wget -qO- http://localhost:3100/ready
# → Ready
```

#### Шаг 2: Установка Tempo (OCI)

Для Minikube рекомендуется использовать монолитную версию Tempo (`tempo`), а не распределенную (`tempo-distributed`), для экономии ресурсов.

```bash
helm upgrade --install tempo oci://ghcr.io/grafana-community/helm-charts/tempo \
  --namespace tempo \
  --create-namespace \
  --version 2.3.0 \
  --set tempo.storage.trace.backend=local \
  --set tempo.resources.requests.cpu=100m \
  --set tempo.resources.requests.memory=128Mi
```

**Валидация Tempo:**

```bash
# Проверка статуса релиза
helm status tempo -n tempo
# → NAME: tempo
# → LAST DEPLOYED: ...
# → NAMESPACE: tempo
# → STATUS: deployed

# Проверка запуска подов
kubectl get pods -n tempo
# → Expected: tempo-0 в статусе Running

# Проверка готовности Tempo
kubectl exec -n tempo tempo-0 -- wget -qO- http://localhost:3200/ready
# → ok
```

---

### Сценарий 3: Настройка доступа и проверка корреляции

#### Шаг 1: Настройка локального DNS

```bash
echo "$(minikube ip) grafana.test" | sudo tee -a /etc/hosts
# → 192.168.49.2 grafana.test

echo "$(minikube ip) loki.test" | sudo tee -a /etc/hosts
# → 192.168.49.2 loki.test

echo "$(minikube ip) tempo.test" | sudo tee -a /etc/hosts
# → 192.168.49.2 tempo.test
```

**Валидация DNS:**

```bash
# Проверка разрешения имён
ping -c 1 grafana.test
# → PING grafana.test (192.168.49.2): 56 data bytes

ping -c 1 loki.test
# → PING loki.test (192.168.49.2): 56 data bytes

ping -c 1 tempo.test
# → PING tempo.test (192.168.49.2): 56 data bytes
```

#### Шаг 2: Валидация Data Sources

1. Зайти в Grafana (`https://grafana.test`, логин `admin`, пароль `prom-operator`).
2. Перейти в **Connections -> Data Sources**.
3. Проверить наличие трех источников данных: **Loki**, **Tempo**, **Prometheus**.
4. Нажать **Save & Test** для каждого источника:
   - **Loki:** ожидать сообщение "Data source successfully connected"
   - **Tempo:** ожидать сообщение "Data source successfully connected"
   - **Prometheus:** ожидать сообщение "Data source successfully connected"
5. В настройках Loki проверить наличие **Derived Fields** для связи с Tempo:
   - Перейти в настройки Loki -> **Derived Fields**
   - Убедиться, что существует поле с `datasourceUid: tempo` и `matcherRegex: "traceID=(\\\\w+)"`

**Проверка корреляции через API:**

```bash
# Проверка доступности Grafana
curl -sk https://grafana.test/api/health
# → {"commit":"...","database":"ok","version":"..."}

# Проверка доступности Loki
curl -sk https://loki.test/ready
# → Ready

# Проверка доступности Tempo
curl -sk https://tempo.test/ready
# → ok
```

---

## Очистка окружения (Cleanup)

Для полного удаления стека и освобождения ресурсов Minikube:

### Удаление компонентов стека

```bash
# Удаление в обратном порядке развертывания
helm uninstall tempo -n tempo
# → release "tempo" uninstalled

helm uninstall loki -n loki
# → release "loki" uninstalled

helm uninstall prometheus -n monitoring
# → release "prometheus" uninstalled
```

### Удаление пространств имён

```bash
kubectl delete namespace monitoring
# → namespace "monitoring" deleted

kubectl delete namespace loki
# → namespace "loki" deleted

kubectl delete namespace tempo
# → namespace "tempo" deleted
```

### Очистка DNS-записей

```bash
# Удаление записей из /etc/hosts (выполнить с правами root)
sudo sed -i '' '/grafana.test/d' /etc/hosts
sudo sed -i '' '/loki.test/d' /etc/hosts
sudo sed -i '' '/tempo.test/d' /etc/hosts
```

### Полная остановка Minikube (опционально)

```bash
minikube stop
# → Profiles "minikube" are stopped

# Для полного удаления кластера:
# minikube delete --all --purge
```

**Валидация очистки:**

```bash
# Проверка удаления релизов
helm list -A
# → Expected: пустой список (или без tempo, loki, prometheus)

# Проверка удаления подов
kubectl get pods -A | grep -E "monitoring|loki|tempo"
# → Expected: пустой вывод

# Проверка освобождения ресурсов
kubectl top nodes
# → Expected: снижение использования CPU/Memory
```

---

## Дополнительная информация

### Настройка персистентности (Persistence)

По умолчанию данные хранятся в эфемерных томах. Для сохранения данных при перезагрузке Minikube используйте `hostPath` или локальный `StorageClass`.

```yaml
# Пример включения persistence для Prometheus
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: standard
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
```

### Устранение неисправностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Prometheus OOMKilled** | Высокая интенсивность метрик | Увеличить memory limits до 2.5Gi в values.yaml |
| **Loki 404/502 в Grafana** | Неверный внутренний URL | Проверить доступность: `http://loki.loki:3100` (формат `<svc>.<ns>:<port>`) |
| **Нет ссылок на трейсы в логах** | Ошибка в `matcherRegex` | Проверить экранирование обратных слешей в YAML (нужно `\\\\w+`) |
| **Exemplars не отображаются** | `enableFeatures` не включен | Убедиться, что в конфигурации Prometheus есть `- exemplars` |
| **Ingress не работает** | Аддон nginx не включен | Выполнить `minikube addons enable ingress` |
| **Alertmanager не шлет алерты** | Ошибка маршрутизации | Проверить `kubectl logs` пода Alertmanager и `ConfigMap` |
| **Helm install зависает** | Проблемы с сетью или ресурсами | Проверить `kubectl get events -n monitoring` и увеличить таймаут |
| **Prometheus не скребет поды** | Отсутствует label `release` | Убедиться, что ServiceMonitor содержит лейбл, соответствующий селектору Prometheus |
| **Grafana не видит Data Sources** | ServiceAccount не имеет доступа | Проверить RBAC и ServiceAccount для Grafana |
| **Tempo не сохраняет трейсы** | Недостаточно дискового пространства | Проверить PV/PVC: `kubectl get pvc -n tempo` |
| **Loki не принимает логи** | Push- API недоступен | Убедиться, что gateway включен и Ingress настроен |
| **Поды в CrashLoopBackOff** | Ошибка конфигурации | Проверить логи: `kubectl logs <pod> -n <namespace>` |

### Диагностические команды

```bash
# Проверка статуса всех компонентов стека
kubectl get all -n monitoring
kubectl get all -n loki
kubectl get all -n tempo

# Проверка включенных фич в Prometheus
kubectl get prometheus -n monitoring -o yaml | grep enableFeatures -A 3
# → Expected:
#   enableFeatures:
#   - exemplars
#   - otlp-write-receiver

# Просмотр логов Grafana для отладки Data Sources
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana --tail=100

# Просмотр логов Loki
kubectl logs -n loki loki-0 --tail=100

# Просмотр логов Tempo
kubectl logs -n tempo tempo-0 --tail=100

# Проверка использования ресурсов
kubectl top pods -n monitoring
kubectl top pods -n loki
kubectl top pods -n tempo

# Проверка событий кластера
kubectl get events -n monitoring --sort-by='.lastTimestamp' | tail -20
kubectl get events -n loki --sort-by='.lastTimestamp' | tail -20
kubectl get events -n tempo --sort-by='.lastTimestamp' | tail -20

# Проверка PVC (персистентные тома)
kubectl get pvc -n monitoring
kubectl get pvc -n loki
kubectl get pvc -n tempo

# Port-forward для прямого доступа к сервисам (для отладки)
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 &
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80 &
kubectl port-forward -n loki svc/loki-gateway 3100:8080 &
kubectl port-forward -n tempo svc/tempo 3200:3200 &
```

### Ограничения и известные проблемы

| Ограничение | Описание | Обходной путь |
| :--- | :--- | :--- |
| **Эфемерное хранилище** | Данные теряются при перезапуске Minikube | Настроить Persistence (см. раздел "Настройка персистентности") |
| **Single-node кластер** | Нет реальной отказоустойчивости | Использовать Minikube с 3 нодами для тестирования scheduling |
| **Ограниченные ресурсы** | Возможны OOMKill при высокой нагрузке | Увеличить `--memory` до 12288mb или уменьшить retention |
| **Нет HA для Loki/Tempo** | SingleBinary режим, replication_factor=1 | Для production использовать распределенные версии |
| **Самоподписанные сертификаты** | Браузер будет предупреждать о недоверии | Добавить CA в доверенные системные сертификаты |
| **OTLP-приемник Prometheus** | Экспериментальная функция | Использовать Prometheus Remote Write для production |
| **Лимиты Minikube** | Нет поддержки некоторых K8s фич | Проверить совместимость: `minikube addons list` |

**Известные проблемы:**

1. **Конфликт портов:** Если порты 3000 (Grafana) или 9090 (Prometheus) заняты, используйте port-forward с другими портами.

2. **Проблемы с OCI-чартами:** Некоторые версии Helm могут иметь проблемы с OCI-репозиториями. Убедитесь, что Helm >= 3.8.0.

3. **Долгий старт Loki:** При первом запуске Loki может занимать 2-3 минуты на инициализацию базы данных.

4. **Exemplars без OTel:** Для работы Exemplars необходимо настроить OTel Collector или приложение, добавляющее TraceID в метрики.

### Лучшие практики для Minikube

#### Управление ресурсами

1. **Установка лимитов ресурсов:** Всегда задавайте `requests` и `limits` для каждого компонента для предотвращения OOMKill и гарантии доступности.

2. **Мониторинг использования:** Регулярно проверяйте потребление ресурсов:
   ```bash
   kubectl top nodes
   kubectl top pods -A --sort-by=memory
   ```

3. **Настройка retention:** Для Minikube рекомендуется короткий retention (1-2 дня) для экономии дискового пространства.

#### Конфигурация

4. **Использование values.yaml:** Выносите конфигурацию в отдельные файлы `values.yaml` вместо инлайн-параметров для версионирования и воспроизводимости.

5. **Версионирование чартов:** Всегда указывайте конкретную версию чарта (`--version X.Y.Z`) для предсказуемых обновлений.

6. **Пространства имен:** Используйте отдельные namespaces для каждого компонента (`monitoring`, `loki`, `tempo`) для изоляции и удобства управления.

#### Безопасность

7. **Смена паролей:** Измените стандартный пароль `prom-operator` на собственный перед использованием.

8. **Network Policies:** В Minikube можно включить Network Policies для тестирования security-конфигураций.

9. **RBAC:** Настройте принцип наименьших привилегий для ServiceAccount компонентов стека.

#### Развитие

10. **GitOps:** Храните конфигурации Helm в Git для отслеживания изменений.

11. **Тестирование изменений:** Используйте `helm diff` перед обновлением для предварительного просмотра изменений:
    ```bash
    helm plugin install https://github.com/databus23/helm-diff
    helm diff upgrade prometheus prometheus-community/kube-prometheus-stack -f values.yaml
    ```

12. **Резервное копирование:** Для персистентных данных настройте регулярные снимки (Snapshots) если используете cloud-провайдер Minikube.

### См. также
- **[Grafana Alloy: Современный агент для LGTM](../../../Grafana/grafana_alloy_overview.md)**
- **[OpenTelemetry: Интеграция с LGTM](../../../OpenTelemetry/opentelemetry_overview.md)**
- **[Kube-Prometheus-Stack: Продвинутая настройка](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**

### Связанные материалы SSoT

- **[kube-prometheus-stack: Конфигурация](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**
- **[Loki: Практические сценарии](../../../Loki/loki_overview.md)**
- **[Tempo: Операции и TraceQL](../../../Tempo/index.md)**
- **[Grafana: Визуализация](../../../Grafana/grafana_overview.md)**

### Безопасность и хранение данных

> **Внимание:** Текущая конфигурация в базовом варианте использует эфемерное хранилище (emptyDir). После перезапуска Minikube данные будут потеряны, если не настроена персистентность.

| Аспект | Данное руководство | Production |
| :--- | :--- | :--- |
| **Persistence** | Отключена по умолчанию | PersistentVolumes (SSD) или S3-бакеты |
| **Метрики** | Prometheus (single) | Grafana Mimir (Distributed) |
| **Auth** | Базовая (admin/pass) | OIDC (Keycloak, Okta, Google) |
| **Сбор данных** | Скрейпинг Prometheus | **[Grafana Alloy](../../../Grafana/grafana_alloy_overview.md)** |

---

**Навигация по руководству:**

- **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)** (назад)
- **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** (вперед)
