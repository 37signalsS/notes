# Обзор инструментов: Chaos Mesh и аналогичные решения

Chaos Engineering в практике эксплуатации требует инструментов, которые позволяют безопасно и предсказуемо вносить сбои, фиксировать эффекты и ограничивать «радиус поражения». На Kubernetes- и облачных платформах сформировалась экосистема решений с разными моделями внедрения и управления экспериментами. Ниже — обзор ключевых опций и критериев выбора.

## Chaos Mesh: Kubernetes-native подход

Chaos Mesh — оператор Kubernetes, использующий CRD для описания экспериментов. Он ставится в кластер и действует через контроллеры и агенты (chaos-daemon) на узлах.

Особенности:

*   Модель CRD: PodChaos, NetworkChaos, IOChaos, DNSChaos, TimeChaos, StressChaos, HTTPChaos, JVMChaos.
*   Ограничение области воздействия: namespace, label selectors, процент/число объектов (mode: one, fixed, fixed-percent).
*   Управляемая обратимость: duration, пауза/возобновление, аннотации для исключений.
*   Интеграция с наблюдаемостью: события Kubernetes, метрики, совместимость с стандартными пайплайнами мониторинга.
*   Workflow-режим для построения последовательностей и зависимостей экспериментов.

Пример минимального PodChaos, который на 90 секунд завершает 30% подов приложения с меткой app=payments в пространстве prod:

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: kill-payments
spec:
  action: pod-kill
  mode: fixed-percent
  value: "30"
  selector:
    namespaces:
      - prod
    labelSelectors:
      app: payments
  gracePeriod: 0
  duration: "90s"
```

## LitmusChaos и другие решения

*   **LitmusChaos**. CNCF-проект с CRD-моделью, широким каталогом экспериментов и UI (ChaosCenter). Поддерживает workflows, проверочные шаги (steady-state hypothesis), отчеты.
*   **Gremlin**. Коммерческий агентный инструмент для хостов, контейнеров и Kubernetes. Сильные функции безопасных «guardrails», планировщик, проверки, управление «blast radius».
*   **PowerfulSeal**. Скриптуемый инструмент (политики и сценарии), полезен для случайных отключений подов/нод и сетевых экспериментов, ориентирован на гибкость.
*   **AWS Fault Injection Simulator**. Облачный сервис для оркестрации отказов на EC2/EKS/RDS и др., с «stop conditions» по метрикам.
*   **Azure Chaos Studio**. Аналог для ресурсов Azure с интеграцией в нативные сервисы мониторинга и RBAC.
*   **Istio fault injection**. Внедрение задержек и ошибок на уровне сервис-меша. Это не полнофункциональный chaos-инструмент, но полезен для моделирования деградации сетевых путей.

Короткий пример LitmusChaos (удаление подов приложения):

```yaml
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: payments-pod-delete
spec:
  appinfo:
    appns: prod
    applabel: app=payments
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
    - name: pod-delete
      spec:
        components:
          env:
            - name: TOTAL_CHAOS_DURATION
              value: "60"
            - name: CHAOS_INTERVAL
              value: "10"
```

## Сравнение по критериям

| Инструмент             | Среда           | Типы сбоев                     | Планирование/Workflows   | Защитные механизмы          | UI    | Лицензия      |
| ---------------------- | --------------- | ------------------------------ | ------------------------ | --------------------------- | ----- | ------------- |
| Chaos Mesh             | Kubernetes      | Под/сеть/IO/время/JVM/HTTP     | Да (workflows)           | Неймспейсы, селекторы, duration | Есть  | Open Source   |
| LitmusChaos            | Kubernetes      | Каталог готовых экспериментов  | Да (workflows, checks)   | Steady-state checks, RBAC   | Да    | Open Source   |
| Gremlin                | Хосты/K8s/VM    | CPU/память/сеть/выключение     | Да                       | Guardrails, проверки        | Да    | Коммерческий  |
| PowerfulSeal           | Kubernetes/VM   | Под/нода/сеть                  | Скрипты/политики         | Теги/селекторы              | Нет   | Open Source   |
| AWS FIS                | AWS ресурсы     | EC2/EKS/RDS и др.              | Да                       | Stop conditions по метрикам | Да    | Сервис        |
| Azure Chaos Studio     | Azure ресурсы   | Виртуалки/PAAS                 | Да                       | Политики/метрики            | Да    | Сервис        |
| Istio faults           | Service Mesh    | Задержки/ошибки HTTP           | Через манифесты          | Ограничение маршрутов       | Нет   | Open Source   |

При выборе учитывают: среду запуска (Kubernetes vs облако/VM), требуемые типы инъекций, глубину интеграции с мониторингом, наличие UI и рабочих процессов, требования к безопасным ограничениям и соответствие лицензионной модели.
