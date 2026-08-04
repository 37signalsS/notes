# Инструменты Chaos Engineering

## Определения

**Инструменты Chaos Engineering** — это специализированное программное обеспечение, предназначенное для автоматизации, контроля и безопасного проведения экспериментов по внесению сбоев (fault injection). 

Современные инструменты обеспечивают полный жизненный цикл эксперимента: от определения **устойчивого состояния (Steady State)** и валидации гипотез до автоматической остановки (Stop-switch) при превышении порога **радиуса поражения (Blast Radius)**.

## Основные концепции

### Обзор популярных инструментов

*   **Chaos Mesh:** Kubernetes-native платформа, использующая Custom Resource Definitions (CRD). Идеальна для глубокой интеграции с K8s. Позволяет имитировать сбои на уровнях: Pod, Network, File System, Kernel (через BPF) и даже Time (смещение времени).
*   **LitmusChaos:** Один из самых популярных Open Source инструментов (CNCF Incubating). Ключевая особенность — **ChaosHub**, каталог готовых экспериментов. Версия 3.x (2026) предлагает продвинутый веб-интерфейс, поддержку мультикластерности и сложную логику проверок (Probes).
*   **Gremlin:** Коммерческая SaaS-платформа ("Chaos as a Service"). Фокусируется на безопасности и простоте использования. Поддерживает bare-metal, VM и облачные сервисы. Включает уникальный функционал "Detected Dependencies" для автоматического построения карты рисков.
*   **Chaosblade:** Инструмент от Alibaba (CNCF Sandbox). Отличается мощной CLI-утилитой и поддержкой множества языков программирования (Java, C++, Go) для инъекции сбоев на уровне приложения.
*   **Kube-monkey:** Реализация паттерна Chaos Monkey специально для Kubernetes. Простой инструмент, который удаляет поды в случайное время на основе аннотаций в манифестах.

### Облачные нативные сервисы (Managed Chaos)

*   **AWS Fault Injection Simulator (FIS):** Полностью управляемый сервис для AWS. Позволяет создавать сложные сценарии, затрагивающие EC2, RDS, EKS и сетевые компоненты.
*   **Azure Chaos Studio:** Сервис для измерения и повышения устойчивости приложений в Azure. Интегрируется с Azure Monitor для отслеживания влияния сбоев.
*   **Google Cloud Fault Injection:** Функционал, встроенный в Cloud Service Mesh (Istio) и Anthos для управления устойчивостью трафика.

## Практические сценарии

### Пример 1: Инъекция сетевых задержек в Chaos Mesh

Этот манифест добавляет 200 мс задержки (+/- 50 мс) для всех исходящих соединений подов с меткой `app: catalog` в пространстве имен `staging`.

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: network-delay-catalog
spec:
  action: delay
  mode: one
  selector:
    namespaces:
      - staging
    labelSelectors:
      app: catalog
  delay:
    latency: "200ms"
    correlation: "25"
    jitter: "50ms"
  duration: "5m"
```

### Пример 2: Проверка Steady State в LitmusChaos (Probes)

Использование `httpProbe` для подтверждения того, что сервис остается доступным (код 200) во время эксперимента по удалению пода.

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
            mode: "Continuous"
            runProperties:
              probeTimeout: 1000
              interval: 2
```

## Дополнительная информация

### Chaos Engineering в GitOps-пайплайнах

Современная практика подразумевает описание хаос-экспериментов как кода (CaC).
*   **ArgoCD / Flux:** Манифесты `ChaosMesh` или `Litmus` хранятся в Git и синхронизируются с кластером.
*   **Keptn:** Использование хаос-тестов как части Quality Gates в CI/CD для автоматической валидации надежности новых релизов.

### Сравнительная таблица инструментов

| Инструмент | Основная среда | Модель управления | Сложность | Лицензия |
|---|---|---|---|---|
| **Chaos Mesh** | Kubernetes | CRD / Dashboard | Средняя | Apache 2.0 |
| **LitmusChaos** | Multi-K8s | Dashboard / ChaosHub | Высокая | Apache 2.0 |
| **Chaosblade** | Linux / Docker / K8s | CLI / API | Низкая | Apache 2.0 |
| **Gremlin** | Hybrid / Cloud | SaaS / Agent | Низкая | Коммерческая |
| **Kube-monkey** | Kubernetes | Annotations | Очень низкая | MIT |
| **AWS FIS** | AWS | AWS Console / API | Низкая | Сервис |

### См. также

* [Обзор Chaos Engineering](chaos_engineering_overview.md)
* [Концепция Chaos Monkey](chaos_monkey_concept.md)
* [Метрики в Chaos Engineering](chaos_engineering_metrics.md)
* [Observability (Наблюдаемость)](../Concepts/Observability_and_Monitoring/observability_definitions.md)
