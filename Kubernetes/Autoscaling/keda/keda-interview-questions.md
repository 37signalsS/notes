# KEDA: Вопросы для собеседования

## Определения

Данный материал систематизирует типичные вопросы по KEDA на технических собеседованиях для DevOps/SRE/Sysadmin позиций. Вопросы сгруппированы по уровням сложности и тематикам.

## Теоретический блок

### Базовый уровень (Junior/Middle)

**Q1: Что такое KEDA и зачем она нужна?**

**A:** KEDA (Kubernetes Event-driven Autoscaling) — легковесный оператор Kubernetes для автоматического масштабирования подов на основе внешних событий (очереди Kafka/RabbitMQ, метрики Prometheus, расписание cron). Основное отличие от стандартного HPA — поддержка scale-to-zero (полная остановка подов при отсутствии нагрузки) и 60+ внешних источников метрик.

---

**Q2: Чем KEDA отличается от стандартного HPA?**

**A:**

| Характеристика | HPA | KEDA |
|:---|:---|:---|
| Масштабирование до 0 | Нет (минимум 1) | Да |
| Источники метрик | CPU/RAM | 60+ внешних источников |
| Механизм | Опрос Metrics API | Событийный + External Metrics API |
| Типы нагрузок | Deployment, StatefulSet | + Jobs, Custom Resources |
| Сложная логика | Базовые порога | Scaling Modifiers, Fallback, Multiple Triggers |

KEDA не заменяет HPA, а дополняет: KEDA создаёт HPA под капотом и передаёт ему внешние метрики.

---

**Q3: Как работает scale-to-zero в KEDA?**

**A:** Когда количество событий (длина очереди, lag) падает до 0, KEDA уменьшает количество реплик до `minReplicaCount` (включая 0). При появлении первого события KEDA напрямую обновляет `/scale` подресурс Deployment, создавая первый под. Когда запущен хотя бы один под, в дело вступает HPA.

---

**Q4: Что такое ScaledObject и ScaledJob?**

**A:** ScaledObject — CRD для масштабирования долгоживущих объектов (Deployment, StatefulSet). KEDA создаёт и управляет HPA для каждого ScaledObject. ScaledJob — CRD для масштабирования задач типа Job: вместо изменения реплик KEDA создаёт новую Job для каждого события.

---

**Q5: Что такое Scaler в KEDA?**

**A:** Scaler — компонент, интегрирующийся с конкретным источником событий (Kafka, RabbitMQ, Prometheus и др.). Скейлер опрашивает источник с интервалом `pollingInterval` и возвращает метрику, на основе которой HPA принимает решение о масштабировании.

---

**Q6: Как KEDA взаимодействует с Cluster Autoscaler?**

**A:** Цепочка: KEDA масштабирует поды через HPA → при нехватке ресурсов поды переходят в Pending → Cluster Autoscaler добавляет узлы → при scale-to-zero KEDA удаляет поды → CA видит пустые узлы и удаляет их. Важно настроить `--scale-down-delay-after-add` для предотвращения "пинг-понга".

---

**Q7: Что такое TriggerAuthentication и ClusterTriggerAuthentication?**

**A:** TriggerAuthentication — ресурс для безопасного хранения credentials (пароли, токены, IAM роли) в namespace. ClusterTriggerAuthentication — глобальный аналог для использования во всех namespace. Оба ссылаются на Kubernetes Secrets и предотвращают хардкод паролей в манифестах ScaledObject.

---

**Q8: Что такое fallback в KEDA?**

**A:** Механизм аварийного переключения: если источник метрик недоступен N раз подряд (`failureThreshold`), KEDA переводит workload в fallback-режим с фиксированным количеством реплик (`fallback.replicas`). Поведение настраивается: `static`, `currentReplicas`, `currentReplicasIfHigher`, `currentReplicasIfLower`.

---

### Средний уровень (Middle/Senior)

**Q9: Как работает формула расчёта реплик в KEDA?**

**A:** KEDA использует ту же формулу что и HPA:

```text
desiredReplicas = ceil(currentReplicas × (currentMetricValue / targetValue))
```

При нескольких триггерах — MAX среди всех триггеров. При metric = 0 и minReplicaCount = 0 — scale-to-zero.

---

**Q10: Что будет, если KEDA упадёт?**

**A:** HPA продолжит работать с последней известной метрикой. Новые ScaledObject не создадутся, метрики перестанут обновляться, workload останется на текущем количестве реплик. Состояние подов keda-operator и keda-metrics-apiserver должно быть под мониторингом.

---

**Q11: Как настроить масштабирование по очереди Kafka?**

**A:** Использовать ScaledObject с триггером `type: kafka`, указать `bootstrapServers`, `consumerGroup`, `topic`, `lagThreshold`. Аутентификация через TriggerAuthentication (SASL/PLAIN, SASL/SCRAM, mTLS). Важно: maxReplicaCount не должен превышать количество партиций в топике.

---

**Q12: Как измерить cold start и что с ним делать?**

**A:** Замер: `kube_pod_status_ready_time - kube_pod_created`. Если cold start > SLA: (1) `minReplicaCount: 1` вместо 0, (2) оптимизировать Docker image (multi-stage build), (3) настроить readiness probe, (4) для HTTP Add-on использовать Interceptor для буферизации запросов.

---

**Q13: Что такое activationThreshold и чем он отличается от trigger threshold?**

**A:** `activationThreshold` — минимальное значение метрики для "пробуждения" ресурса (перехода 0 → 1). Если метрика выше activationThreshold, но ниже основного порога, KEDA создаст 1 под, но HPA не будет масштабировать дальше. Предотвращает запуск подов при единичных сообщениях.

---

**Q14: Как KEDA работает с PDB (Pod Disruption Budget)?**

**A:** KEDA управляет количеством реплик через HPA. HPA при scale-down уменьшает `replicas`, но PDB не блокирует этот процесс напрямую (PDB блокирует только Eviction API). Однако если после scale-down количество реплик < minAvailable PDB, это может нарушить availability. Решение: настроить `behavior.scaleDown` с ограничением скорости и `minAvailable` в PDB <= maxReplicaCount.

---

**Q15: Как предотвратить flapping (частое масштабирование вверх/вниз)?**

**A:** (1) Увеличить `cooldownPeriod` (600с вместо 300), (2) настроить `stabilizationWindowSeconds` в behavior.scaleDown (300-600с), (3) увеличить порог триггера (более грубая гранулярность), (4) использовать `selectPolicy: Min` для консервативного scale-down.

---

**Q16: KEDA + GitOps (ArgoCD): какие проблемы и как решать?**

**A:** ArgoCD с selfHeal: true конфликтует с HPA/KEDA: HPA меняет `spec.replicas`, ArgoCD возвращает значение из Git. Решение: `ignoreDifferences` с `managedFieldsManagers: [kube-controller-manager]` или `jsonPointers: ["/spec/replicas"]`. Порядок деплоя: сначала ScaledObject, потом Deployment.

---

### Продвинутый уровень (Senior/Staff)

**Q17: Как работает Scaling Modifiers в KEDA v2.20?**

**A:** Scaling Modifiers — логическая надстройка над триггерами, позволяющая изменять финальное значение метрики перед передачей в HPA через формулу `formula: "metricValue * 1.5"`. Полезно для: boost масштабирования, комбинирования метрик с весами, кастомной логики.

---

**Q18: Как KEDA интегрируется с OpenTelemetry?**

**A:** KEDA поддерживает нативную выгрузку метрик и трейсов через OTLP. Включается через Helm values: `otel.enabled=true`, `otel.collectorUri`, `otel.protocol`. Доступны метрики `scaling_latency` для анализа задержки от события до запуска пода.

---

**Q19: Какие метрики KEDA критичны для мониторинга в production?**

**A:**
- `keda_scaler_errors_total` — ошибки скейлера (critical)
- `keda_scaledobject_replicas` vs `keda_scaledobject_max_replicas` — приближение к лимиту
- `keda_scaler_metrics_latency` — задержка получения метрики
- `keda_scaler_active` — количество активных ScaledObjects

---

**Q20: Как влияет pollingInterval на нагрузку и реактивность?**

**A:** При pollingInterval = 30с: 100 ScaledObject = 3.3 опроса/сек (минимальная нагрузка). При pollingInterval = 5с: 20 опросов/сек (значительная). Рекомендация: 15-30с для большинства сценариев, 5-10с для критичных сервисов, 30-60с для batch-задач.

---

**Q21: Как KEDA работает с VPA?**

**A:** KEDA масштабирует количество реплик (HPA), VPA — размер ресурсов подов. Совместное использование допускается при разнесении метрик: HPA по внешней метрике (RabbitMQ, Prometheus) + VPA по CPU/Memory. Запрещено: HPA по CPU + VPA по CPU (гонка масштабирования).

---

**Q22: Как KEDA влияет на FinOps?**

**A:** Три FinOps-механизма: (1) scale-to-zero — 0 подов без нагрузки = 0 расходов на compute, (2) maxReplicaCount — финансовый предохранитель от runaway scaling, (3) привязка к бизнес-нагрузке (очередь, RPS) вместо CPU/RAM. Экономия 40-70% на workloads с непостоянной нагрузкой.

---

**Q23: Как тестировать KEDA перед production?**

**A:** (1) Functional: масштабирование вверх/вниз, scale-to-zero, (2) Cold start: замер времени, (3) Fallback: инжект ошибки скейлера, (4) Chaos: network partition через Chaos Mesh, (5) PDB: проверка что scale-down не нарушает availability, (6) ResourceQuota: проверка что квота не блокирует масштабирование.

---

**Q24: Какие типичные ошибки при настройке KEDA?**

**A:** (1) maxReplicaCount > число партиций Kafka (лишние поды idle), (2) не настроен fallback (KEDA падает при сбое источника), (3) credentials в YAML вместо Secret, (4) pollingInterval < 5с (нагрузка на источник), (5) HPA behavior не настроен (flapping), (6) PDB минимум > maxReplicaCount (блокировка масштабирования).

---

**Q25: KEDA vs Prometheus Adapter — когда что использовать?**

**A:** Prometheus Adapter: если метрики уже в Prometheus и scale-to-zero не нужен (HPA по custom метрике). KEDA: если нужен scale-to-zero, метрики из внешних систем (Kafka, RabbitMQ), или множество триггеров. KEDA проще в настройке для типовых сценариев, Prometheus Adapter гибче для кастомных метрик.

---

### Сценарные вопросы

**Q26: Ваш воркер RabbitMQ обрабатывает 1000 сообщений/сек, но KEDA не успевает масштабировать. Очередь растёт. Что делать?**

**A:** (1) Уменьшить `pollingInterval` (30 → 10с), (2) увеличить `maxReplicaCount`, (3) настроить агрессивный `behavior.scaleUp` (stabilizationWindowSeconds: 0, Percent: 100, periodSeconds: 15), (4) проверить downstream лимиты (DB connections, API rate limits), (5) оптимизировать код (batching, async processing).

---

**Q27: После обновления KEDA с 2.19 на 2.20 ScaledObject перестал масштабировать. Как диагностировать?**

**A:** (1) Проверить CRD: `kubectl get crd | grep keda`, (2) проверить логи оператора: `kubectl logs -n keda deploy/keda-operator | grep -i error`, (3) проверить upgrade notes релиза 2.20, (4) проверить ScaledObject status: `kubectl describe so <name>`, (5) проверить HPA: `kubectl get hpa`, (6) при необходимости откат: `helm rollback keda <revision>`.

---

**Q28: Масштабирование по Prometheus, но KEDA показывает <unknown>. Как troubleshoot?**

**A:** (1) Проверить PromQL вручную через curl к Prometheus API, (2) убедиться что query возвращает scalar/vector с одним элементом (добавить `sum()`), (3) проверить `serverAddress` в ScaledObject, (4) проверить NetworkPolicy между KEDA и Prometheus, (5) проверить логи: `kubectl logs -n keda deploy/keda-operator | grep <name>`, (6) проверить External Metrics API: `kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1"`.

---

## Дополнительная информация

### Структура ответа на собеседовании

Хороший ответ на вопрос по KEDA должен содержать:
1. **Что это:** определение и ключевая идея
2. **Зачем:** какую проблему решает
3. **Как работает:** архитектура и ключевые компоненты
4. **Практика:** конкретные примеры из опыта или конфигурации
5. **Ловушки:** типичные ошибки и как их избегать

### См. также

* [KEDA: Основные концепции](./keda_concepts.md) — полная теория
* [KEDA: Практические сценарии](./practical_scenarios.md) — YAML-примеры
* [KEDA: Эксплуатация](./keda-operations.md) — troubleshooting
* [HPA: Советы для собеседования](../HPA/index.md#советы-для-собеседования) — HPA Q&A
