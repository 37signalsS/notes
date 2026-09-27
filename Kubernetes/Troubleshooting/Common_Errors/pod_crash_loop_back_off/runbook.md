# Runbook: Реагирование на CrashLoopBackOff

## Определения

**Runbook CrashLoopBackOff** — пошаговая инструкция для дежурного инженера (SRE/Sysadmin) по диагностике и устранению циклических перезапусков контейнеров в Kubernetes. Назначение документа — минимизация времени восстановления (MTTR) через стандартизированный алгоритм действий.

> **Контекст:** Каждый алерт на `CrashLoopBackOff` должен содержать ссылку на данный runbook через аннотацию `runbook_url`.

## Основные концепции

### Формат runbook

Runbook — это конкретный набор инструкций, который должен быть понятен дежурному инженеру без дополнительных объяснений. Структура:

1. **Контекст:** Что мониторится, почему это важно.
2. **Симптомы:** Как выглядит проблема (алерт, логи, статусы).
3. **Диагностика:** Пошаговые команды для определения причины.
4. **Решение:** Конкретные действия по устранению.
5. **Верификация:** Как убедиться, что проблема решена.
6. **Эскалация:** Кого вызвать, если решение не помогло.

### Метрики качества runbook

| Метрика | Описание | Целевое значение |
|:--------|:---------|:-----------------|
| **Runbook Coverage** | Доля алертов с runbook / общее число алертов | 100% (SEV1/SEV2) |
| **MTTR Delta** | Сравнение MTTR для алертов с runbook vs без | На 30–50% ниже |
| **Freshness Score** | % runbook, обновленных за последние 90 дней | >90% |

## Пошаговый алгоритм реагирования

### Шаг 1: Триаж (первые 60 секунд)

**Цель:** Определить критичность и масштаб проблемы.

```bash
# 1. Проверка статуса пода
kubectl get pod <pod-name> -o wide
# → Observe: STATUS, RESTARTS, AGE, NODE

# 2. Количество перезапусков за последние 15 минут
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].restartCount}'

# 3. Причина последнего завершения
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'
# → OOMKilled / Error / RuntimeError

# 4. Exit code
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.exitCode}'
```

**Критичность:**

| Exit Code | Критичность | Действие |
|:----------|:------------|:---------|
| 137 (OOMKilled) | High | Увеличить лимиты памяти |
| 1 (Error) | Medium | Проверить логи приложения |
| 125 (Runtime Error) | High | Проверить CRI и манифест |
| 0 (Success) | Low | Проверить CMD/ENTRYPOINT |

### Шаг 2: Анализ событий и логов

**Цель:** Определить корневую причину падения.

```bash
# 1. События пода (фильтрация по Warning)
kubectl events --for pod/<pod-name> --types=Warning --watch

# 2. Логи предыдущего запуска
kubectl logs <pod-name> --previous

# 3. Если несколько контейнеров
kubectl logs <pod-name> -c <container-name> --previous

# 4. Termination message
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.message}'
```

**Типичные симптомы:**

| Симптом | Вероятная причина | Ссылка на сценарий |
|:--------|:------------------|:-------------------|
| `OOMKilled` | Недостаточно памяти | [Сценарий 8](#сценарий-8) |
| `Liveness probe failed` | Проблемы с health-эндпоинтом | [Диагностика проб](./diagnostics.md#диагностика-проб-probes) |
| `Forbidden` | RBAC или Admission Controller | [Сценарий 5](#сценарий-5) |
| `connection refused` | Проблемы сетевой связности | [Сценарий 2](#сценарий-2) |
| `file not found` | Отсутствие ConfigMap/Secret | [Сценарий 1](#сценарий-1) |

### Шаг 3: Диагностика по доменам

**Цель:** Систематически исключить проблемные области.

| Домен | Команды диагностики | Действие при проблеме |
|:------|:--------------------|:----------------------|
| **Конфигурация** | `kubectl get configmap,secret -n <ns>` | Проверить имена, namespace, пути монтирования |
| **Сеть / DNS** | `kubectl debug --image=nicolaka/netshoot`, `nslookup`, `curl` | Проверить NetworkPolicy, CoreDNS |
| **RBAC** | `kubectl auth can-i get pods --as=system:serviceaccount:<ns>:<sa>` | Добавить Role/RoleBinding |
| **Ресурсы** | `kubectl top pod`, `kubectl describe node` | Увеличить limits, проверить ResourceQuota |
| **Пробы** | `kubectl get pod -o yaml`, `curl localhost:<port>/healthz` | Настроить startupProbe |
| **Runtime / CRI** | `crictl ps`, `crictl logs`, `journalctl -u kubelet` | Проверить containerd, место на диске |
| **Хранилище** | `kubectl get pv,pvc`, `kubectl describe pod` | Проверить StorageClass, монтирование |
| **Безопасность** | `kubectl get pod -o yaml | grep securityContext` | Проверить PSA, SELinux/AppArmor |

### Шаг 4: Устранение проблемы

**Цель:** Применить решение в зависимости от корневой причины.

**Быстрые исправления (remediation):**

```bash
# 1. Остановка циклических перезапусков
kubectl scale deployment/<name> --replicas=0

# 2. Исправление конфигурации / образа
kubectl set image deployment/<name> app=<name>:<fixed-tag>
kubectl set env deployment/<name> DB_HOST=<correct-db>

# 3. Возврат реплик
kubectl scale deployment/<name> --replicas=1

# 4. Или откат на предыдущую ревизию
kubectl rollout undo deployment/<name>
kubectl rollout undo deployment/<name> --to-revision=2
```

**Drain узла с подами в CrashLoopBackOff:**

```bash
# Проверка PDB
kubectl get pdb -n <ns>

# Вариант 1: Включение AlwaysAllow (Kubernetes v1.31+)
kubectl patch pdb <name> -p '{"spec":{"unhealthyPodEvictionPolicy":"AlwaysAllow"}}'

# Вариант 2: Принудительное удаление пода
kubectl delete pod <pod-name> --grace-period=0 --force
```

### Шаг 5: Верификация

**Цель:** Убедиться, что проблема решена и под работает стабильно.

```bash
# 1. Проверка статуса пода
kubectl get pod <pod-name> -w
# → READY 1/1, STATUS Running, RESTARTS не растет

# 2. Проверка логов (убедиться, что ошибок нет)
kubectl logs <pod-name> --tail=50

# 3. Проверка потребления ресурсов
kubectl top pod <pod-name>

# 4. Проверка health-эндпоинта
kubectl exec <pod-name> -- curl -sf http://localhost:<port>/healthz

# 5. Проверка restartCount (не должен расти)
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].restartCount}'
```

### Шаг 6: Эскалация

**Цель:** Привлечь дополнительные ресурсы, если проблема не решена.

| Уровень | Кого вызвать | Когда |
|:--------|:-------------|:------|
| L1 | Дежурный SRE | Первичная диагностика |
| L2 | Team Lead / Senior SRE | Сложные случаи, multiple pods affected |
| L3 | Platform Team | Проблемы с CRI, kubelet, etcd |
| L4 | Vendor Support | Проблемы с провайдером хранилища, CNI |

## Мониторинг и алертинг

### Prometheus метрики для мониторинга

```promql
# Контейнеры в CrashLoopBackOff
kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} == 1

# Перезапуски за последние 15 минут
increase(kube_pod_container_status_restarts_total[15m]) > 5

# Процент подов в CrashLoopBackOff
count(kube_pod_status_reason{reason="CrashLoopBackOff"}) / count(kube_pod_status_phase{phase="Running"}) * 100

# OOMKilled события
kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1
```

### Пример PrometheusRule

```yaml
groups:
- name: pod-health
  rules:
  - alert: PodCrashLooping
    expr: increase(kube_pod_container_status_restarts_total[15m]) > 5
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Pod {{ $labels.pod }} в namespace {{ $labels.namespace }} циклично перезапускается"
      runbook_url: "https://wiki.example.com/runbooks/crashloopbackoff"
      dashboard_url: "https://grafana.example.com/d/pod-health"

  - alert: PodOOMKilled
    expr: kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Pod {{ $labels.pod }} завершён по OOMKilled"
      runbook_url: "https://wiki.example.com/runbooks/oomkilled"
```

## Post-mortem анализ

### Формат post-mortem

После каждого значимого инцидента (SEV1/SEV2) проводится анализ:

1. **Временная шкала:** Когда обнаружен, когда устранен, сколько длился инцидент.
2. **Корневая причина:** Что именно вызвало проблему.
3. **Влияние:** Сколько пользователей/сервисов пострадало.
4. **Что сработало:** Какие алерты/ Runbook помогли.
5. **Что не сработало:** Какие шаги оказались неэффективными.
6. **Рекомендации:** Как предотвратить повторение.

### Шаблон post-mortem

```markdown
# Post-mortem: CrashLoopBackOff в <service-name>

## Временная шкала
- **Обнаружение:** YYYY-MM-DD HH:MM (алерт PodCrashLooping)
- **Реагирование:** YYYY-MM-DD HH:MM (дежурный начал диагностику)
- **Устранение:** YYYY-MM-DD HH:MM (проблема решена)
- **Длительность:** X часов Y минут

## Корневая причина
<Описание корневой причины>

## Влияние
- Сервис: <service-name>
- Namespace: <namespace>
- Пользователи: <количество/описание>

## Что сработало
- Алерт PodCrashLooping сработал через 5 минут
- Runbook позволил быстро локализовать проблему

## Что не сработало
- Liveness probe не отслеживала проблему с БД

## Рекомендации
1. Добавить init-контейнер для проверки доступности БД
2. Обновить runbook с учетом нового сценария
```

## Дополнительная информация

### См. также

- **[Диагностика CrashLoopBackOff](./diagnostics.md)** — пошаговый алгоритм поиска неисправностей.
- **[Распространенные решения](./common_cases_and_solutions.md)** — 30 типовых сценариев.
- **[Определения и концепции](./definitions_and_concepts.md)** — теория, BackOff, RestartPolicy.
- **[Продвинутые темы](./advanced_topics.md)** — eBPF, Cgroup v2, Native Sidecars.
- **[Runbook Engineering](../../../../Concepts/sre_concepts_main.md)** — методология создания runbook.
- **[Incident Response](../../../../CI-CD/Core_Concepts/incident_response_sre.md)** — жизненный цикл инцидентов.
