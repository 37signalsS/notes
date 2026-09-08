# NFS Production Pitfalls в контексте CSI

## Определения

**NFS Production Pitfalls** — типичные проблемы и ограничения, возникающие при эксплуатации NFS-хранилища в Kubernetes через CSI-драйвер `nfs.csi.k8s.io` или внешние provisioner (`nfs-subdir-external-provisioner`), которые критичны для продакшен-нагрузок и могут привести к потере данных, простою приложений или деградации производительности.

Ключевые отличия NFS от блочных CSI-драйверов:
- NFS — сетевая файловая система с централизованным сервером (SPOF)
- Метаданные и блокировки обрабатываются на стороне сервера
- Консистентность параллельного доступа зависит от версии NFS и настроек

---

## Теоретический блок

### Архитектурные ограничения NFS в Kubernetes

#### 1. Блокировки (NFS Locking)

NFSv3 и NFSv4 реализуют блокировки принципиально differently:

| Параметр | NFSv3 | NFSv4 |
| :--- | :--- | :--- |
| **Протокол блокировок** | NLM (Network Lock Manager) + portmap | Встроен в NFSv4 ( stateful) |
| **Порты** | Динамические (lockd: 32768-32800, statd: 662) | Единый порт 2049 |
| **Проблемы с NAT/Firewall** | Критичны (динамические порты) | Отсутствуют |
| **Reboot recovery** | Сложный (NLM replay) | Простой (stateful протокол) |
| **flock/fcntl** | Ограниченно | Полная поддержка |

**Практическое следствие:** При использовании NFSv3 в Kubernetes:
- `lockd` и `statd` должны быть запущены и на сервере, и на клиенте
- Фаервол должен разрешать динамические порты (32768-32800)
- После рестарта NFS-клиента блокировки могут «потеряться» → data corruption
- PostgreSQL, MySQL и другие СУБД **недопустимы** на NFSv3 из-за проблем с блокировками

#### 2. Маппинг UID/GID (idmapd)

```bash
# Типичная проблема: файлы создаются как "nobody:nogroup"
# Причина: несовпадение UID между NFS-сервером и клиентом
ls -la /mnt/nfs/
# → -rw-r--r-- 1 nobody nogroup 1234 Jan 1 all.txt

# NFSv4: маппинг через rpc.idmapd
# NFSv3: маппинг через auth_unix (mapstatic в exports)
```

**Механизм маппинга:**
- NFSv4: `rpc.idmapd` + `/etc/idmapd.conf` → преобразование UID/GID через name service
- NFSv3: `maproot`/`mapall` в `/etc/exports` → статический маппинг
- Kubernetes: `fsGroup` в SecurityContext не влияет на маппинг NFS — права задаются сервером

#### 3. SPOF (Single Point of Failure)

NFS-сервер — единственный точка отказа:
- При падении NFS-сервера **все** PV на NFS-бэкенде становятся недоступны
- kubelet не может размонтировать том → поды зависают в Terminating
- NFS-сервер с высокой нагрузкой → деградация всех подов, использующих NFS

#### 4. Производительность: Metadata-Heavy Operations

```bash
# Каждый stat()/ls() — это NFS-запрос к серверу
# find /mnt/nfs -name "*.log" — генерирует thousands NFS-запросов
# Это катастрофически медленно на больших директориях

# Пример: nginx с 100K файлов в одном каталоге
ls /mnt/nfs/logs/ | wc -l    # 10+ секунд через NFS
ls /local/logs/ | wc -l       # <1 секунды локально
```

**Кэширование метаданных:**
- `actimeo` / `noac` — контроль времени кэширования метаданных на клиенте
- Слишком долгое кэширование → «старые» данные; слишком короткое → нагрузка на сервер
- По умолчанию NFSv4: `actimeo=60` — приемлемо для большинства сценариев

#### 5. Write Ordering и Data Loss

```bash
# NFS не гарантирует атомарность rename() на NFSv3
# NFSv4 добавляет delegation, но не решает все проблемы

# Сценарий потери данных:
# 1. Приложение пишет файл на NFS через буфер ядра
# 2. Происходит restart приложения (SIGKILL)
# 3. Данные в буфере не сброшены → потеря данных
# Решение: fsync() + hard mount (no soft)
```

### Mount Options для продакшена

| Опция | Рекомендация | Описание |
| :--- | :--- | :--- |
| `hard` | **Всегда** | При недоступности сервера повторять запросы бесконечно (не терять данные) |
| `noatime` | Рекомендуется | Не обновлять atime → снижение нагрузки |
| `rsize` / `wsize` | 1048576 (1 МБ) | Максимальный размер блока чтения/записи |
| `nconnect` | Включить | Параллельные TCP-соединения к серверу (устраняет bottleneck) |
| `nfsvers` | **4.2** | Актуальная версия с наилучшей безопасностью |
| `noresvport` | Для HA | Не резервироватьпорт (требуется для failover) |
| `timeo` | 600 (60 сек) | Таймаут перед retry ( дефолт: 600 = 60 сек) |
| `retrans` | 2 | Количество повторов перед ESCIENORES |
| `tcp` | **Всегда** | NFS over UDP ненадёжен |

### Типовые неисправности NFS в Kubernetes

| Симптом | Вероятная причина | Метод решения |
| :--- | :--- | :--- |
| `Stale file handle` | NFS-export был пересоздан или сервер перезапущен | `umount -f /mnt/nfs && mount -t nfs4 ...` или restart пода |
| `Permission denied` (uid=nobody) | Несовпадение UID/GID, не настроен idmapd | Проверить `/etc/idmapd.conf`, `rpc.idmapd`, `exports` |
| `Connection timed out` | NFS-сервер недоступен или firewall блокирует порты | `ping <nfs-server>`, `rpcinfo -p <nfs-server>`, проверить firewall |
| `NLM: failed to register` (NFSv3) | lockd/statd не запущены | `systemctl enable --now rpcbind lockd statd` |
| `Transport endpoint is not connected` | NFS-маунт «умер» (сервер перезапущен) | `mount -t nfs4 ...` или restart пода |
| Под завис в Terminating | NFS-сервер недоступен, kubelet не может unmount | Восстановить NFS-сервер; если невозможно — `kubectl delete pod --force --grace-period=0` |
| Низкая скорость записи | Маленький `wsize`, нет `nconnect`, много metadata | Увеличить `wsize`, включить `nconnect`, использовать `actimeo=1` |

---

## Практический блок

### Настройка NFS-клиента для Kubernetes

```bash
# Установка NFS-клиента (Debian/Ubuntu)
apt-get install -y nfs-common

# Проверка доступности NFS-сервера с узла
showmount -e <nfs-server-ip>
# → Export list for <nfs-server-ip>:
# → /exports/kubernetes *

# Тестовое монтирование
mount -t nfs4 -o hard,noatime,rsize=1048576,wsize=1048576,nconnect=16 \
  <nfs-server-ip>:/exports/kubernetes /mnt/test-nfs
ls /mnt/test-nfs
umount /mnt/test-nfs
```

### StorageClass для NFS CSI с оптимальными параметрами

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-hard
provisioner: nfs.csi.k8s.io
parameters:
  server: <nfs-server-ip>
  share: /exports/kubernetes
  # Секрет для аутентификации (если требуется)
  csi.storage.k8s.io/provisioner-secret-name: nfs-credentials
  csi.storage.k8s.io/provisioner-secret-namespace: kube-system
mountOptions:
  - hard
  - noatime
  - rsize=1048576
  - wsize=1048576
  - nconnect=16
  - nfsvers=4.2
  - noresvport
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: Immediate
```

### SecurityContext для подов на NFS

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nfs-app
spec:
  securityContext:
    fsGroup: 1000          # Группа для NFS-файлов (влияет только на права)
    runAsUser: 1000
    runAsGroup: 1000
  containers:
    - name: app
      image: nginx
      volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: nfs-pvc
```

> **Важно:** `fsGroup` в SecurityContext работает с NFS, но маппинг зависит от настроек сервера (`all_squash`/`no_root_squash` в exports, `idmapd.conf` на клиенте).

### Мониторинг NFS-сервера

```bash
# Проверка активных подключений на NFS-сервере
rpcinfo -p <nfs-server-ip> | grep nfs
# → 100003  4    tcp6   2049  nfs
# → 100003  3    tcp6   2049  nfs

# Количество активных NFS-клиентов
cat /proc/net/rpc/nfsd | head -5
# → line 3: thread count, access count

# Мониторинг через nfsiostat (если установлен nfs-utils)
nfsiostat 5

# Проверка использования NFS через /proc
cat /proc/mounts | grep nfs
# → <nfs-server>:/exports/kubernetes /var/lib/kubelet/pods/.../volumes/kubernetes.io~nfs/data nfs4 ...
```

### Алертинг для NFS

```yaml
# Prometheus alert rules для NFS
groups:
  - name: nfs_alerts
    rules:
      - alert: NFSExportInaccessible
        expr: absent(up{job="nfs-exporter"} == 1)
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "NFS export {{ $labels.export }} недоступен"

      - alert: NFSServerHighLatency
        expr: nfs_request_duration_seconds{quantile="0.99"} > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая латентность NFS-сервера {{ $labels.server }}"

      - alert: NFSPVUsageHigh
        expr: |
          kubelet_volume_stats_used_bytes{namespace=~".*", persistentvolumeclaim=~"nfs-.*"}
          / kubelet_volume_stats_capacity_bytes{namespace=~".*", persistentvolumeclaim=~"nfs-.*"} > 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "NFS PVC {{ $labels.persistentvolumeclaim }} заполнена на {{ $value | humanizePercentage }}"
```

### Чеклист перед запуском NFS в продакшене

- [ ] NFSv4.2 (не NFSv3) — без динамических портов, stateful протокол
- [ ] `hard` mount (никогда `soft`) — data loss при transient failures
- [ ] `nconnect=16` — параллельные TCP-соединения
- [ ] `rsize/wsize=1048576` — максимальный размер блока
- [ ] `noatime` — снижение нагрузки
- [ ] NFS-сервер в HA-конфигурации (DRBD + Pacemaker, или расшаренная СХД)
- [ ] Мониторинг NFS-сервера (nfsiostat, rpcinfo, алерты)
- [ ] Регулярные бэкапы NFS-данных (вне Kubernetes, через Velero или rsync)
- [ ] NFS-сервер **не** используется для СУБД (PostgreSQL, MySQL)
- [ ] Проверка lockd/statd (для NFSv3, если невозможно перейти на v4)

---

## Дополнительная информация

### Связанные темы
- [Обзор CSI](./csi_overview.md) — архитектура и жизненный цикл
- [Сравнение CSI-драйверов](./csi_drivers_comparison.md) — NFS в таблице возможностей
- [S3 CSI-драйверы](./s3-csi-drivers.md) — альтернатива NFS для RWX
- [PV, PVC и StorageClass](../pv_and_pvc.md) — базовые операции с томами
- [NFS — Настройка сервера](../../../../Linux/Networking/Services/nfs/nfs_setup.md) — серверная часть
- [NFS — Производительность](../../../../Linux/Networking/Services/nfs/nfs_performance.md) — тюнинг NFS
- [NFS — Диагностика](../../../../Linux/Networking/Services/nfs/nfs_troubleshooting.md) — troubleshooting

### Официальные источники
- [NFS CSI Driver](https://github.com/kubernetes-csi/csi-driver-nfs) — официальный CSI-драйвер NFS
- [NFS Mount Options](https://www.man7.org/linux/man-pages/man8/mount.nfs.8.html) — все опции монтирования
- [NFS Locking](https://www.rfc-editor.org/rfc/rfc1813) — NFSv3 спецификация (Bumper spec)
