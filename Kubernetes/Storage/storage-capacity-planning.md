# Планирование ёмкости и квоты хранилища в Kubernetes

## Определения

**Capacity Planning (Планирование ёмкости)** — процесс расчёта требуемого объёма дискового пространства с учётом текущей нагрузки, роста данных, репликации и запаса. Неправильное планирование приводит к простоям приложений (Full OSD, No space left) или перерасходу бюджета.

**ResourceQuota** — объект Kubernetes, ограничивающий суммарный объём PVC (и других ресурсов) в namespace. Предотвращает «проглатывание» всего свободного места одним проектом.

**LimitRange** — объект Kubernetes, задающий минимальные и максимальные размеры PVC в namespace. Не даёт создать слишком маленький или слишком большой том.

**Overprovisioning** — выделение томов сверх физически доступного места (в Longhorn по умолчанию 200%). Основан на предположении, что не все тома будут заполнены одновременно. Опасно при высокой утилизации.

**Thin Provisioning** — механизм, при котором физические блоки выделяются не при создании тома, а при первой записи данных. Позволяет «продавать» больше места, чем есть физически. Требует мониторинга реального использования.

**Full Ratio** — порог заполнения СХД, при котором запись блокируется. В Ceph по умолчанию `mon_osd_full_ratio = 0.95` (95%). При достижении кластер переходит в `HEALTH_ERR`.

**Связанные темы:**
- [StorageClass](./storageclass.md) — параметры выделения томов.
- [Longhorn — Overprovisioning](./longhorn.md) — избыточное provisionирование.
- [Ceph — мониторинг заполнения](./Ceph/Administration/monitoring.md) — пороги и алерты.

---

## Теоретический блок

### Формула расчёта необходимого объёма

```
Требуемый объём = (Данные приложения × (1 + Рост_год)) × Коэффициент_репликации × (1 + Запас)
```

| Параметр | Описание | Пример |
|:---|:---|:---|
| **Данные приложения** | Текущий объём данных | 100 ГБ |
| **Рост_год** | Годовой рост данных (0.2 = 20%) | 0.5 (50% рост) |
| **Коэффициент_репликации** | Количество копий данных | 3 (Longhorn default) |
| **Запас** | Запас на снапшоты, temporary, overhead | 0.3 (30%) |

**Пример:** 100 ГБ × 1.5 × 3 × 1.3 = 585 ГБ физического места.

### Типичные ошибки расчёта

| Ошибка | Результат | Как избежать |
|:---|:---|:---|
| Не учтена репликация | Ceph/Longhorn заполняется за месяцы | Умножать на factor репликации |
| Не учтён overhead ФС | ext4/XFS занимает ~5% на метаданные | Добавлять 5-10% |
| Не учтены снапшоты | Снимки заполняют диск | Учитывать размер снапшотов и retention policy |
| Overprovisioning без мониторинга | Кластер уходит в `HEALTH_ERR` | Настроить алерты на 70%/85%/95% |

### Пороги заполнения в Ceph

| Порог | Значение по умолчанию | Действие при достижении |
|:---|:---|:---|
| `backfillfull_ratio` | 0.90 (90%) | Приостановка backfill/recovery |
| `nearfull_ratio` | 0.85 (85%) | Предупреждение, начало расширения |
| `full_ratio` | 0.95 (95%) | Блокировка записи, `HEALTH_ERR` |

---

## Практический блок

### 1. ResourceQuota для хранилища

Ограничивает суммарный объём PVC в namespace.

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: storage-quota
  namespace: development
spec:
  hard:
    requests.storage: 100Gi          # Суммарный объём всех PVC
    persistentvolumeclaims: "10"      # Максимум количество PVC
    storageclass.storage.k8s.io/requests.storage:  # Ограничение по StorageClass
      ssd: 50Gi
      hdd: 200Gi
```

**Проверка использования:**
```bash
kubectl get resourcequota -n development
# → NAME           AGE   REQUEST               LIMIT
# → storage-quota  5d    requests.storage: 45Gi/100Gi, persistentvolumeclaims: 6/10

kubectl describe resourcequota storage-quota -n development
```

### 2. LimitRange для PVC

Задаёт min/max размер для PVC в namespace.

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: pvc-limits
  namespace: development
spec:
  limits:
  - type: PersistentVolumeClaim
    min:
      storage: 1Gi      # Минимальный размер PVC
    max:
      storage: 50Gi      # Максимальный размер PVC
    default:
      storage: 10Gi      # Размер по умолчанию
    defaultRequest:
      storage: 5Gi       # Размер запроса по умолчанию
```

**Попытка создать PVC больше max:**
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: too-big-pvc
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 100Gi    # > max 50Gi → ошибка
EOF
# → Error: PersistentVolumeClaim "too-big-pvc" is invalid:
#    spec.resources[storage]: Forbidden: exceeded quota
```

### 3. Мониторинг использования

#### Prometheus метрики

```promql
# Использование PVC (% от объёма)
kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes * 100

# Алерт: PVC заполнен на 85%
kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.85

# Свободное место в байтах
kubelet_volume_stats_available_bytes

# Использование inodes
kubelet_volume_stats_inodes_used / kubelet_volume_stats_inodes_total > 0.85
```

#### Алерт-правило (PrometheusRule)

```yaml
groups:
- name: storage-alerts
  rules:
  - alert: PVCHighUsage
    expr: |
      kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.85
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "PVC {{ $labels.persistentvolumeclaim }} заполнен на {{ $value | humanizePercentage }}"

  - alert: PVCNearFull
    expr: |
      kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.90
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "PVC {{ $labels.persistentvolumeclaim }} заполнен на {{ $value | humanizePercentage }} — требуется расширение или очистка"

  - alert: LowDiskSpace
    expr: |
      kubelet_volume_stats_available_bytes < 10 * 1024 * 1024 * 1024
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "На PVC {{ $labels.persistentvolumeclaim }} менее 10 ГБ свободного места"
```

### 4. Расширение заполненного PVC

```bash
# 1. Проверить текущий размер
kubectl get pvc <name> -o jsonpath='{.spec.resources.requests.storage}'
# → 20Gi

# 2. Убедиться, что StorageClass поддерживает expansion
kubectl get sc <sc-name> -o jsonpath='{.allowVolumeExpansion}'
# → true

# 3. Расширить PVC (только вверх!)
kubectl patch pvc <name> -p '{"spec":{"resources":{"requests":{"storage":"40Gi"}}}}'

# 4. Проверить статус расширения
kubectl get pvc <name>
# → STATUS: Bound (норма), или Bound + Resizing=True (в процессе)

# 5. Если ФС не расширилась онлайн — перезапустить под
kubectl delete pod <pod-using-pvc>
# Под пересоздастся, ФС расширится при монтировании
```

### 5. Рекомендации по ёмкости для разных workload-ов

| Workload | Рекомендуемый запас | Фактор репликации | Примечание |
|:---|:---|:---|:---|
| PostgreSQL/MySQL | 30-50% | 3 (Longhorn) или 3x (Ceph) | Учитывать WAL, temp tables |
| Elasticsearch | 30-40% | 3 (副本) | Учитывать segment merges |
| Kafka | 50-100% | 3 (replication factor) | Логи растут быстро, нужен retention |
| MinIO/S3 | 20-30% | Зависит от конфигурации | Квоты на bucket level |
| Prometheus | 20-30% | 1 (обычно без репликации) | Хранить ≤ 15 дней на диске |
| GitOps (ArgoCD) | 10-20% | 1 | Метаданные, не данные |

---

## Дополнительная информация

### Чеклист перед запуском production-нагрузки

- [ ] Рассчитан объём с учётом репликации и роста
- [ ] Настроены ResourceQuota в namespace
- [ ] Настроены LimitRange для PVC (min/max)
- [ ] Настроены алерты на заполнение (85%, 90%, 95%)
- [ ] Включено `allowVolumeExpansion: true` в StorageClass
- [ ] Проверена производительность (fio тест)
- [ ] Настроены бэкапы (Velero / CSI Snapshots)
- [ ] Задокументирован план расширения

### См. также

- [StorageClass](./storageclass.md) — параметры выделения томов.
- [Storage Decision Matrix](./storage-decision-matrix.md) — выбор хранилища.
- [Storage Performance Testing](./storage-performance-testing.md) — тестирование производительности.
- [Ceph — мониторинг](./Ceph/Administration/monitoring.md) — пороги заполнения.
