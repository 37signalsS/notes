# Pod Evicted: Выселение по диску (Disk Eviction)

## Определения

**DiskPressure Eviction** — защитный механизм `kubelet`, который принудительно завершает поды при критической нехватке дискового пространства или индексных дескрипторов (inodes). Процесс инициируется, когда узел переходит в состояние `DiskPressure=True`.

**Эфемерное хранилище (Ephemeral storage)** — временное дисковое пространство узла, используемое подами. Оно включает:
*   **Слой записи контейнера (Writable layer):** Изменения в файловой системе контейнера во время работы.
*   **Логи контейнеров:** Файлы в `/var/log/pods`.
*   **Тома типа `emptyDir`:** Локальные данные, время жизни которых ограничено временем жизни пода.

**Порог выселения (Eviction Threshold)** — лимит ресурсов, при пересечении которого `kubelet` начинает освобождение места.
*   **Hard Threshold:** Немедленное выселение (по умолчанию `nodefs.available < 10%`, `nodefs.inodesFree < 5%`).
*   **Soft Threshold:** Выселение после льготного периода (grace period).

Общие определения и типы выселения: **[Pod Evicted: Определения](./definitions.md)**.

## Основные концепции

### Разделение файловых систем (nodefs vs imagefs)

Kubernetes отслеживает два типа разделов через `Eviction Manager`:

1.  **`nodefs` (Основная ФС):** Корневой раздел узла. Содержит логи, локальное хранилище `kubelet` (`/var/lib/kubelet`), тома `emptyDir` и рабочие директории рантайма (если не выделен `imagefs`).
2.  **`imagefs` (ФС образов):** Опциональный выделенный раздел для рантайма (containerd/CRI-O). Используется для хранения кэша образов и слоев записи контейнеров.

| Раздел | Метрики Kubelet | Что занимает место |
|:---|:---|:---|
| **`nodefs`** | `nodefs.available`, `nodefs.inodesFree` | `/var/log`, `/var/lib/kubelet` (`emptyDir`), `/var/lib/containerd` (если нет `imagefs`) |
| **`imagefs`** | `imagefs.available`, `imagefs.inodesFree` | Кэш образов, Snapshot-ы рантайма, слои записи (writable layers) |

**Архитектурная рекомендация:** Вынесение `/var/lib/containerd` на отдельный диск (логический раздел) изолирует рост логов приложения от кэша образов. Это предотвращает ситуацию, когда из-за переполнения логов удаляются образы, что приводит к циклической ошибке `ImagePullBackOff`.

### Алгоритм Garbage Collection (GC) диска

Перед выселением подов `kubelet` выполняет следующие шаги для очистки места:

1.  **Контейнерный GC:** Удаление всех завершенных (exited) контейнеров и их слоев записи.
2.  **Образный GC:** Если использование `imagefs` (или `nodefs`, если `imagefs` нет) превысило `HighThresholdPercent` (по умолчанию 85%), удаляются неиспользуемые образы, пока использование не упадет до `LowThresholdPercent` (по умолчанию 80%).
3.  **Выселение (Eviction):** Если GC не помог и свободное место все еще ниже Hard Threshold, начинается выбор кандидатов на выселение.

### Порядок (Priority) выселения при DiskPressure

Кандидаты выбираются по следующей логике:
1.  **Нарушители лимитов:** Поды, потребление `ephemeral-storage` которых превышает `limits.ephemeral-storage`.
2.  **BestEffort / Burstable без запросов:** Поды, у которых не указаны `requests.ephemeral-storage`.
3.  **Относительное превышение:** Поды, у которых разница `Usage - Requests` максимально велика.

## Практические сценарии

### 1. Диагностика состояния узла и пода

При выселении под получает статус `Failed` с причиной `Evicted` и сообщением `The node was low on resource: ephemeral-storage`.

```bash
# 1. Проверка условий узла (Conditions)
kubectl describe node <node-name> | grep -A 5 Conditions
# Результат: DiskPressure: True

# 2. Проверка Taints (узел помечается автоматически)
kubectl describe node <node-name> | grep Taints
# Результат: node.kubernetes.io/disk-pressure:NoSchedule

# 3. Проверка сообщения в поде
kubectl get pod <pod-name> -o jsonpath='{.status.message}'
```

**Логи Kubelet (`journalctl -u kubelet`):**
Ищите записи о нехватке места:
`eviction manager: attempting to reclaim nodefs`
`eviction manager: pod <pod> is evicted because it exceeds its ephemeral-storage limit`

### 2. Поиск причин переполнения на узле

Если место закончилось на `nodefs`:

```bash
# Анализ emptyDir (тома подов)
du -sh /var/lib/kubelet/pods/*/volumes/kubernetes.io~empty-dir/* | sort -rh | head -n 5

# Анализ логов (если ротация контейнеров не справляется)
du -sh /var/log/pods/* | sort -rh | head -n 5

# Проверка удаленных, но удерживаемых файлов (deleted but held open)
# Если df показывает 100%, а du - 50%, проверьте этот пункт
lsof +L1 | grep deleted
```

Если место закончилось на `imagefs`:

```bash
# Просмотр использования диска через crictl
crictl stats

# Список самых тяжелых образов
crictl images --sort-by size
```

### 3. Проблема Inode Exhaustion

Иногда `DiskPressure` возникает при наличии свободного места в гигабайтах, но при исчерпании лимита на количество файлов (Inodes). Это характерно для приложений, создающих миллионы мелких файлов.

```bash
# Проверка количества свободных Inodes
df -i

# Поиск директории с наибольшим количеством файлов
find /var/lib/kubelet/pods -type d -exec sh -c 'echo -n "{}: "; ls -1 "{}" | wc -l' \; | sort -n -k 2
```

### 4. Настройка лимитов (Resource Management)

Всегда ограничивайте эфемерное хранилище, чтобы один под не "уронил" весь узел.

```yaml
spec:
  containers:
  - name: app
    resources:
      requests:
        ephemeral-storage: "1Gi"
      limits:
        ephemeral-storage: "2Gi" # Kubelet выселит под при превышении 2Gi
  volumeMounts:
  - name: temp-data
    mountPath: /tmp
spec:
  volumes:
  - name: temp-data
    emptyDir:
      sizeLimit: "500Mi" # Лимит конкретно для этого тома
```

## Дополнительная информация

### Настройка порогов (KubeletConfiguration)

Для современных узлов с большими дисками (1ТБ+) использование процентов неэффективно. Рекомендуется использовать абсолютные значения.

```yaml
# /var/lib/kubelet/config.yaml
evictionHard:
  nodefs.available: "5Gi"      # Жесткий порог
  nodefs.inodesFree: "1%"
  imagefs.available: "10Gi"
evictionSoft:
  nodefs.available: "10Gi"     # Мягкий порог
evictionSoftGracePeriod:
  nodefs.available: "2m"       # Время на "самоочистку" перед выселением
```

### Мониторинг (PromQL)

```promql
# Узлы в состоянии DiskPressure
kube_node_status_condition{condition="DiskPressure", status="true"} == 1

# Потребление эфемерного хранилища конкретным подом
sum(container_fs_usage_bytes{container!=""}) by (pod, namespace)

# Прогноз исчерпания Inodes на узле (на основе тренда за 6 часов)
predict_linear(node_filesystem_files_free{mountpoint="/"}[6h], 3600 * 24) < 0
```

### См. также

- **[Pod Evicted: Определения](./definitions.md)** — база по типам выселений.
- **[Диагностика выселения](./diagnostics.md)** — общие шаги траблшутинга.
- **[Профилактика выселения](./prevention.md)** — архитектурные меры защиты.
- **[Node Resource Pressure](../NodeUnavailability/resource_pressure.md)** — детали по Inodes и системным дискам.
- **[Управление логами Docker](../../../../Docker/Docker_logs/docker_log_rotation.md)** — настройка ротации на уровне рантайма.
