# Инструменты Chaos Engineering

## Определения

**Инструменты Chaos Engineering** — это специализированное программное обеспечение, предназначенное для автоматизации, контроля и безопасного проведения экспериментов по внесению сбоев (fault injection).

Современный инструментарий классифицируется по уровню воздействия (инфраструктура, сеть, приложение) и обеспечивает полный жизненный цикл эксперимента:
*   **Steady State Definition:** Интеграция с мониторингом для фиксации «нормы».
*   **Fault Injection:** Механизмы внесения возмущений (удаление ресурсов, ограничение пропускной способности, инъекция кода).
*   **Stop-switch (Прерыватель):** Автоматическая остановка эксперимента при обнаружении критической деградации бизнес-метрик.
*   **Blast Radius Control:** Механизмы изоляции влияния эксперимента на конкретную группу пользователей или сегмент сети.

## Основные концепции

### Классификация по области применения

#### 1. Kubernetes-native инструменты
Ориентированы на работу с объектами K8s (Pods, Nodes, NetworkPolicies) через Custom Resource Definitions (CRD).

*   **Chaos Mesh:**
    *   **Особенности:** Глубокая интеграция с ядром через BPF. Поддерживает сбои на уровнях: Pod, Network, File System, Kernel (инъекция ошибок в системные вызовы) и Time (смещение системного времени).
    *   **Применение:** Когда требуется максимальная детализация сбоев в K8s.
*   **LitmusChaos:**
    *   **Особенности:** Использует декларативный подход и **ChaosHub** (каталог готовых сценариев). Версия 3.x поддерживает мультикластерность и сложные цепочки проверок (Probes).
    *   **Применение:** Построение Enterprise-платформ хаос-инженерии.
*   **Kube-monkey:**
    *   **Особенности:** Реализация паттерна Chaos Monkey для K8s. Удаляет поды на основе аннотаций в Deployment. Работает в рабочее время, когда инженеры на месте.
    *   **Применение:** Простейшая проверка «выживаемости» сервисов при потере подов.

#### 2. Платформы универсального назначения
Поддерживают Bare-metal, виртуальные машины и проприетарные инфраструктурные решения.

*   **Gremlin:**
    *   **Особенности:** Коммерческая платформа ("Resilience Management"). Фокусируется на безопасности и простоте. Функция "Detected Dependencies" автоматически визуализирует риски каскадных сбоев.
*   **Steadybit:**
    *   **Особенности:** Визуальный конструктор экспериментов. Фокус на "Resilience as Code" и автоматическом обнаружении всей топологии системы.
*   **Chaosblade:**
    *   **Особенности:** Инструмент от Alibaba. Мощный CLI и агенты для инъекции сбоев на уровне рантайма (Java, Go, C++), например, выброс исключений в конкретных методах кода.

#### 3. Специализированные и локальные инструменты
*   **Pumba:** Хаос-тестирование специально для Docker-контейнеров (сеть, пауза, удаление).
*   **Toxiproxy:** TCP-прокси для имитации сетевых аномалий в CI/CD и локальной разработке.
*   **PowerfulSeal:** Инструмент для автономного «уничтожения» ресурсов в K8s и виртуальных/физических инфраструктурах.

### Архитектура pipeline хаос-эксперимента

Качественный инструмент Chaos Engineering управляет pipeline из пяти этапов:

```
1. Target Selection (Выбор цели)
   └── Label Selectors / IP / Hostname
   └── Blast Radius filter (только 1–5% ресурсов)

2. Fault Injection (Внесение сбоя)
   └── Network: delay, loss, partition (tc, iptables)
   └── Compute: CPU hog, memory hog, IO stress
   └── Application: exception injection, latency injection
   └── Infrastructure: pod kill, node drain, disk fill

3. Monitoring & Probes (Наблюдение)
   └── HTTP/GRPC probes (Litmus, Chaos Mesh)
   └── Prometheus metrics pull
   └── Business metrics validation

4. Stop Condition (Условие остановки)
   └── Time-based: TOTAL_CHAOS_DURATION истек
   └── Metric-based: error_rate > SLO
   └── Probe-based: health check вернул 500

5. Cleanup & Analysis (Очистка и анализ)
   └── Автоматическое удаление CRD/политик
   └── Генерация отчета: steady state upheld?
```

**Ключевые компоненты:**
*   **Chaos Controller / Daemon:** Основной процесс, который принимает CRD/политики и управляет инъекцией. В Chaos Mesh — `chaos-controller-manager` и `chaos-daemon`. В LitmusChaos — `chaos-operator`.
*   **Sidecar / Agent:** Дополнительный контейнер или демон, который работает на целевом узле и выполняет фактическую инъекцию сбоя (например, `chaos-daemon` использует `tc` для сетевых задержек).
*   **Exporter:** Сбор метрик об эксперименте (статус, длительность,blast radius). В Chaos Mesh — `chaos-mesh-exporter`.

## Практические сценарии

### Пример 1: Инъекция сетевых задержек (Chaos Mesh)

Сценарий: Проверка работы Circuit Breaker при задержках 200мс в сервисе `catalog`.

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: network-delay-catalog
spec:
  action: delay
  mode: one # Выбрать один случайный под
  selector:
    namespaces:
      - production
    labelSelectors:
      app: catalog
  delay:
    latency: "200ms"
    correlation: "25" # Степень корреляции с предыдущими пакетами
    jitter: "50ms"    # Разброс задержки
  duration: "10m"     # Длительность атаки
```

### Пример 2: Проверка Steady State через HTTP-пробы (LitmusChaos)

Гарантируем, что фронтенд отдает 200 OK в течение всего процесса удаления подов бэкенда.

```yaml
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: engine-payment-check
spec:
  experiments:
    - name: pod-delete
      spec:
        probe:
          - name: "check-frontend-availability"
            type: "httpProbe"
            httpProbe/inputs:
              url: "http://frontend.prod.svc.cluster.local/health"
              method: "GET"
              expectedResponseCode: "200"
            mode: "Continuous" # Проверять непрерывно
            runProperties:
              probeTimeout: 1000
              interval: 2
```

### Пример 3: Инъекция исключения на уровне Java (Chaosblade)

Выброс исключения `CustomException` при вызове метода `getUserInfo` в приложении.

```bash
# Инъекция исключения в Java-приложение по PID
blade create docker jvm throwCustomException \
  --exception java.lang.Exception \
  --classname com.example.service.UserService \
  --methodname getUserInfo \
  --container-id <CONTAINER_ID>
```

### Пример 4: Инъекция задержки на уровне системных вызовов (Chaos Mesh)

Сценарий: Проверка устойчивости базы данных при задержке дисковых операций (IO latency).

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: IOChaos
metadata:
  name: io-latency-postgres
spec:
  action: delay
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: postgres
  delay: "100ms"
  volumePath: /var/lib/postgresql/data
  duration: "5m"
```

## Операции и команды

### Chaos Mesh

| Операция | Команда / Манифест |
|:---|:---|
| **Установка (Helm)** | `helm install chaos-mesh chaos-mesh/chaos-mesh --namespace chaos-mesh --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/containerd/containerd.sock --version 2.6.0` |
| **Проверка CRDs** | `kubectl get crd | grep chaos-mesh` |
| **Запуск эксперимента** | `kubectl apply -f network-delay.yaml` |
| **Статус эксперимента** | `kubectl describe NetworkChaos network-delay-catalog -n chaos-mesh` |
| **Принудительная остановка** | `kubectl delete -f network-delay.yaml` |
| **Просмотр логов** | `kubectl logs -n chaos-mesh -l app.kubernetes.io/name=chaos-mesh --controller` |

### LitmusChaos

| Операция | Команда / Манифест |
|:---|:---|
| **Установка (Helm)** | `helm install litmus litmuschaos/litmus --namespace litmus --set portalServer.enabled=true` |
| **Проверка CRDs** | `kubectl get crd | grep litmus` |
| **Запуск эксперимента** | `kubectl apply -f chaosengine-pod-delete.yaml` |
| **Статус эксперимента** | `kubectl get chaosengine -n litmus` |
| **Остановка** | `kubectl delete chaosengine <name> -n litmus` |
| **Workflow** | `kubectl apply -f game-day-workflow.yaml` |

### Pumba (Docker)

| Операция | Команда |
|:---|:---|
| **Пауза контейнера** | `pumba pause --duration 30s <container_id>` |
| **Удаление контейнера** | `pumba kill --signal SIGKILL <container_id>` |
| **Сетевая задержка** | `pumba netem --duration 60s --delay 500ms <container_id>` |
| **Потеря пакетов** | `pumba netem --duration 60s --loss 10% <container_id>` |
| **Просмотр списка** | `pumba ls` |

### Toxiproxy

| Операция | Команда |
|:---|:---|
| **Создание прокси** | `curl -X POST http://localhost:8474/proxies -d '{"name":"app","listen":"0.0.0.0:8080","upstream":"app:8080","enabled":true}'` |
| **Добавление задержки** | `curl -X POST http://localhost:8474/proxies/app/toxics -d '{"name":"latency","type":"latency","attributes":{"latency":5000}}'` |
| **Потеря пакетов** | `curl -X POST http://localhost:8474/proxies/app/toxics -d '{"name":"loss","type":"loss","attributes":{"percentage":10}}'` |
| **Удаление toxic** | `curl -X DELETE http://localhost:8474/proxies/app/toxics/latency` |
| **Список прокси** | `curl http://localhost:8474/proxies` |

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Chaos Mesh CRD не установлены** | Неполная установка | `kubectl apply -f https://chaos-mesh.org/manifests/chaos-mesh.yaml` |
| **LitmusChaos не находит поды** | Неверный namespace или label | Проверьте `appns` и `applabel` в ChaosEngine |
| **Probe не работает** | NetworkPolicy блокирует | Добавьте исключение для Litmus/Chaos Mesh в NetworkPolicy |
| **Эксперимент не останавливается** | Истёк `TOTAL_CHAOS_DURATION` | Проверьте логи ChaosDaemon / chaos-operator |
| **Нет алертов после fault injection** | Alertmanager не настроен | Проверьте интеграцию Ruler → Alertmanager |
| **Game Day прерывается** | Emergency stop сработал | Это корректное поведение — проверьте стабильность системы |
| **Сетевая задержка не применяется** | BPF/tc недоступен | Убедитесь, что `chaos-daemon` имеет права CAP_SYS_ADMIN |
| **Sidecar не инжектируется** | Istio/Ambient conflict | Проверьте, что namespace не аннотирован для sidecar injection |

Подробные диагностические сценарии и разборы с логами — в разделе [Chaos Engineering — практическое руководство](chaos_engineering_practical.md#устранение-неполадок).

## Лучшие практики

### Безопасность и Blast Radius

1.  **Всегда начинайте с staging** — первое применение инструмента обязательно в тестовой среде.
2.  **Ограничивайте Blast Radius** — начинайте с 1% трафика или одного пода. Никогда не применяйте к `mode: all` в production без проверки.
3.  **Имейте emergency stop** — автоматическое прерывание при критических метриках. Один человек должен иметь физический доступ к кнопке «остановить всё».
4.  **Уведомляйте команду** — все должны знать о запланированном эксперименте. Используйте общий чат и статус-страницу.
5.  **Не проводите эксперименты** во время критических периодов (релизы, праздники, маркетинговые акции).

### Архитектура экспериментов

6.  **Начинайте с простых экспериментов** — Pod Delete, CPU Hog. Переходите к сложным сетевым сбоям после отработки базовых.
7.  **Всегда используйте probes** — проверяйте steady state во время эксперимента. Без probes эксперимент — не научный метод, а «угадайка».
8.  **Документируйте эксперименты** — создавайте runbook для каждого сценария: цель, гипотеза, blast radius, критерии успеха, критерии остановки.
9.  **Автоматизируйте** — интегрируйте chaos testing в CI-CD pipeline. Каждый Pull Request должен проходить минимальный хаос-тест в Staging.
10. **Ведите metrics** — отслеживайте detection time, response time, MTTR. Без цифр нельзя доказать улучшение надежности.

### Организация процессов

11. **Проводите Game Days** — минимум 1 раз в квартал. Это не только техническая проверка, но и тренировка команды.
12. **Используйте Resilience as Code** — хаос-эксперименты хранятся в Git рядом с манифестами приложения. Процесс review обязателен.
13. **Валидируйте Observability перед экспериментом** — если мониторинг не видит сбой, эксперимент бессмысленен. Проверьте алерты, дашборды, trace coverage.
14. **Синхронизируйте с DR-планом** — если у вас есть сценарии Disaster Recovery, хаос-эксперименты должны их покрывать (failover БД, восстановление кеша).
15. **Анализируйте инциденты** — каждый production incident — это готовый сценарий для хаос-эксперимента. Воспроизведите отказ в контролируемых условиях.

### Избегайте ошибок

16. **Не используйте средние значения** — мониторьте p99/p999, а не average latency. Среднее скрывает «хвосты», которые разрушают production.
17. **Не маскируйте Retry Storm** — при анализе проверяйте не только Error Rate, но и RPS. Клиентские ретраи могут создать «шторм запросов».
18. **Не проверяйте только кэш** — если при отключении БД сервис продолжает отдавать 200 OK из кэша, эксперимент может показаться успешным. Проверяйте `cache_hit_ratio` и `db_query_duration`.
19. **Не делайте эксперименты бесконечными** — фиксируйте duration в манифесте. Бесконечный эксперимент = непреднамеренный инцидент.
20. **Не дублируйте контент** — за подробными практическими сценариями обращайтесь к [Chaos Engineering — практическое руководство](chaos_engineering_practical.md). Здесь сосредоточены только инструменты и их операционная специфика.

## Дополнительная информация

### Сравнение: LitmusChaos vs Chaos Mesh vs Gremlin

| Характеристика | LitmusChaos | Chaos Mesh | Gremlin |
|:---|:---|:---|:---|
| **Установка** | Helm, kubectl | Helm | платформа |
| **UI** | Litmus Portal | Chaos Mesh Dashboard | Gremlin Dashboard |
| **Типы сбоев** | Pod, Network, IO, CPU, Memory | Pod, Network, IO, Kernel, Time | Pod, Network, CPU, Memory, State |
| **Kubernetes** | CRD-based | CRD-based | Agent-based |
| **Enterprise** |混沌 игры |混沌游戏 |混沌游戏 |

### Выбор инструмента: Критерии

1.  **Среда выполнения:** Если только K8s — Chaos Mesh или Litmus. Если гибрид — Gremlin или Steadybit.
2.  **Глубина атаки:** Если нужны сбои в логике приложения (Application Chaos) — Chaosblade или Steadybit.
3.  **Уровень экспертизы:** Для начинающих — Gremlin/Steadybit (Dashboard-first). Для опытных — Chaos Mesh (YAML/CRD-first).

### Resilience as Code (RaC)

Современный подход подразумевает:
*   **GitOps:** Хаос-эксперименты хранятся в репозитории рядом с манифестами приложения.
*   **Quality Gates:** Новая версия приложения не проходит в Prod, если она не выдержала автоматизированный хаос-тест в Staging-среде.
*   **Observability First:** Инструмент хаоса должен автоматически подтягивать графики из Prometheus/Datadog для валидации гипотез.

### См. также
* [Обзор Chaos Engineering](chaos_engineering_overview.md)
* [Концепция Chaos Monkey](chaos_monkey_concept.md)
* [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — установка LitmusChaos/Chaos Mesh, Game Days, шаблоны runbook
* **[Нагрузочное тестирование с помощью k6](../Testing/k6_load_testing.md)** — использование k6 для генерации реалистичной нагрузки во время инъекции сбоев (см. раздел "Тестирование хаоса с k6").
* [Chaos Engineering — тестирование resilience-паттернов](chaos_resilience_patterns_testing.md) — Circuit Breaker, Bulkhead, Rate Limiter.
* [Chaos Engineering — service mesh](chaos_service_mesh.md) — Istio/Envoy fault injection.
* [Chaos Engineering — application-level chaos](chaos_application_level.md) — exception injection, thread pool exhaustion.
* [Chaos Engineering — non-Kubernetes](chaos_non_kubernetes.md) — Pumba, Toxiproxy, VM chaos.
