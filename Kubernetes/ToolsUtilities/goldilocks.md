# Goldilocks — рекомендации по ресурсам Kubernetes

## Определения

**Goldilocks** (FairwindsOps/goldilocks) — инструмент для Kubernetes, который автоматически генерирует рекомендации по `resources.limits` и `resources.requests` для подов на основе их реального потребления ресурсов. Инструмент использует метрики Vertical Pod Autoscaler (VPA) для определения оптимальных значений, помогая достичь «золотой середины» между избыточным выделением и нехваткой ресурсов.

На 2026 год Goldilocks является стандартом де-факто для визуализации right-sizing рекомендаций в On-prem и гибридных кластерах Kubernetes.

**Актуальная версия:** v4.16.1 (август 2026).

**Лицензия:** Apache-2.0. Звёзды: ~3.3k.

**Документация:** [goldilocks.docs.fairwinds.com](https://goldilocks.docs.fairwinds.com/)

---

## Основные концепции

### Архитектура и принцип работы

Goldilocks не является автономным вычислительным движком — он использует VPA как «бэкенд» для расчёта рекомендаций:

```
Goldilocks Controller
    ↓ (создаёт VPA объекты в Managed Namespaces)
VPA Recommender
    ↓ (опрашивает Metrics Server / Prometheus)
Расчёт Target, LowerBound, UpperBound
    ↓
Goldilocks Dashboard (UI) / goldilocks summary (CLI/JSON)
```

**Ключевой принцип:** Goldilocks создаёт VPA-объекты в режиме `Off` (только рекомендации, без автоприменения). Это делает его безопасным для production — ни один под не будет перезапущен без явного решения оператора.

### Режимы работы (UpdateMode)

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| **`Off`** | Только сбор рекомендаций без изменения подов | Стандарт для Goldilocks и production-систем |
| **`Initial`** | Применение рекомендаций только при создании новых подов | Постепенное внедрение без перезапуска живых подов |
| **`Recreate`** | Применение рекомендаций с перезапуском существующих подов | Тестовые окружения или окна обслуживания |

> **Важно:** Режим `Recreate` для Goldilocks рекомендуется только для Dev/Test. В production-среде всегда используйте `Off`.

### QoS-классы в рекомендациях

- **Guaranteed (Гарантированный):** Устанавливает `requests` равными `limits`. Это предотвращает вытеснение подов и гарантирует выделение ресурсов, что критично для высоконагруженных приложений.
- **Burstable (С возможностью всплесков):** Устанавливает `requests` ниже, чем `limits`. Это позволяет экономить ресурсы кластера за счёт более плотной упаковки (overcommitting), но несёт риск троттлинга при нехватке физических ресурсов на узле.

### Интеграция с VPA и In-Place Resize

Goldilocks использует VPA как вычислительный движок, предоставляя над ним удобную абстракцию и UI.

**Важные нюансы:**
- **In-Place Pod Resizing (K8s 1.35+):** В современных кластерах рекомендации Goldilocks могут применяться без перезапуска подов благодаря стабильной поддержке изменения ресурсов «на лету» (при поддержке со стороны VPA и контейнерного рантайма).
- **Поддержка cgroup v2:** Начиная с версии v4.15.0 Goldilocks полностью совместим с cgroup v2, что является обязательным требованием для Kubernetes v1.35+.
- **Раздельное управление:** Рекомендуется устанавливать VPA отдельно от Goldilocks. Это гарантирует, что при удалении или обновлении панели управления данные и объекты VPA сохранятся.
- **Конфликты:** Запрещено использовать Goldilocks и прямой (ручной) VPA для одного и того же workload — это приведёт к непредсказуемому поведению и конфликтам в API.
- **VPA Recommender only:** При установке VPA через Goldilocks-чарт устанавливается **только VPA Recommender** (без Updater и Admission Controller). Это безопасно — Admission Webhook может вызвать неожиданные последствия в кластере, если не настроен корректно.

### Фильтрация и выборочный анализ

Goldilocks позволяет гибко настраивать область анализа:

- **Namespace:** Активируется только в тех пространствах имен, где установлен соответствующий лейбл.
- **Labels:** Можно настроить фильтрацию конкретных объектов внутри namespace.
- **Workload type:** Анализирует Deployment, StatefulSet, DaemonSet и другие стандартные типы контроллеров (все, содержащие `spec.template.spec.containers[]`).
- **Container exclusions:** Можно исключить sidecar-контейнеры (istio-proxy, linkerd-proxy) из анализа.
- **Prometheus (опционально):** VPA не требует Prometheus, но его использование может обеспечить более точные результаты за счёт расширенных метрик.

---

## Практические сценарии

### Установка

#### Метод 1: Helm (рекомендуется)

```bash
# Добавление репозитория
helm repo add fairwinds-stable https://charts.fairwinds.com/stable
# -> "fairwinds-stable" has been added to your repositories

helm repo update
# -> Hang tight while we grab the latest from your chart repositories...
# -> ...Successfully got an update from the "fairwinds-stable" chart repository

# Установка Goldilocks (без встроенного VPA, если он уже есть в кластере)
helm install goldilocks fairwinds-stable/goldilocks \
  --namespace goldilocks \
  --create-namespace \
  --set controller.rbac.clusterRoleName=goldilocks-clusterrole
# -> NAME: goldilocks
# -> STATUS: deployed
# -> NAMESPACE: goldilocks
```

**Примечание:** С версии v4.15.0 образы перемещены в Google Artifact Registry: `us-docker.pkg.dev/fairwinds-ops/oss/goldilocks`. Образы подписаны (cosign) и имеют неизменяемые теги.

#### Метод 2: YAML-манифесты

```bash
# Клонирование репозитория
git clone https://github.com/FairwindsOps/goldilocks.git
cd goldilocks

# Создание namespace и применение манифестов
kubectl create namespace goldilocks
kubectl -n goldilocks apply -f hack/manifests/controller
kubectl -n goldilocks apply -f hack/manifests/dashboard
```

Этот метод полезен для air-gapped сред или когда Helm недоступен.

### Включение анализа для namespace

Для активации сбора данных добавьте лейбл на пространство имен:

```bash
kubectl label namespace my-namespace goldilocks.fairwinds.com/enabled=true
# -> namespace/my-namespace labeled
```

**Включение VPA-режима через label namespace** (продвинутая настройка):

```bash
# Установка updateMode для всех VPA в namespace
kubectl label ns my-namespace goldilocks.fairwinds.com/vpa-update-mode="auto"

# Установка resource policy через annotation
kubectl annotate ns my-namespace \
  goldilocks.fairwinds.com/vpa-resource-policy='{
    "containerPolicies": [{
      "containerName": "nginx",
      "minAllowed": {"cpu": "250m", "memory": "100Mi"},
      "maxAllowed": {"cpu": "2000m", "memory": "2048Mi"}
    }, {
      "containerName": "istio-proxy",
      "mode": "Off"
    }]
  }'
```

**Управление на уровне workload** (приоритет над namespace-лейблами):

```bash
# Установка updateMode для конкретного Deployment
kubectl annotate deployment myapp \
  goldilocks.fairwinds.com/vpa-update-mode="Recreate"

# Исключение sidecar-контейнеров из анализа
kubectl label deployment myapp \
  goldilocks.fairwinds.com/exclude-containers="linkerd-proxy,istio-proxy"
```

### Просмотр рекомендаций

**Через веб-интерфейс:**

```bash
# Проброс порта для доступа к UI
kubectl port-forward svc/goldilocks-dashboard -n goldilocks 8080:80
# -> Forwarding from 127.0.0.1:8080 -> 80
```

После этого интерфейс доступен по адресу `http://localhost:8080`.

**Через kubectl:**

```bash
# Просмотр всех VPA объектов, созданных инструментом
kubectl get vpa --all-namespaces -o wide
# -> NAMESPACE      NAME                MODE   CPU    MEM       AGE
# -> my-namespace   myapp-goldilocks    Off    150m   512Mi     12h

# Детальное изучение рекомендаций конкретного объекта
kubectl describe vpa myapp-goldilocks -n my-namespace
# -> Target: CPU: 120m, Memory: 300Mi
# -> Uncapped Target: CPU: 120m, Memory: 300Mi
# -> Lower Bound: CPU: 100m, Memory: 250Mi
# -> Upper Bound: CPU: 500m, Memory: 1Gi
```

**Через CLI (JSON-вывод):**

```bash
# Генерация сводки всех рекомендаций в JSON
goldilocks summary
# Вывод JSON-объекта для интеграции с другими инструментами

# Фильтрация по namespace
goldilocks summary -n my-namespace

# Исключение sidecar-контейнеров из сводки
goldilocks summary --exclude-containers=istio-proxy,linkerd-proxy
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
```bash
kubectl label namespace kube-system goldilocks.fairwinds.com/enabled-
# -> namespace/kube-system unlabeled
```

**Исключение контейнеров через annotation:**
```yaml
metadata:
  annotations:
    goldilocks.fairwinds.com/exclude-containers: "istio-proxy,linkerd-proxy"
```

**Исключение контейнеров через label (推薦):**
```bash
kubectl label deployment myapp \
  goldilocks.fairwinds.com/exclude-containers="istio-proxy,linkerd-proxy"
```

**Исключение контроллеров (CLI):**
```bash
# Исключение Job и CronJob из автоматического создания VPA
goldilocks controller --ignore-controller-kind=Job,CronJob
```

### Использование CLI

Goldilocks предоставляет CLI-утилиту, которая запускается как внутри кластера (Docker-контейнер), так и локально.

**Установка CLI:**

```bash
# Linux (amd64)
curl -L "https://github.com/FairwindsOps/goldilocks/releases/download/v4.16.1/goldilocks_4.16.1_linux_amd64.tar.gz" \
  > goldilocks.tar.gz
tar -xvf goldilocks.tar.gz
sudo mv goldilocks /usr/local/bin/

# Проверка версии
goldilocks version
```

**Доступные команды:**

| Команда | Описание |
| :--- | :--- |
| `controller` | Запуск контроллера (внутри кластера). Создаёт VPA для лейблованных namespace. |
| `dashboard` | Запуск веб-интерфейса (по умолчанию порт 8080). |
| `summary` | Генерация сводки рекомендаций в JSON. |
| `create-vpas` | Ручное создание VPA для указанного namespace. |
| `delete-vpas` | Удаление всех VPA, созданных Goldilocks, в namespace. |
| `version` | Вывод текущей версии. |

**Флаги контроллера:**

| Флаг | Описание |
| :--- | :--- |
| `--on-by-default` | Создавать VPA во **всех** namespace (без необходимости лейблов). |
| `--include-namespaces` | Создавать VPA в указанных namespace (в дополнение к лейблованным). |
| `--exclude-namespaces` | Исключить указанные namespace (используется с `--on-by-default`). |
| `--ignore-controller-kind` | Игнорировать указанные типы контроллеров (например, `Job,CronJob`). |
| `--kubeconfig` | Путь к kubeconfig (по умолчанию `$HOME/.kube/config`). |
| `-v` | Уровень детализации логов (verbosity). |

**Примеры:**

```bash
# Запуск контроллера с включением для всех namespace
goldilocks controller --on-by-default

# Исключение системных namespace
goldilocks controller --on-by-default --exclude-namespaces=kube-system,kube-public

# Ручное создание VPA для конкретного namespace
goldilocks create-vpas -n my-namespace

# Удаление всех VPA, созданных Goldilocks
goldilocks delete-vpas -n my-namespace

# Запуск dashboard на порту 9090
goldilocks dashboard --port=9090
```

---

## Лучшие практики

1. **Правило 24 часов:** VPA требуется время для накопления статистики. Не принимайте решений на основе данных, собранных менее чем за полные сутки работы приложения под нагрузкой.
2. **Конфликт с HPA:** Если Horizontal Pod Autoscaler настроен на масштабирование по CPU или памяти, VPA/Goldilocks **обязательно** должен быть в режиме `UpdateMode: "Off"`. Совместное автоматическое масштабирование ресурсов (Vertical) и количества реплик (Horizontal) по одним и тем же метрикам приведёт к нестабильности.
3. **Staging перед Production:** Всегда проверяйте новые лимиты в тестовой среде. Занижение ресурсов может привести к OOM (Out of Memory) или деградации производительности.
4. **Регулярный аудит:** Профили нагрузки меняются с выходом новых версий кода. Проводите ревизию рекомендаций Goldilocks раз в квартал.
5. **PDB обязателен:** При включении VPA в активных режимах (`Initial`, `Recreate`) всегда настраивайте [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md) для защиты от одновременного удаления всех реплик.
6. **ResourceQuota:** Перед включением VPA в режиме `Auto` убедитесь, что ResourceQuota неймспейса позволяет увеличение `requests`.
7. **FinOps:** Goldilocks — ключевой инструмент для FinOps-аналитики. Рекомендации позволяют выявить over-provisioning (завышенные requests, раздувающие кластер) и under-provisioning (заниженные requests, приводящие к троттлингу).

---

## Дополнительная информация

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.25+ | Полная поддержка до 1.35+ включительно |
| Metrics Server | 0.6+ | Критически важен для передачи метрик в VPA |
| Helm | 3.0+ | Для стандартной установки (метод 1) |
| VPA | 0.8+ | Должен быть предварительно развёрнут в кластере |
| Go | 1.17+ | Для сборки из исходников (CLI) |

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

- **RBAC:** Контроллер требует прав на чтение метрик, ресурсов (deployments, pods, statefulsets, daemonsets) и управление объектами `verticalpodautoscalers.autoscaling.k8s.io`.
- **Изоляция:** Рекомендуется запускать в выделенном namespace `goldilocks` с ограниченными сетевыми политиками.
- **Immutable:** По умолчанию инструмент не изменяет существующие поды, работая как пассивный аудитор.
- **Pod Security:** Убедитесь, что PSP/PSA для namespace `goldilocks` позволяет запуск контейнеров от непривилегированного пользователя.

### Ограничения

- **Batch Workloads:** Плохо подходит для короткоживущих задач (Jobs/CronJobs), так как VPA не успевает собрать репрезентативные данные. Используйте `--ignore-controller-kind=Job,CronJob`.
- **Зависимость от метрик:** При сбоях Metrics Server или Prometheus рекомендации перестают обновляться.
- **CLI:** CLI-режим рекомендуется только для тестирования. Для production используйте controller (Docker-контейнер), который автоматически отслеживает изменения и поддерживает несколько namespace.

### Fairwinds Ecosystem

Goldilocks — часть экосистемы Open Source инструментов от Fairwinds:

| Инструмент | Назначение |
| :--- | :--- |
| **[Polaris](https://github.com/FairwindsOps/Polaris)** | Аудит, исполнение и построение политик для ресурсов Kubernetes (20+ встроенных проверок). |
| **[Pluto](https://github.com/FairwindsOps/Pluto)** | Обнаружение Deprecated API в кластере (подготовка к апгрейду). |
| **[Nova](https://github.com/FairwindsOps/Nova)** | Проверка доступности обновлений для Helm-чартов. |
| **[rbac-manager](https://github.com/FairwindsOps/rbac-manager)** | Упрощённое управление RBAC в кластерах. |

### Смотрите также

- [VPA](../Autoscaling/vpa_detailed.md) — глубокое погружение в механизмы Vertical Pod Autoscaler.
- [Metrics Server](../MonitoringLogging/metrics-server.md) — установка и настройка источника данных.
- [In-Place Pod Resize](../Autoscaling/in_place_pod_resize.md) — изменение ресурсов без перезапуска подов.
- [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md) — защита при обновлении VPA.
- [QoS и управление ресурсами](../Scheduling/qos_limit_and_requests.md) — как работают requests/limits.
- [Официальная документация Fairwinds](https://goldilocks.docs.fairwinds.com/) — актуальные параметры конфигурации и Roadmap.
- [GitHub: FairwindsOps/goldilocks](https://github.com/FairwindsOps/goldilocks) — исходный код, релизы, CHANGELOG.
