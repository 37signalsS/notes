# Инструменты Chaos Engineering

## 1. Определения

**Инструменты Chaos Engineering** — это программное обеспечение, которое позволяет автоматизировать и безопасно проводить эксперименты по внесению сбоев в систему. Они предоставляют API и UI для управления жизненным циклом эксперимента: от инъекции сбоя до его прекращения и сбора результатов.

## 2. Основные концепции

### Обзор популярных инструментов

* **Chaos Mesh:** Kubernetes-native инструмент, использующий CRD для декларативного описания хаос-экспериментов. Позволяет управлять сбоями подов, сети, системы ввода-вывода и др.
* **LitmusChaos:** CNCF-проект с большим каталогом готовых экспериментов (ChaosHub) и веб-интерфейсом для управления. Активно развивается (версия 3.26+, 2026), CNCF Incubating.
* **Chaosblade:** CNCF Sandbox проект от Alibaba, простой и мощный инструмент для инъекции хаоса. Поддерживает Linux, Docker и Kubernetes.
* **Gremlin:** Коммерческая SaaS-платформа, поддерживающая различные среды (не только Kubernetes) и предоставляющая продвинутые функции безопасности.
* **AWS Fault Injection Simulator (FIS) и Azure Chaos Studio:** Нативные облачные сервисы для проведения экспериментов над ресурсами AWS и Azure соответственно.

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

### Требования к наблюдаемости

Хаос-эксперименты требуют качественной наблюдаемости для валидации гипотез. Убедитесь, что:

* Метрики (Prometheus, Grafana) покрывают все критические SLI.
* Трассировки (Jaeger, Tempo) позволяют отслеживать цепочки вызовов между сервисами.
* Логи централизованы и доступны для анализа в реальном времени.

### Сравнительная таблица инструментов

| Инструмент | Среда | Модель | UI | Лицензия |
|---|---|---|---|---|
| Chaos Mesh | Kubernetes | CRD | Да | CNCF Incubating |
| LitmusChaos | Kubernetes | CRD + ChaosHub | Да | CNCF Incubating |
| Chaosblade | Linux/Docker/K8s | CLI/Agent | Нет | CNCF Sandbox |
| Gremlin | Хосты/K8s/VM | Агент + SaaS | Да | Коммерческий |
| AWS FIS | AWS | Облачный сервис | Да | Сервис |
| Azure Chaos Studio | Azure | Облачный сервис | Да | Сервис |

### Связанные концепции

* [Обзор Chaos Engineering](chaos_engineering_overview.md)
* [Observability (Наблюдаемость)](../Concepts/Observability_and_Monitoring/observability_overview.md)
