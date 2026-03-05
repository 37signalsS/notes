# Goldilocks

## 1. Определения

**Goldilocks** — это инструмент для Kubernetes от Fairwinds, который автоматически генерирует рекомендации по `resources.limits` и `resources.requests` для подов на основе их реального потребления ресурсов. Инструмент использует метрики Vertical Pod Autoscaler (VPA) для определения оптимальных значений, помогая достичь «золотой середины» между избыточным выделением и нехваткой ресурсов.

## 2. Основные концепции

### Принцип работы

1. **Развёртывание в кластере:** Goldilocks устанавливается как контроллер в кластер Kubernetes (обычно через Helm).
2. **Сбор метрик:** Контроллер анализирует метрики потребления CPU и памяти подов через Metrics Server или Prometheus.
3. **Генерация рекомендаций:** На основе исторических данных генерируются предложения для `resources.limits` и `resources.requests`.
4. **Визуализация:** Рекомендации отображаются в веб-интерфейсе или через `kubectl`.

### Режимы работы (UpdateMode)

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| **`Off`** | Только сбор рекомендаций без применения | Начальный этап анализа, production-системы |
| **`Initial`** | Применение рекомендаций только при создании новых подов | Постепенное внедрение |
| **`Recreate`** | Применение рекомендаций с перезапуском существующих подов | Тестовые окружения, maintenance windows |

### Интеграция с VPA

Goldilocks использует VPA как источник рекомендаций, но предоставляет более удобный интерфейс:

- **VPA** — низкоуровневый API, требует ручной настройки
- **Goldilocks** — высокоуровневая абстракция с веб-UI и упрощённым управлением

**Важно:** Не используйте Goldilocks и прямой VPA одновременно для одних и тех же workload'ов — это вызовет конфликты.

### Фильтрация и выборочный анализ

Поддерживается фильтрация по:
- **Namespace** — анализ конкретных пространств имён
- **Labels** — выборочный анализ по лейблам (например, `app=frontend`)
- **Workload type** — фильтрация по типу рабочей нагрузки

## 3. Практические сценарии

### 3.1. Установка через Helm

```bash
# Добавление репозитория
helm repo add fairwinds-stable https://charts.fairwinds.com/stable
helm repo update

# Установка Goldilocks
helm install goldilocks fairwinds-stable/goldilocks \
  --namespace goldilocks \
  --create-namespace \
  --set controller.rbac.clusterRoleName=goldilocks-clusterrole
```

### 3.2. Включение анализа для namespace

Для активации сбора рекомендаций в конкретном namespace добавьте лейбл:

```bash
kubectl label namespace my-namespace goldilocks.fairwinds.com/enabled=true
```

### 3.3. Просмотр рекомендаций

**Через веб-интерфейс:**

```bash
# Проброс порта для доступа к UI
kubectl port-forward svc/goldilocks-dashboard -n goldilocks 8080:80
```

Откройте `http://localhost:8080` в браузере.

**Через kubectl:**

```bash
# Просмотр VPA объектов, созданных Goldilocks
kubectl get vpa --all-namespaces -o wide

# Детальная информация по рекомендациям
kubectl describe vpa <vpa-name> -n <namespace>
```

### 3.4. Применение рекомендаций

**Автоматическое применение (для тестовых окружений):**

```yaml
# annotations в Deployment
annotations:
  goldilocks.fairwinds.com/enabled: "true"
  goldilocks.fairwinds.com/update-mode: "Recreate"
```

**Ручное применение (рекомендуется для production):**

1. Просмотрите рекомендации в UI или через `kubectl describe vpa`
2. Скопируйте рекомендованные значения
3. Обновите манифест Deployment:

```yaml
spec:
  template:
    spec:
      containers:
      - name: myapp
        resources:
          requests:
            cpu: 100m      # из рекомендаций Goldilocks
            memory: 256Mi  # из рекомендаций Goldilocks
          limits:
            cpu: 200m      # из рекомендаций Goldilocks
            memory: 512Mi  # из рекомендаций Goldilocks
```

### 3.5. Исключение namespace'ов

Для исключения системных namespace'ов из анализа:

```bash
# Исключение kube-system
kubectl label namespace kube-system goldilocks.fairwinds.com/enabled-
```

## 4. Дополнительная информация

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.20+ | Проверено до 1.32 |
| Metrics Server | 0.6+ | Обязателен для сбора метрик |
| Helm | 3.0+ | Для установки через Helm |

### Ресурсы контроллера

```yaml
resources:
  requests:
    cpu: 50m
    memory: 64Mi
  limits:
    cpu: 200m
    memory: 256Mi
```

### Безопасность

- Не вносит изменения в манифесты без явного указания режима `Recreate` или `Initial`
- Требует RBAC-права на чтение метрик и создание VPA объектов
- Рекомендуется запускать в отдельном namespace

### Ограничения

- Не работает с подами, управляемыми другими операторами авто scaling'а
- Требует установленного Metrics Server или Prometheus
- Рекомендации основаны на исторических данных (24 часа по умолчанию)

### Связанные документы

- **[VPA](../Autoscaling/vpa_detailed.md)** — подробная информация о Vertical Pod Autoscaler
- **[HPA](../Autoscaling/hpa_detailed.md)** — горизонтальное масштабирование
- **[Metrics Server](../MonitoringLogging/metrics-server.md)** — источник метрик для VPA/Goldilocks
- **[Prometheus](../../Prometheus/prometheus_api.md)** — система мониторинга

### Репозиторий и документация

- [GitHub: FairwindsOps/goldilocks](https://github.com/FairwindsOps/goldilocks)
- [Документация Fairwinds](https://goldilocks.docs.fairwinds.com/)
