# Алертинг и мониторинг компонентов Autoscaling

## Определения

**Alerting** — процесс генерации уведомлений при нарушении пороговых значений метрик. В контексте autoscaling алерты позволяют обнаружить ситуации, когда масштабирование не работает корректно, поды застревают в Pending или компоненты недоступны.

**PrometheusRule** — CRD Prometheus Operator, определяющий группы правил алертинга и recording rules. Правила записываются на PromQL и проверяются Prometheus на каждом цикле (по умолчанию 1 минута).

**SLI/SLO для autoscaling** — индикаторы уровня сервиса: доступность HPA, время отклика на scale-up, доля неуспешных масштабирований.

---

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
|-----------|-------------------|---------------|------------|
| Prometheus | 2.45+ | 2.50+ | PromQL, Alertmanager |
| kube-state-metrics | 2.7+ | 2.10+ | Метрики состояния HPA, PDB, Deployment |
| Prometheus Operator | 0.65+ | 0.70+ | Управление PrometheusRule |
| Alertmanager | 0.26+ | 0.27+ | Доставка алертов |

---

## Теоретический блок

### Источники метрик autoscaling

| Источник | Метрики | Что даёт |
|----------|---------|----------|
| **kube-state-metrics** | `kube_hpa_*`, `kube_deployment_status_replicas`, `kube_pdb_*` | Состояние HPA, текущее/желаемое количество реплик, PDB |
| **Prometheus** (cpu/memory) | `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes` | Реальное потребление ресурсов |
| **Cluster Autoscaler** | `cluster_autoscaler_*` | Статус CA, количество pending-подов, scale-up/down |
| **Metrics Server** | `container_cpu_usage_seconds_total` | Базовые метрики для HPA |
| **Custom Metrics** | Зависит от адаптера | RPS, latency, queue length |

### Метрики HPA (kube-state-metrics)

```promql
# Текущее количество реплик HPA
kube_hpa_status_current_replicas

# Желаемое количество реплик HPA
kube_hpa_status_desired_replicas

# Целевая утилизация CPU
kube_hpa_spec_target_metric{metric="cpu"}

# Условия HPA (AbleToScale, ScalingActive, ScalingLimited)
kube_hpa_status_condition{condition="ScalingActive",status="true"}

# Все HPA в состоянии ScalingLimited
kube_hpa_status_condition{condition="ScalingLimited",status="true"} == 1
```

### Метрики Cluster Autoscaler

```promql
# Количество неуспешных scale-up за 10 минут
increase(cluster_autoscaler_failed_scale_ups_total[10m])

# Количество Pending-подов, которые CA не может разместить
cluster_autoscaler_unschedulable_pods_count

# CA в состоянии scale-down cooldown
cluster_autoscaler_scale_down_in_cooldown

# Количество удалённых подов при scale-down
cluster_autoscaler_evicted_pods_total

# Последнее действие CA (для детектирования зависания)
cluster_autoscaler_last_activity
```

### Метрики VPA

```promql
# VPA Recommender недоступен
up{job="vpa-recommender"} == 0

# Рекомендации VPA vs реальное потребление
vpa_recommender_container_recommendations_cpu_cores
vpa_recommender_container_recommendations_memory_bytes
```

---

## Практический блок

### Alertmanager правила дляautoscaling

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: autoscaling-alerts
  labels:
    release: prometheus
spec:
  groups:
    - name: autoscaling.rules
      rules:
        # ===== HPA =====
        - alert: HPAScaleUpStuck
          expr: |
            kube_hpa_status_condition{condition="ScalingActive",status="true"} == 1
            and
            kube_hpa_status_desired_replicas > kube_hpa_status_current_replicas
            and
            increase(kube_hpa_status_current_replicas[15m]) == 0
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "HPA {{ $labels.hpa }} не может масштабировать вверх"
            description: |
              HPA хочет {{ $value }} реплик, но не может достичь этой цели.
              Проверьте: PDB, ресурсы узлов, CA.

        - alert: HPAScaleDownTooSlow
          expr: |
            kube_hpa_status_condition{condition="ScalingLimited",status="true"} == 1
            and
            kube_hpa_status_desired_replicas < kube_hpa_status_current_replicas
            and
            increase(kube_hpa_status_current_replicas[1h]) == 0
          for: 1h
          labels:
            severity: warning
          annotations:
            summary: "HPA {{ $labels.hpa }} медленно масштабирует вниз"
            description: |
              HPA хочет {{ $value }} реплик, но scale-down не происходит более 1 часа.

        - alert: HPAAtMaxReplicas
          expr: |
            kube_hpa_status_condition{condition="ScalingLimited",status="true"} == 1
            and
            kube_hpa_status_current_replicas == kube_hpa_spec_max_replicas
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "HPA {{ $labels.hpa }} достиг максимума реплик"
            description: |
              HPA достиг лимита maxReplicas={{ $value }}.
              Увеличьте maxReplicas или оптимизируйте приложение.

        - alert: HPAReplicasMismatch
          expr: |
            abs(kube_hpa_status_desired_replicas - kube_hpa_status_current_replicas) > 2
            and
            increase(kube_hpa_status_current_replicas[10m]) == 0
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "HPA {{ $labels.hpa }}: желаемое не совпадает с текущим"
            description: |
              Желаемое: {{ $labels.kube_hpa_status_desired_replicas }}, текущее: {{ $labels.kube_hpa_status_current_replicas }}.

        # ===== Cluster Autoscaler =====
        - alert: ClusterAutoscalerFailedScaleUp
          expr: increase(cluster_autoscaler_failed_scale_ups_total[10m]) > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "CA не может добавить узлы"
            description: |
              Cluster Autoscaler не может масштабировать кластер.
              Проверьте: квоты облака, права IAM, доступность железа (on-prem).

        - alert: ClusterAutoscalerPendingPods
          expr: cluster_autoscaler_unschedulable_pods_count > 0
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "{{ $value }} подов в Pending (>15 минут)"
            description: |
              Поды не могут быть запланированы более 15 минут.
              CA не может добавить узлы или поды не удовлетворяют ограничениям.

        - alert: ClusterAutoscalerDown
          expr: up{job="cluster-autoscaler"} == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Cluster Autoscaler недоступен"
            description: |
              CA не отвечает более 5 минут. Масштабирование кластера невозможно.

        - alert: ClusterAutoscalerStuck
          expr: |
            time() - cluster_autoscaler_last_activity > 1800
            and
            cluster_autoscaler_unschedulable_pods_count > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "CA завис (нет активности >30 минут при Pending подах)"
            description: |
              CA не выполняет действий более 30 минут, хотя есть Pending поды.

        # ===== VPA =====
        - alert: VPARecommenderDown
          expr: up{job="vpa-recommender"} == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "VPA Recommender недоступен"
            description: |
              VPA не анализирует метрики. Рекомендации не обновляются.

        # ===== Pods =====
        - alert: PodsPendingTooLong
          expr: kube_pod_status_phase{phase="Pending"} > 600
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Под {{ $labels.pod }} в Pending >10 минут"
            description: |
              Pod в namespace {{ $labels.namespace }} не может быть запланирован.
              Проверьте CA, квоты, PDB.

        - alert: PodsCrashLooping
          expr: increase(kube_pod_container_status_restarts_total[1h]) > 5
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Pod {{ $labels.pod }} перезапускается (>5 раз/час)"
            description: |
              Container {{ $labels.container }} перезапускается.
              Проверьте логи: kubectl logs {{ $labels.pod }} -n {{ $labels.namespace }}.

        # ===== Deployment =====
        - alert: DeploymentReplicasMismatch
          expr: |
            kube_deployment_spec_replicas != kube_deployment_status_available_replicas
            and
            increase(kube_deployment_status_available_replicas[30m]) == 0
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "Deployment {{ $labels.deployment }}: реплики не совпадают"
            description: |
              Ожидалось {{ $labels.kube_deployment_spec_replicas }}, доступно {{ $labels.kube_deployment_status_available_replicas }}.
              Проверьте Pending поды и CA.

        # ===== PDB =====
        - alert: PDBMinAvailableExceeded
          expr: |
            kube_poddisruptionbudget_status_current_healthy < kube_poddisruptionbudget_status_desired_healthy
            and
            kube_poddisruptionbudget_spec_min_available > 0
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "PDB {{ $labels.poddisruptionbudget }}: нарушено minAvailable"
            description: |
              Доступных подов меньше, чем требуется PDB.
              Приложение может быть недоступно.
```

### Recording rules для агрегации

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: autoscaling-recording-rules
  labels:
    release: prometheus
spec:
  groups:
    - name: autoscaling.recording
      interval: 30s
      rules:
        # HPA: доля HPA в состоянии ScalingLimited
        - record: autoscaling:hpa_scaling_limited_ratio
          expr: |
            count(kube_hpa_status_condition{condition="ScalingLimited",status="true"} == 1)
            /
            count(kube_hpa_status_condition{condition="ScalingActive",status="true"} == 1)

        # HPA: средняя задержка scale-up (если есть custom metrics)
        - record: autoscaling:hpa_scale_up_delay_seconds
          expr: |
            histogram_quantile(0.95,
              rate(hpa_scaling_duration_seconds_bucket[5m])
            )

        # CA: доля успешных scale-up
        - record: autoscaling:ca_scale_up_success_ratio
          expr: |
            rate(cluster_autoscaler_scaled_up_nodes_total[1h])
            /
            (rate(cluster_autoscaler_scaled_up_nodes_total[1h]) + rate(cluster_autoscaler_failed_scale_ups_total[1h]))
```

### Дашборд Grafana (ключевые панели)

| Панель | Метрика | Тип |
|--------|---------|-----|
| HPA: Текущее vs Желаемое | `kube_hpa_status_current_replicas`, `kube_hpa_status_desired_replicas` | Time series |
| HPA: Утилизация CPU | `kube_hpa_status_condition{condition="ScalingLimited"}` | Gauge |
| CA: Pending поды | `cluster_autoscaler_unschedulable_pods_count` | Stat |
| CA: Scale-up/down | `cluster_autoscaler_scaled_up_nodes_total`, `cluster_autoscaler_scaled_down_nodes_total` | Counter |
| PDB: Disruptions Allowed | `kube_poddisruptionbudget_status_current_healthy - kube_poddisruptionbudget_status_desired_healthy` | Gauge |
| Pods: Pending/Running | `kube_pod_status_phase` | Pie chart |

---

## Дополнительная информация

### SLI/SLO для autoscaling

| SLI | Метрика | SLO |
|-----|---------|-----|
| **HPA Availability** | `kube_hpa_status_condition{condition="ScalingActive"}` | 99.9% времени в состоянии Active |
| **Scale-up Latency** | Время от Pending до Ready | < 5 минут для критичных сервисов |
| **CA Success Rate** | `1 - (failed_scale_ups / total_scale_ups)` | > 99% успешных scale-up |
| **Pod Scheduling Success** | Доля подов, запланированных за < 5 минут | > 99% |

### Диагностика по алертам

| Алерт | Первичные действия | Глубокая диагностика |
|-------|-------------------|---------------------|
| HPAScaleUpStuck | `kubectl describe hpa <name>` | PDB, ресурсы узлов, CA логи |
| ClusterAutoscalerFailedScaleUp | `kubectl logs -n kube-system -l app=cluster-autoscaler` | Квоты облака, права IAM |
| PodsPendingTooLong | `kubectl describe pod <name>` | Events, node selectors, taints |
| VPARecommenderDown | `kubectl get pods -n kube-system -l app=vpa-recommender` | Логи, RBAC, доступность API |

### См. также

- [Cluster Autoscaler](cluster_autoscaler_detailed.md) — метрики CA
- [HPA: Продвинутые темы](HPA/hpa_advanced.md) — диагностика Conditions
- [HPA: Устранение неполадок](../Troubleshooting/Common_Errors/hpa_troubleshooting.md) — чек-лист диагностики
- [VPA: Глубокое погружение](vpa_detailed.md) — метрики VPA
- [Overview: Алертинг](overview_concepts.md#сценарий-5-мониторинг-событий-масштабирования) — базовые алерты
