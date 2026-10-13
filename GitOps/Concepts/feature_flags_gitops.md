# Feature Flags в GitOps: разделение deploy и release

**Актуально для:** OpenFeature Operator v0.10.x / flagd v0.11.x / Argo CD v3.x / Flux v2.9.x / Kubernetes 1.28–1.32+ (on-premise / bare-metal)

GitOps отвечает на вопрос «какое состояние манифестов и контейнеров зафиксировано в кластере», но не на вопрос «какая часть исполняемого кода фактически активна для конкретных пользователей». Фиче-флаги (feature flags / feature toggles) разделяют эти два процесса: физическое развертывание новой версии артефакта (deploy) и активация бизнес-функциональности (release) становятся независимыми операциями — с раздельными коммитами, разной скоростью применения и изолированными уровнями риска.

## Предварительные требования

| Компонент | Минимальная версия / Требование | Назначение |
| :--- | :--- | :--- |
| Kubernetes | v1.28–v1.32+ (on-premise / bare-metal) | Кластерная инфраструктура для запуска рабочих нагрузок |
| GitOps-контроллер | Argo CD v3.x или Flux v2.9.x | Декларативная доставка манифестов и конфигураций флагов из Git |
| OpenFeature Operator | v0.10.x (CRD `core.openfeature.dev/v1beta1`) | Мутирующий вебхук для инъекции sidecar-демона flagd и управление CRD |
| flagd | v0.11.x | Локальный in-process/sidecar демон вычисления флагов (Unix philosophy) |
| OpenFeature SDK | SDK для языка сервиса (Go, Python, Java, Node.js) | Унифицированный API обращения к флагам с провайдером flagd |
| Self-hosted платформа | Flipt v1.40+ или Unleash v6.x (on-premise) | Опционально: централизованная платформа для динамических раскаток |
| Прогрессивная доставка | Argo Rollouts v1.7+ или Flagger v1.38+ | Опционально: управление канареечным трафиком между версиями подов |
| Утилиты диагностики | `kubectl`, `jq`, `curl`, `grpcurl` | Инспекция CRD, проверка probe и прямое тестирование gRPC/HTTP API |

## Определения

- **Deployment (развертывание)**: Процесс доставки собранного артефакта (бинарного файла, OCI-образа) в целевое окружение и запуск подов в кластере. В классическом GitOps автоматизируется оператором на основе коммита в Git.
- **Release (выпуск)**: Предоставление новой функциональности конечным пользователям или внешним системам. Без фиче-флагов релиз происходит автоматически в момент деплоя; с флагами релиз отложен и контролируется отдельно.
- **Feature Flag (feature toggle)**: Условная конструкция в кодовой базе, изменяющая поведение системы в рантайме на основе значения, вычисленного внешним или локальным движком правил, без перекомпиляции и перезапуска сервиса.
- **OpenFeature**: Открытый стандарт под эгидой CNCF, задающий вендоро-независимый API оценки флагов. Приложение взаимодействует с унифицированным интерфейсом SDK (`client.getBooleanValue("flag", false)`), не завися от конкретного бэкенда хранения правил.
- **flagd**: Легковесный open-source демон вычисления флагов от проекта OpenFeature. Читает конфигурацию правил (из файлов, ConfigMap, HTTP или gRPC), оценивает правила таргетинга (включая процентное распределение) локально в оперативной памяти и отдает результат приложению по протоколу gRPC или HTTP.
- **OpenFeature Operator (OFO)**: Kubernetes-оператор, управляющий жизненным циклом flagd. Автоматически внедряет sidecar-контейнеры flagd в поды приложений через mutating webhook и синхронизирует правила через CRD `FeatureFlag` и `FeatureFlagSource`.
- **Static Flags (статические флаги)**: Архитектурный подход, при котором правила и значения флагов хранятся непосредственно в Git (манифесты Kubernetes, ConfigMap или CRD). Изменение флага требует Git-коммита и PR. Обеспечивает строгий аудит и воспроизводимость, но скорость применения ограничена временем реконсиляции GitOps.
- **Dynamic Flags (динамические флаги)**: Подход, при котором значения флагов хранятся в выделенной платформе (self-hosted Flipt или Unleash) и изменяются через UI/API в реальном времени за секунды. Не требует Git-коммита, но выводит часть конфигурации из-под контроля GitOps, создавая риск дрейфа.
- **Kill Switch (аварийный выключатель)**: Долговременный операционный флаг, предназначенный для мгновенной деактивации ресурсоемкой или дефектной функциональности при аварии без отката релизов и перезапуска подов.
- **Feature Debt (технический долг флагов)**: Накопление устаревших ветвлений кода и неактуальных конфигураций флагов после завершения релиза, повышающее когнитивную сложность и комбинаторный взрыв в тестировании.

## Архитектура и базовые концепции

### Разделение Deploy и Release в GitOps

Классический цикл GitOps жестко связывает доставку кода с его активацией:

```text
[Коммит в Git] → [CI: сборка образа] → [GitOps: обновление тега] → [Argo CD Sync] → [Поды v2 запущены]
                                                                                        │
                                                     Без флагов: пользователи сразу видят код v2 (Deploy == Release)
                                                     С флагами: код v2 неактивен, флаг = false (Deploy != Release)
```

При отсутствии фиче-флагов обнаружение критического дефекта в новой функциональности требует отката:
1. Создание revert-коммита или исправление тега образа в Git.
2. Прохождение проверок CI.
3. Ожидание цикла синхронизации GitOps-контроллера (poll interval или webhook).
4. Запуск RollingUpdate / перезапуск подов (минуты или десятки минут).

С применением фиче-флагов новая версия развертывается в кластере с выключенным состоянием флага (`defaultVariant: "off"`). Активация выполняется отдельно. При возникновении сбоя срабатывает kill switch, переводящий логику на старый путь выполнения за миллисекунды.

### Топология вычислений: Local-First vs Centralized

Критическое требование SRE к фиче-флагам — отсутствие накладных расходов в hot-path приложения. Существуют две основные топологии развертывания движка правил в on-premise Kubernetes:

```text
1. Local-First Evaluation (Sidecar / In-Process):
┌──────────────────────── Pod ────────────────────────┐
│  ┌───────────────────────┐   gRPC (localhost:8013)  │
│  │ Контейнер приложения  │ ◄──────────────────────┐ │
│  │ (OpenFeature SDK)     │                        │ │
│  └───────────────────────┘                        │ │
│                                                   ▼ │
│                                 ┌──────────────────┐│
│  CRD FeatureFlag (k8s API) ───► │ flagd Sidecar    ││
│  (или локальный ConfigMap)      │ (O(1) in-memory) ││
│                                 └──────────────────┘│
└─────────────────────────────────────────────────────┘

2. Centralized Proxy (Кластерный сервис):
┌─────────────────────────┐               ┌─────────────────────────────────┐
│ App Pod 1               │  gRPC / HTTP  │ Service: flagd-proxy            │
├─────────────────────────┤ ────────────► │ ┌─────────────────────────────┐ │
│ App Pod 2               │               │ │ flagd Deployment (Replicas) │ │
└─────────────────────────┘               │ └─────────────────────────────┘ │
                                          └─────────────────────────────────┘
```

| Параметр | Local-First (Sidecar flagd) | Centralized Proxy (Service) | Прямой вызов платформы (Антипаттерн) |
| :--- | :--- | :--- | :--- |
| Latency вычисления | **< 0.5 мс** (локальный IPC/loopback) | 1–3 мс (внутрикластерная сеть) | 10–50+ мс (внешний HTTP-запрос) |
| Точка отказа | Изолирована в рамках пода | Сбой Service ломает группу подов | Падение платформы парализует все сервисы |
| Расход памяти | ~15–30 МБ RAM на каждый Pod | Фиксированный пул (2–4 пода по 50 МБ) | Отсутствует на стороне пода |
| Рекомендация для SRE | **Основной стандарт** для высоконагруженных сервисов | Экономия ресурсов в dev/staging или при 1000+ микросервисах | Недопустимо в hot-path продакшена |

### Модели управления: Static, Dynamic и Hybrid

| Критерий | Static (флаги в Git) | Dynamic (self-hosted платформа) | Hybrid (промышленный стандарт) |
| :--- | :--- | :--- | :--- |
| Хранение состояния | Git (ConfigMap / `FeatureFlag` CRD) | БД платформы (Flipt / Unleash) | Git (дефолты/CRD) + Платформа (раскатка) |
| Скорость изменения | 1–3 минуты (PR merge + sync) | < 1 секунды (API / UI) | Мгновенно через API с авто-синхронизацией |
| Аудит изменений | Неизменяемая история коммитов Git | Журналы БД платформы | Git-история + стриминг событий аудита |
| Риск GitOps Drift | **Исключен** (Git — единственный источник) | **Высокий** (состояние живет вне Git) | Контролируется через `ignoreDifferences` |
| Автономность при изоляции сети | **Полная** (работает автономно в кластере) | Требует доступности локальной БД | Полная (локальный кэш flagd) |

**Рекомендованный гибридный подход:**
1. Все базовые объявления флагов, безопасные значения по умолчанию (`defaultVariant: "off"`) и критические kill-switch'и описываются декларативно в Git и доставляются через Argo CD / Flux.
2. Оперативные проценты раскатки (fractional targeting) и сегменты тестирования управляются через локально развернутую self-hosted платформу флагов.
3. Платформа экспортирует все события аудита через webhook в централизованный стек логирования ([журналы аудита](./audit_logs.md)).

### Ортогональность канареечной доставки и фиче-флагов

Канареечные релизы (Canary via Argo Rollouts / Flagger) и фиче-флаги закрывают принципиально разные риски и дополняют друг друга в едином пайплайне:

```text
[Инфраструктурный уровень]  Canary Deployment (Argo Rollouts)
                             Управляет трафиком между ВЕРСИЯМИ ПОДОВ (v1 vs v2).
                             Контроль технических метрик: ошибки сети, 5xx, CPU, p99 latency.
                                      │
                                      ▼ (После переключения 100% трафика на v2)
[Прикладной уровень]        Feature Flag Rollout (flagd / OpenFeature)
                             Управляет видимостью ФУНКЦИИ ВНУТРИ ВЕРСИИ v2.
                             Контроль бизнес-метрик: конверсия, ошибки валидации форм, нагрузка на БД.
```

Такое разделение предотвращает смешивание сигналов: если при канарейке на 10% трафика вырастет время ответа, инженер SRE точно знает, что проблема в коде новой версии контейнера, а не в бизнес-логике новой скрытой фичи, так как фича в этот момент отключена флагом.

### Жизненный цикл и классификация флагов

Для предотвращения деградации кодовой базы флаги классифицируются по типам и времени жизни (TTL):

```text
           ┌─────────────────────────────────────────────────────────┐
           │                   Классификация флагов                   │
           └────────────────────────────┬────────────────────────────┘
                                        │
             ┌──────────────────────────┴──────────────────────────┐
             ▼                                                     ▼
┌─────────────────────────┐                             ┌─────────────────────────┐
│     Краткосрочные       │                             │      Долговременные     │
├─────────────────────────┤                             ├─────────────────────────┤
│ Release Toggles         │                             │ Ops Toggles             │
│ (TTL: 1–4 недели)       │                             │ (Kill Switch, Circuit   │
│ Цель: безопасный релиз  │                             │  Breakers, аварийные)   │
├─────────────────────────┤                             ├─────────────────────────┤
│ Experiment Toggles      │                             │ Permission Toggles      │
│ (TTL: 2–8 недель)       │                             │ (Тарифы, права доступа, │
│ Цель: A/B тестирование  │                             │  внутренние модули)     │
└─────────────────────────┘                             └─────────────────────────┘
```

Правила гигиены технического долга:
1. **Именование**: Префикс по типу и подсистеме: `rel-<service>-<feature>` для релизных, `ops-<service>-<killswitch>` для аварийных.
2. **Метка устаревания (Expiration)**: В манифесте флага указывается дата планируемого вывода из эксплуатации.
3. **Ограничение количества**: Не более 3–5 активных release-флагов на один микросервис одновременно.
4. **Обязательный Cleanup PR**: Создание задачи на удаление флага из кода и манифестов сразу при создании флага (Definition of Done для релиза).

## Практические сценарии и конфигурация

### Сценарий 1: Декларативное управление флагами через OpenFeature Operator v1beta1

Декларативное описание флагов в виде CRD `FeatureFlag` и источника `FeatureFlagSource` (`core.openfeature.dev/v1beta1`), доставляемых Argo CD или Flux:

```yaml
# 1. Описание правил флагов в пространстве имен приложения
apiVersion: core.openfeature.dev/v1beta1
kind: FeatureFlag
metadata:
  name: checkout-feature-flags
  namespace: billing
spec:
  flagSpec:
    flags:
      new-payment-engine:
        state: ENABLED
        variants:
          "on": true
          "off": false
        defaultVariant: "off"
      express-checkout-flow:
        state: ENABLED
        variants:
          "on": true
          "off": false
        defaultVariant: "off"
        targeting:
          fractional:
            - ["on", 25]
            - ["off", 75]
---
# 2. Описание источника флагов для sidecar flagd
apiVersion: core.openfeature.dev/v1beta1
kind: FeatureFlagSource
metadata:
  name: checkout-flag-source
  namespace: billing
spec:
  sources:
    - source: billing/checkout-feature-flags
      provider: kubernetes
  port: 8013
```

Подключение автоматической инъекции flagd sidecar в Deployment приложения:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout-service
  namespace: billing
spec:
  replicas: 3
  selector:
    matchLabels:
      app: checkout-service
  template:
    metadata:
      labels:
        app: checkout-service
      annotations:
        # Активация инъекции sidecar через OpenFeature Operator
        openfeature.dev/enabled: "true"
        # Привязка к созданному FeatureFlagSource
        openfeature.dev/featureflagsource: "checkout-flag-source"
    spec:
      containers:
        - name: application
          image: registry.internal/billing/checkout:v2.4.0
          ports:
            - containerPort: 8080
          env:
            - name: FLAGD_HOST
              value: "localhost"
            - name: FLAGD_PORT
              value: "8013"
```

Пример использования в Go с безопасным отказоустойчивым дефолтом (Local Fallback):

```go
package main

import (
	"context"
	"log"

	"github.com/open-feature/go-sdk/openfeature"
	flagd "github.com/open-feature/go-sdk-contrib/providers/flagd/pkg"
)

func initFeatureClient() openfeature.IClient {
	// Подключение к локальному sidecar flagd через gRPC (zero network hops)
	provider := flagd.NewProvider(flagd.WithHost("localhost"), flagd.WithPort(8013))
	if err := openfeature.SetProviderAndWait(provider); err != nil {
		log.Printf("Внимание: flagd недоступен, SDK использует fallback: %v", err)
	}
	return openfeature.NewClient("checkout-service")
}

func handleCheckout(ctx context.Context, client openfeature.IClient, userID string) {
	evalCtx := openfeature.NewTargetingContext(userID, map[string]interface{}{
		"targetingKey": userID,
	})

	// При сбое связи с flagd вернется безопасный дефолт (false)
	enabled, err := client.BooleanValue(ctx, "new-payment-engine", false, evalCtx)
	if err != nil {
		log.Printf("Ошибка вычисления флага, применен fallback: %v", err)
	}

	if enabled {
		executeModernPaymentPipeline()
	} else {
		executeLegacyPaymentPipeline()
	}
}
```

Проверка применения и статуса в кластере:

```bash
# Проверка готовности CRD флагов
kubectl get featureflag,featureflagsource -n billing
# → NAME                                                  AGE
# → featureflag.core.openfeature.dev/checkout-feature-flags   45s
# → featureflagsource.core.openfeature.dev/checkout-flag-source 45s

# Проверка наличия внедренного sidecar-контейнера flagd
kubectl get pods -n billing -l app=checkout-service -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.containers[*].name}{"\n"}{end}'
# → checkout-service-789bfb846-abc12: application flagd
# → checkout-service-789bfb846-def34: application flagd
# → checkout-service-789bfb846-ghi56: application flagd
```

### Сценарий 2: Поэтапное включение функции поверх канареечного деплоя

Сквозной регламент вывода функциональности на прод:

1. **Этап 1: Канареечный деплой контейнеров (Argo Rollouts)**
   - Выкатывается новая версия `v2.4.0`.
   - Флаг `express-checkout-flow` в Git зафиксирован в `defaultVariant: "off"`.
   - Контроллер канарейки раскатывает трафик: 10% → 50% → 100%.
   - Анализируются технические метрики пода: Prometheus HTTP latency p99 < 80ms, 5xx error rate < 0.05%.
2. **Этап 2: Процентная раскатка бизнес-функциональности (Feature Flag PR #1)**
   - Создается Git PR, изменяющий таргетинг флага на 10%:
     ```json
     "fractional": [["on", 10], ["off", 90]]
     ```
   - Argo CD синхронизирует `FeatureFlag` CRD. Sidecar flagd моментально перечитывает правила без перезапуска подов приложения.
   - SRE и аналитики мониторят бизнес-метрики: количество успешно завершенных платежей, отсутствие бизнес-ошибок в логах.
3. **Этап 3: Полный релиз и стабилизация (Feature Flag PR #2)**
   - Перевод флага на 100%:
     ```yaml
     defaultVariant: "on"
     ```
   - Таргетинг удаляется, функционал доступен всем.

### Сценарий 3: Аварийный Kill Switch при инциденте

Два режима локализации аварии:

**Вариант А: Статический откат через Git (плановый)**:

```bash
# 1. Revert коммита включения флага
git revert <COMMIT_HASH> -m 1
git push origin main
# → Argo CD синхронизирует CRD (~1–2 мин в зависимости от sync-политики)
```

**Вариант Б: Экстренный аварийный патч напрямую в кластере (SRE Hot-Fix)**:
Когда 2 минуты на прохождение Git-пайплайна недопустимы при падении прода:

```bash
# 1. Мгновенный патч defaultVariant в положение "off" напрямую в CRD
kubectl patch featureflag checkout-feature-flags -n billing --type=merge -p \
  '{"spec":{"flagSpec":{"flags":{"new-payment-engine":{"defaultVariant":"off"}}}}}'
# → featureflag.core.openfeature.dev/checkout-feature-flags patched

# 2. Проверка немедленного переключения в логах flagd
kubectl logs -l app=checkout-service -c flagd -n billing --tail=5 | grep -E "(sync|eval)"
# → event=configuration_change source=billing/checkout-feature-flags defaultVariant=off
```

> [!WARNING]
> Любой аварийный `kubectl patch` должен сопровождаться немедленным созданием follow-up коммита в Git. В противном случае следующая автоматическая синхронизация Argo CD вернет значение из Git и снова включит упавшую функцию (GitOps Drift).

### Сценарий 4: Устранение GitOps Drift для CRD флагов в Argo CD и Flux

Если контроллер OpenFeature Operator обновляет статусные поля или служебные метаданные ресурсов, Argo CD видит постоянный дрейф (`OutOfSync`).

Настройка исключения статусных полей в Argo CD `Application`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-flags
  namespace: argocd
spec:
  ignoreDifferences:
    # Игнорирование служебных полей статуса OpenFeature CRD
    - group: core.openfeature.dev
      kind: FeatureFlag
      jsonPointers:
        - /status
    - group: core.openfeature.dev
      kind: FeatureFlagSource
      jsonPointers:
        - /status
```

Эквивалент для Flux в ресурсе `Kustomization`:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: billing-flags
  namespace: flux-system
spec:
  patches:
    - patch: |
        $patch: delete
        apiVersion: core.openfeature.dev/v1beta1
        kind: FeatureFlag
        metadata:
          name: not-used
        status: {}
      target:
        group: core.openfeature.dev
        kind: FeatureFlag
```

### Сценарий 5: Безопасные миграции баз данных под флагами (Expand-Contract)

Использование фиче-флагов без поддержки совместимости схем БД — частая причина сбоев. Для обеспечения нулевого простоя и возможности мгновенного отката флагом применяется паттерн Expand-Contract:

```text
Фаза 1 (Expand - БД):     Добавление новой колонки `new_data` (NULLable), старая `old_data` остается.
Фаза 2 (Деплой кода):     Развертывание сервиса с флагом `use-new-schema: off`.
Фаза 3 (Двойная запись):  Флаг включает параллельную запись в обе колонки, чтение из `old_data`.
Фаза 4 (Переключение):    Флаг переключает чтение на `new_data`. При сбое — мгновенный откат флага!
Фаза 5 (Contract - БД):   Удаление старой колонки `old_data` и удаление флага из кода через 2 спринта.
```

## Операции и команды

Сводка команд администрирования и диагностики инфраструктуры фиче-флагов:

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| Список CRD флагов | `kubectl get featureflag,featureflagsource -A` | Обзор всех зарегистрированных флагов и источников в кластере |
| Просмотр конфигурации | `kubectl get featureflag <NAME> -n <NS> -o jsonpath='{.spec.flagSpec}' \| jq .` | Чтение активных правил таргетинга из манифеста |
| Логи демона flagd | `kubectl logs deploy/<APP> -c flagd -n <NS> --tail=50 -f` | Трассировка событий синхронизации правил и вычислений |
| Проверка healthcheck | `kubectl exec deploy/<APP> -c flagd -n <NS> -- curl -s http://localhost:8014/healthz` | Проверка liveness probe демона (порт 8014) |
| Проверка готовности | `kubectl exec deploy/<APP> -c flagd -n <NS> -- curl -s http://localhost:8014/readyz` | Проверка готовности провайдеров синхронизации правил |
| Тест вычисления (HTTP) | `kubectl exec deploy/<APP> -c flagd -n <NS> -- curl -s -X POST http://localhost:8013/flagd.evaluation.v1.Service/ResolveBoolean -H "Content-Type: application/json" -d '{"flagKey":"<FLAG>"}'` | Ручное тестирование резолвинга флага через локальный API |
| Сбор метрик flagd | `kubectl exec deploy/<APP> -c flagd -n <NS> -- curl -s http://localhost:8014/metrics \| grep feature_flag` | Инспекция счетчиков Prometheus (`feature_flag_flagd_impression_total`) |
| Аварийный Kill Switch | `kubectl patch featureflag <NAME> -n <NS> --type=merge -p '{"spec":{"flagSpec":{"flags":{"<FLAG>":{"defaultVariant":"off"}}}}}'` | Экстренное отключение функции в обход Git с последующим PR |

### Примеры диагностических запросов

1. Проверка состояния синхронизации в логах flagd:
```bash
kubectl logs deploy/checkout-service -c flagd -n billing --tail=20 | grep -E "(sync|provider|ready)"
# → {"level":"info","time":"2026-10-12T21:00:00Z","message":"provider sync completed: billing/checkout-feature-flags"}
# → {"level":"info","time":"2026-10-12T21:00:00Z","message":"flagd readiness probe status: 200 OK"}
```

2. Сбор статистики вычисления флагов для Prometheus:
```bash
kubectl exec deploy/checkout-service -c flagd -n billing -- curl -s http://localhost:8014/metrics | grep -E "feature_flag.*impression"
# → feature_flag_flagd_impression_total{feature_flag_key="new-payment-engine",feature_flag_provider_name="flagd",feature_flag_reason="STATIC",feature_flag_result_variant="off"} 18452
```

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Рост latency приложения при каждом запросе флага | Сетевой оверхед: SDK настроен на прямой HTTP-запрос к внешней платформе вместо локального sidecar flagd | `kubectl logs deploy/<APP> -n <NS>` (замеры времени вызова SDK); `netstat -an \| grep <PORT>` | Перевести SDK на `localhost:8013` (local-first evaluation через sidecar или IPC); исключить сетевые вызовы в hot-path |
| Статус OutOfSync в Argo CD / Flux для `FeatureFlag` | Оператор обновляет `.status` или аннотации ресурса, которые GitOps считает дрейфом | `argocd app diff <APP_NAME>` или `kubectl get featureflag <NAME> -o yaml` | Добавить игнорирование `.status` в `ignoreDifferences` (Argo CD) или `.spec.ignore` (Flux) |
| Sidecar flagd не внедряется в поды | Отсутствуют аннотации на шаблоне пода, либо muting webhook оператора заблокирован политиками | `kubectl get pod <NAME> -o jsonpath='{.metadata.annotations}'`; `kubectl get events -n <NS>` | Проверить аннотации `openfeature.dev/enabled: "true"` именно в `spec.template.metadata.annotations`; проверить права RBAC и доступность webhook OFO |
| flagd отдает HTTP 412 на `/readyz` | Ошибка провайдера синхронизации: не найден ConfigMap/CRD или синтаксическая ошибка JSON/YAML | `kubectl logs deploy/<APP> -c flagd -n <NS>` | Проверить имя и пространство имен в `FeatureFlagSource`; исправить валидность JSON/YAML в спецификации флагов |
| Рассинхрон значений флага между подами | Кэширование значения внутри приложения без подписки на стрим событий обновления | Проверить реализацию SDK в коде сервиса; сравнить отдачу разных подов через `/metrics` | Использовать dynamic event listener в SDK или проверять флаг при каждом обращении (flagd локален и оптимизирован для O(1) in-memory) |
| Ошибки 500 / сбои в БД после включения флага | Функционал требует изменений схемы БД, которые не поддерживают старый путь выполнения | `kubectl logs deploy/<APP> -n <NS> \| grep -E "(SQL\|DB\|QueryException)"` | Применить аварийный kill switch; переработать миграцию по шаблону Expand-Contract |
| Накопление зомби-флагов в коде и Git | Отсутствует регламент вывода флагов из эксплуатации | Поиск флагов старше 30 дней: `grep -r "feature_flags" manifests/` | Ввести обязательный срок жизни (TTL), настроить CI-линтер устаревших флагов и cleanup PR |

## Лучшие практики

1. **Local-First Evaluation**: Всегда отдавать предпочтение локальному sidecar flagd. Приложение обращается к демону по адресу `127.0.0.1:8013` (gRPC или Unix Domain Socket). Оценка правил происходит локально в оперативной памяти без сетевых задержек.
2. **Разделение политик отказа (Fail-Closed vs Fail-Open)**:
   - Для критических бизнес-процессов (платежи, безопасность, валидация прав) дефолтное значение должно быть строго **Fail-Closed** (`false` / отключено).
   - Для второстепенных элементов (рекомендательные блоки, вспомогательный UI) допускается **Fail-Open** / **Fail-Safe** с отдачей базового контента.
3. **Строгая изоляция секретов**: Конфигурация флагов предназначена исключительно для маршрутизации логики. Запрещено передавать в `variants` или контексте таргетинга секретные ключи, пароли или токены. Управление секретами должно выполняться строго через специализированные операторы ([ESO/SOPS](../secrets_encryption.md)).
4. **Аудит и воспроизводимость**:
   - При статическом управлении каждый шаг раскатки фиксируется в Git через отдельный PR со ссылкой на дашборд мониторинга.
   - При использовании dynamic/hybrid платформы включить обязательный экспорт логов аудита через webhook в кластерный сборщик логов (Vector/Fluentbit/Loki).
5. **Ограничение срока жизни (TTL) и гигиена**:
   - Release-флаг должен жить в кодовой базе не более 1–2 релизных циклов (максимум 30 дней).
   - Задача на удаление флага из кодовой базы и манифестов GitOps создается одновременно с задачей на его внедрение.

## Дополнительная информация

- **Связь с DORA-метриками**: Практика использования фиче-флагов радикально снижает метрику **FDRT / MTTR** (время восстановления после сбоя) с десятков минут (цикл отката в GitOps) до миллисекунд (срабатывание kill switch). Кроме того, процентная раскатка флагов минимизирует **Change Failure Rate (CFR)**, изолируя потенциальный сбой рамками малой группы пользователей ([DORA-метрики в GitOps](./dora_metrics_gitops.md)).
- **Трассируемость и аудит**: Регламенты фиксации изменений рантайм-платформ и аудита действий операторов подробно описаны в руководстве [Журналы аудита и трассируемость](./audit_logs.md).

### См. также

- [Прогрессивная доставка в GitOps](./progressive_delivery_gitops.md) — канареечные и blue-green релизы в связке с фиче-флагами.
- [DORA-метрики в GitOps](./dora_metrics_gitops.md) — измерение влияния отделения deploy от release на метрики команды.
- [Игнорирование различий в Argo CD](../ArgoCD/synchronization/ignore_differences.md) — решение проблемы бесконечной реконсиляции статусов CRD.
- [GitOps: Управление секретами и шифрование](../secrets_encryption.md) — безопасное хранение чувствительных данных.
- [Архитектура фиче-тогглов](../../CI-CD/Testing/feature_toggles/architecture.md) — общие шаблоны проектирования систем флагов в приложениях.
- [Антипаттерны фиче-тогглов](../../CI-CD/Testing/feature_toggles/antipatterns.md) — типичные ошибки проектирования и эксплуатации флагов.
- [Рабочие процессы в Git](../../Git/git_workflows.md) — методология Trunk-Based Development с использованием Feature Flags.

---

## Вопросы для собеседования

### 1. В чем заключается фундаментальная разница между понятиями Deploy и Release в современном DevOps/SRE?
**Ответ:** 
- **Deploy (Развертывание):** Чисто технический процесс доставки бинарного артефакта в целевой кластер Kubernetes (создание подов, монтирование томов, прохождение readiness probes). В этот момент код уже работает в кластере, но конечные пользователи его не видят.
- **Release (Релиз):** Бизнес-событие предоставления функционала пользователям. С использованием Feature Flags (фича-тогглов) релиз полностью отвязывается от деплоя: код выкатывается в прод за несколько дней до релиза в выключенном состоянии, а затем активируется мгновенным переключением флага без создания коммитов деплоя и рестартов подов.

### 2. Почему при возникновении P1-инцидента (аварии в проде) изменение значения фича-флага через коммит в GitOps может оказаться неприемлемым для SRE?
**Ответ:** Стандартный цикл GitOps занимает от 1 до 5 минут (создание коммита $\to$ прохождение CI линтеров $\to$ опрос Git контроллером или доставка webhook $\to$ реконсиляция ConfigMap $\to$ перечитка конфига подом). В критической ситуации (например, утечка данных или перегрузка БД) потеря 3–5 минут недопустима. Поэтому для аварийных выключателей (**Emergency Kill Switch**) применяют гибридный подход: флаг управляется через локальный in-memory брокер (Redis / On-Premise Unleash API), позволяющий дежурному SRE выключить функционал за доли секунды, а коммит в Git оформляется постфактум для синхронизации SSoT.

### 3. Почему в On-Premise микросервисах архитектура вызова флагов через sidecar (flagd / Local-First evaluation) предпочтительнее централизованного REST API сервера флагов?
**Ответ:** Если микросервис выполняет синхронный HTTP/gRPC запрос во внешний сервер флагов при каждом входящем пользовательском запросе (на hot-path), это создает критические проблемы:
1. Катастрофический рост latency (каждый сетевой вызов добавляет 2–10 мс).
2. Единая точка отказа (Single Point of Failure): при падении сервера флагов встает весь кластер.
**Local-First через sidecar (flagd):** правила флагов хранятся локально в оперативной памяти пода (внедряются через ConfigMap или стримятся по UDS/gRPC). Вычисление значения флага происходит локально за микросекунды ($O(1)$ in-memory), полностью изолируя рантайм от сетевых проблем.

### 4. Что такое «зомби-флаги» (Zombie Flags / Flag Debt) и как этот технический долг контролируется в продакшене?
**Ответ:** Зомби-флаги — это устаревшие ветвления в кодовой базе, оставшиеся после того, как фича была на 100% раскатана и признана стабильной. Они усложняют чтение кода, увеличивают комбинаторную сложность тестирования (проверка взаимного влияния десятков флагов) и создают риски случайного включения старого дефектного кода.
**Методы борьбы:**
- Назначение TTL на каждый флаг (максимум 14–30 дней).
- Линтеры в CI: статический анализ кода, фейлящий сборку, если флаг существует дольше установленного дедлайна.
- Принцип парных задач: задача на удаление флага (`cleanup task`) заводится в бэклог одновременно с задачей на его создание.

### 5. Как правильно синхронизировать работу фича-флагов с миграциями базы данных (паттерн Expand-Contract)?
**Ответ:** Переключение флага мгновенно, но структура базы данных инерционна. Применяется паттерн параллельного изменения (Expand-Contract):
1. **Фаза Expand (Расширение):** в базу добавляются новые колонки/таблицы с поддержкой обратной совместимости (nullable-поля, триггеры дублирования данных). В прод деплоится код с выключенным флагом.
2. **Фаза Rollout (Переключение):** фича-флаг включается на 10% $\to$ 100%. Сервис начинает писать и читать из новой схемы данных.
3. **Фаза Contract (Сжатие):** после полной стабилизации и успешной работы функционала флаг удаляется из кода, а отдельной финальной миграцией удаляются старые неиспользуемые колонки в БД. Это гарантирует, что мгновенное выключение флага (rollback) не разрушит согласованность данных.


