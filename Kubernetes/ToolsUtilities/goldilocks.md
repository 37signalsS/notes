# Goldilocks

## Определения

**Goldilocks** — это инструмент для Kubernetes от Fairwinds, который автоматически генерирует рекомендации по `resources.limits` и `resources.requests` для подов на основе их реального потребления ресурсов. Инструмент использует метрики Vertical Pod Autoscaler (VPA) для определения оптимальных значений, помогая достичь «золотой середины» между избыточным выделением и нехваткой ресурсов.

## Основные концепции

### Принцип работы

1. **Развёртывание в кластере:** Goldilocks устанавливается как контроллер (через Helm или манифесты).
2. **Сбор метрик:** Контроллер анализирует метрики потребления CPU и памяти подов через Metrics Server или Prometheus (с адаптером).
3. **Генерация рекомендаций:** На основе исторических данных VPA в режиме `Recommendation Mode` (UpdateMode: "Off") генерирует предложения для `resources.limits` и `resources.requests`.
4. **Визуализация:** Рекомендации отображаются в веб-интерфейсе, разделяясь на типы QoS-классов (Guaranteed и Burstable), или доступны через `kubectl`.

### Режимы работы (UpdateMode)

Хотя Goldilocks чаще всего используется в режиме визуализации, он позволяет управлять поведением VPA:

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| **`Off`** | Только сбор рекомендаций без изменения подов | Стандарт для Goldilocks и production-систем |
| **`Initial`** | Применение рекомендаций только при создании новых подов | Постепенное внедрение без перезапуска живых подов |
| **`Recreate`** | Применение рекомендаций с перезапуском существующих подов | Тестовые окружения или окна обслуживания |

### QoS-классы в рекомендациях

Инструмент предоставляет рекомендации для двух стратегий управления ресурсами:
- **Guaranteed (Гарантированный):** Устанавливает `requests` равными `limits`. Это предотвращает вытеснение подов и гарантирует выделение ресурсов, что критично для высоконагруженных приложений.
- **Burstable (С возможностью всплесков):** Устанавливает `requests` ниже, чем `limits`. Это позволяет экономить ресурсы кластера за счет более плотной упаковки (overcommitting), но несет риск троттлинга при нехватке физических ресурсов на узле.

### Интеграция с VPA

Goldilocks использует VPA как вычислительный движок, предоставляя над ним удобную абстракцию и UI.

**Важные нюансы:**
- **Раздельное управление:** Рекомендуется устанавливать VPA отдельно от Goldilocks. Это гарантирует, что при удалении или обновлении панели управления данные и объекты VPA сохранятся.
- **Конфликты:** Запрещено использовать Goldilocks и прямой (ручной) VPA для одного и того же workload — это приведет к непредсказуемому поведению и конфликтам в API.

### Фильтрация и выборочный анализ

Goldilocks позволяет гибко настраивать область анализа:
- **Namespace:** Активируется только в тех пространствах имен, где установлен соответствующий лейбл.
- **Labels:** Можно настроить фильтрацию конкретных объектов внутри namespace.
- **Workload type:** Анализирует Deployment, StatefulSet, DaemonSet и другие стандартные типы контроллеров.

## Практические сценарии

### Установка через Helm

```bash
# Добавление репозитория
helm repo add fairwinds-stable https://charts.fairwinds.com/stable
# → "fairwinds-stable" has been added to your repositories

helm repo update
# → Hang tight while we grab the latest from your chart repositories...
# → ...Successfully got an update from the "fairwinds-stable" chart repository

# Установка Goldilocks (без встроенного VPA, если он уже есть в кластере)
helm install goldilocks fairwinds-stable/goldilocks \
  --namespace goldilocks \
  --create-namespace \
  --set controller.rbac.clusterRoleName=goldilocks-clusterrole
# → NAME: goldilocks
# → STATUS: deployed
# → NAMESPACE: goldilocks
```

**Примечание:** С версии v4.15.0 образы перемещены в Google Artifact Registry: `us-docker.pkg.dev/fairwinds-ops/oss/goldilocks`.

### Включение анализа для namespace

Для активации сбора данных добавьте лейбл на пространство имен:

```bash
kubectl label namespace my-namespace goldilocks.fairwinds.com/enabled=true
# → namespace/my-namespace labeled
```

### Просмотр рекомендаций

**Через веб-интерфейс:**

```bash
# Проброс порта для доступа к UI
kubectl port-forward svc/goldilocks-dashboard -n goldilocks 8080:80
# → Forwarding from 127.0.0.1:8080 -> 80
```
После этого интерфейс доступен по адресу `http://localhost:8080`.

**Через kubectl:**

```bash
# Просмотр всех VPA объектов, созданных инструментом
kubectl get vpa --all-namespaces -o wide
# → NAMESPACE      NAME                MODE   CPU    MEM       AGE
# → my-namespace   myapp-goldilocks    Off    150m   512Mi     12h

# Детальное изучение рекомендаций конкретного объекта
kubectl describe vpa myapp-goldilocks -n my-namespace
# → Target: CPU: 120m, Memory: 300Mi
# → Uncapped Target: CPU: 120m, Memory: 300Mi
# → Lower Bound: CPU: 100m, Memory: 250Mi
# → Upper Bound: CPU: 500m, Memory: 1Gi
```

### Применение рекомендаций

**Автоматическое применение (только для Dev/Test):**

Добавьте аннотации в спецификацию Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  annotations:
    goldilocks.fairwinds.com/enabled: "true"
    goldilocks.fairwinds.com/update-mode: "Recreate" # Включает авто-обновление
spec:
  # ... остальная часть манифеста
```

**Ручное применение (рекомендуется для Production):**

1. Ознакомьтесь с `Target` значениями в UI или через `describe vpa`.
2. Обновите манифест приложения:

```yaml
spec:
  template:
    spec:
      containers:
      - name: myapp
        resources:
          requests:
            cpu: 120m      # Значение из Goldilocks Target
            memory: 300Mi  # Значение из Goldilocks Target
          limits:
            cpu: 500m      # Значение из Goldilocks Upper Bound или ваша политика
            memory: 1Gi    # Значение из Goldilocks Upper Bound или ваша политика
```

### Исключение и тонкая настройка

**Исключение namespace:**
Удалите лейбл, если анализ больше не требуется:
```bash
kubectl label namespace kube-system goldilocks.fairwinds.com/enabled-
# → namespace/kube-system unlabeled
```

**Исключение контейнеров:**
Если в поде есть служебные контейнеры (sidecars), их можно исключить из анализа через аннотацию:
`goldilocks.fairwinds.com/exclude-containers: "istio-proxy,linkerd-proxy"`.

## Лучшие практики

1. **Правило 24 часов:** VPA требуется время для накопления статистики. Не принимайте решений на основе данных, собранных менее чем за полные сутки работы приложения под нагрузкой.
2. **Конфликт с HPA:** Если Horizontal Pod Autoscaler настроен на масштабирование по CPU или памяти, VPA/Goldilocks **обязательно** должен быть в режиме `UpdateMode: "Off"`. Совместное автоматическое масштабирование ресурсов (Vertical) и количества реплик (Horizontal) по одним и тем же метрикам приведет к нестабильности.
3. **Staging перед Production:** Всегда проверяйте новые лимиты в тестовой среде. Занижение ресурсов может привести к OOM (Out of Memory) или деградации производительности.
4. **Регулярный аудит:** Профили нагрузки меняются с выходом новых версий кода. Проводите ревизию рекомендаций Goldilocks раз в квартал.

## Дополнительная информация

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.25+ | Полная поддержка до 1.32 включительно |
| Metrics Server | 0.6+ | Критически важен для передачи метрик в VPA |
| Helm | 3.0+ | Для стандартной установки |
| VPA | 0.8+ | Должен быть предварительно развернут в кластере |

### Ресурсы контроллера (рекомендуемые)

Для стабильной работы самого Goldilocks в средних кластерах:
```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 300m
    memory: 512Mi
```

### Безопасность

- **RBAC:** Контроллер требует прав на чтение метрик, ресурсов (deployments, pods) и управление объектами `verticalpodautoscalers.autoscaling.k8s.io`.
- **Изоляция:** Рекомендуется запускать в выделенном namespace `goldilocks` с ограниченными сетевыми политиками.
- **Immutable:** По умолчанию инструмент не изменяет существующие поды, работая как пассивный аудитор.

### Ограничения

- **Batch Workloads:** Плохо подходит для короткоживущих задач (Jobs/CronJobs), так как VPA не успевает собрать репрезентативные данные.
- **Зависимость от метрик:** При сбоях Metrics Server или Prometheus рекомендации перестают обновляться.

### Смотрите также

- [VPA](../Autoscaling/vpa_detailed.md) — глубокое погружение в механизмы Vertical Pod Autoscaler.
- [Metrics Server](../MonitoringLogging/metrics-server.md) — установка и настройка источника данных.
- [Официальная документация Fairwinds](https://goldilocks.docs.fairwinds.com/) — актуальные параметры конфигурации и Roadmap.
