# Pod Evicted: Выселение по диску (Disk Eviction)

## Определения

**DiskPressure Eviction** — принудительное завершение и выселение подов компонентом kubelet при критической нехватке дискового пространства на узле. Процесс инициируется, когда состояние (condition) узла переходит в `DiskPressure=True`.

**Ephemeral storage (эфемерное хранилище)** — временное дисковое пространство узла, используемое для логов контейнеров, временных файлов, томов `emptyDir` и кэша образов.

**Threshold (порог выселения)** — установленное значение свободного места или inode (индексный дескриптор), при достижении которого начинается выселение. По умолчанию: `< 10%` свободного места или `< 5%` свободных inode.

Общие определения и типы выселения: **[Pod Evicted: Определения](./definitions.md)**.

## Основные концепции

### Источники потребления диска

| Источник | Описание | Путь (типовой) |
|----------|----------|----------------|
| Логи контейнеров | Стандартный вывод (stdout/stderr) приложений | `/var/log/containers/*.log` |
| Тома `emptyDir` | Временные файловые системы подов | `/var/lib/kubelet/pods/<uid>/volumes/...` |
| Image filesystem | Локальный кэш образов контейнеров | `/var/lib/containerd/` или `/var/lib/docker/` |
| Writable layer | Слой записи работающего контейнера | `/var/lib/containerd/.../overlayfs/` |
| Системные логи | Журнал ОС (Operating System — операционная система) | `/var/log/journal/` |

### Пороги выселения в конфигурации kubelet

Настройки хранятся в `/var/lib/kubelet/config.yaml`:

| Параметр | Объект мониторинга | Действие |
|----------|--------------------|----------|
| `nodefs.available` | Раздел `/var/lib/kubelet` | Выселение подов с наибольшим использованием диска |
| `nodefs.inodesFree` | Свободные inode в `nodefs` | Выселение при исчерпании файловых дескрипторов |
| `imagefs.available` | Раздел с образами (если вынесен) | Очистка образов, затем выселение |

### Порядок выселения при DiskPressure

1. **Обнаружение:** Kubelet фиксирует достижение порога (threshold).
2. **Очистка (Image GC — Garbage Collection):** Попытка удалить неиспользуемые образы и контейнеры.
3. **Ранжирование:** Поды сортируются по классу QoS (Quality of Service — качество обслуживания) и фактическому потреблению диска.
4. **Выселение:** Завершение подов, начиная с тех, чье потребление диска максимально превышает `requests`.

## Практические сценарии

### Диагностика

#### Шаг 1: Подтверждение состояния узла

```bash
kubectl describe node <node_name> | grep -A 5 "DiskPressure"
# → DiskPressure   True   ...   Kubelet has critical disk pressure
```

#### Шаг 2: Выявление основных потребителей на узле

Для анализа требуется доступ по SSH (Secure Shell):

```bash
# Общая проверка разделов
df -h

# Проверка использования диска в директории kubelet
df -h /var/lib/kubelet

# Топ-10 подов по потреблению диска в kubelet
du -sh /var/lib/kubelet/pods/* | sort -rh | head -10

# Топ-10 директорий в containerd (образы и слои записи)
du -sh /var/lib/containerd/* | sort -rh | head -10

# Проверка использования inode
df -i /var/lib/kubelet
# → Filesystem     Inodes   IUsed   IFree IUse% Mounted on
# → /dev/sda1      3.2M     3.1M    100K   97% /
```

#### Шаг 3: Сопоставление UID пода с его именем

```bash
kubectl get pods -A -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,NS:.metadata.namespace | grep <pod_uid>
```

### Решение проблемы

#### 1. Ручная очистка ресурсов

Если выселение уже началось, можно ускорить освобождение места:

```bash
# Удаление остановленных (exited) контейнеров
crictl rm $(crictl ps -a -q --state exited)

# Агрессивная очистка неиспользуемых образов
crictl rmi --prune

# Ротация системного журнала
journalctl --vacuum-time=1d
# → Vacuuming done, freed 1.2G of archived journal space.

# Удаление пустых томов emptyDir
find /var/lib/kubelet/pods -name "empty-dir" -type d -empty -delete
```

#### 2. Ограничение потребления (Resource Limits)

Настройте лимиты для эфемерного хранилища в спецификации пода:

```yaml
resources:
  requests:
    ephemeral-storage: "1Gi"
  limits:
    ephemeral-storage: "2Gi" # Под будет выселен при превышении этого значения
```

#### 3. Настройка ротации логов в рантайме

Для `containerd` (файл `/etc/containerd/config.toml`):

```toml
[plugins."io.containerd.grpc.v1.cri".containerd.log]
  max_size = "50Mi"
  max_backups = 3
```

После изменения требуется перезапуск: `systemctl restart containerd`.

## Дополнительная информация

### Профилактика и мониторинг

| Метод | Описание |
|-------|----------|
| **Лимиты ephemeral-storage** | Обязательны для приложений, активно пишущих в `emptyDir` или логи |
| **`emptyDir.sizeLimit`** | Установка жесткого лимита для конкретного тома |
| **Вынос `/var/lib/kubelet`** | Использование отдельного физического диска для данных Kubernetes |
| **Алертинг в Prometheus** | Настройка уведомления при заполнении диска > 80% |

### Смотрите также

- [Pod Evicted: Определения](./definitions.md) — базовые понятия и пороги.
- [Диагностика выселения](./diagnostics.md) — общий алгоритм действий.
- [Node Resource Pressure](../NodeUnavailability/resource_pressure.md) — диагностика со стороны инфраструктуры.
- [Управление логами Docker](../../../../Docker/Docker_logs/docker_log_rotation.md) — настройки для Docker рантайма.
