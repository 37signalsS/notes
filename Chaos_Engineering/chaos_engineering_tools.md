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
    *   **Особенности:** Использует декларативный подход и **ChaosHub** (облачный каталог готовых сценариев). Версия 3.x поддерживает мультикластерность и сложные цепочки проверок (Probes).
    *   **Применение:** Построение Enterprise-платформ хаос-инженерии.
*   **Kube-monkey:**
    *   **Особенности:** Реализация паттерна Chaos Monkey для K8s. Удаляет поды на основе аннотаций в Deployment.
    *   **Применение:** Простейшая проверка «выживаемости» сервисов при потере подов.

#### 2. Платформы для гибридных и облачных сред
Поддерживают Bare-metal, виртуальные машины и проприетарные облачные сервисы.

*   **Gremlin:**
    *   **Особенности:** Коммерческая SaaS-платформа ("Resilience Management"). Фокусируется на безопасности и простоте. Функция "Detected Dependencies" автоматически визуализирует риски каскадных сбоев.
*   **Steadybit:**
    *   **Особенности:** Визуальный конструктор экспериментов. Фокус на "Resilience as Code" и автоматическом обнаружении всей топологии системы.
*   **Chaosblade:**
    *   **Особенности:** Инструмент от Alibaba. Мощный CLI и агенты для инъекции сбоев на уровне рантайма (Java, Go, C++), например, выброс исключений в конкретных методах кода.

#### 3. Специализированные и локальные инструменты
*   **Pumba:** Хаос-тестирование специально для Docker-контейнеров (сеть, пауза, удаление).
*   **Toxiproxy:** TCP-прокси для имитации сетевых аномалий в CI/CD и локальной разработке.
*   **PowerfulSeal:** Инструмент для автономного «уничтожения» ресурсов в K8s и облаках (AWS, Azure, GCP).

### Облачные нативные сервисы (Managed Chaos)

| Сервис | Платформа | Ключевые возможности |
|:---|:---|:---|
| **AWS Fault Injection Service (FIS)** | AWS | Сбои в EC2, RDS, EKS, IAM, сетевые прерывания. |
| **Azure Chaos Studio** | Azure | Интеграция с Azure Monitor, инъекция агентских сбоев (CPU/RAM) и инфраструктурных атак. |
| **GCP Fault Injection** | Google Cloud | Интеграция с Anthos и Service Mesh для управления трафиком и отказами. |

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

## Дополнительная информация

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
* [Метрики в Chaos Engineering](chaos_engineering_metrics.md)
* [Observability (Наблюдаемость)](../Concepts/Observability_and_Monitoring/observability_definitions.md)
* **[Нагрузочное тестирование с помощью k6](../Testing/k6_load_testing.md)** — использование k6 для генерации реалистичной нагрузки во время инъекции сбоев (см. раздел "Тестирование хаоса с k6").
