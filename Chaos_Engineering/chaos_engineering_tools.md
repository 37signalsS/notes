# Инструменты Chaos Engineering

## 1. Определения

**Инструменты Chaos Engineering** — это программное обеспечение, которое позволяет автоматизировать и безопасно проводить эксперименты по внесению сбоев в систему. Они предоставляют API и UI для управления жизненным циклом эксперимента: от инъекции сбоя до его прекращения и сбора результатов.

## 2. Основные концепции

### Обзор популярных инструментов

*   **Chaos Mesh:** Kubernetes-native инструмент, использующий CRD для декларативного описания хаос-экспериментов. Позволяет управлять сбоями подов, сети, системы ввода-вывода и др.
*   **LitmusChaos:** CNCF-проект с большим каталогом готовых экспериментов (ChaosHub) и веб-интерфейсом для управления.
*   **Gremlin:** Коммерческая SaaS-платформа, поддерживающая различные среды (не только Kubernetes) и предоставляющая продвинутые функции безопасности.
*   **AWS Fault Injection Simulator (FIS) и Azure Chaos Studio:** Нативные облачные сервисы для проведения экспериментов над ресурсами AWS и Azure соответственно.

## 3. Практические сценарии

### Пример 1: Удаление подов с помощью Chaos Mesh

Этот манифест на 90 секунд завершает 30% подов с меткой `app=payments`.
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
  duration: "90s"
```

### Пример 2: Удаление подов с помощью LitmusChaos
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
```

## 4. Дополнительная информация

### Сравнительная таблица инструментов

| Инструмент | Среда | Модель | UI | Лицензия |
|---|---|---|---|---|
| Chaos Mesh | Kubernetes | CRD | Да | Open Source |
| LitmusChaos | Kubernetes | CRD + ChaosHub | Да | Open Source |
| Gremlin | Хосты/K8s/VM | Агент + SaaS | Да | Коммерческий |
| AWS FIS | AWS | Облачный сервис | Да | Сервис |
| Azure Chaos Studio | Azure | Облачный сервис | Да | Сервис |

### Связанные концепции
*   [[chaos_engineering_overview.md|Обзор Chaos Engineering]]
