# Pod Terminating — проблемы размонтирования томов (Volume Unmount)

## Определения

**Размонтирование тома (Volume Unmount)** — финальный этап жизненного цикла тома на узле (Node), при котором Kubelet отключает файловую систему тома от дерева каталогов хоста. Выполняется строго после остановки всех контейнеров Pod.

**Устаревшее монтирование (Stale Mount)** — состояние, при котором точка монтирования остается активной в ядре ОС или в `mount namespace` Kubelet, хотя объект Pod уже удален из API. Это блокирует удаление PVC/PV и освобождение ресурсов хранилища.

**VFS Refcount (Счётчик ссылок)** — внутренний механизм ядра Linux. `umount` завершится ошибкой `target is busy`, если хотя бы один процесс удерживает открытый дескриптор файла или рабочую директорию внутри тома.

**D-state (Uninterruptible Sleep)** — состояние процесса, ожидающего завершения ввода-вывода (I/O). Такие процессы нельзя завершить сигналом `SIGKILL`, и они блокируют `umount`, так как ядро не может закрыть их дескрипторы.

**Kubelet Volume Manager** — подсистема Kubelet (reconciliation loop), которая сверяет желаемое состояние (Desired State) из API с текущим состоянием (Actual State) на узле и инициирует операции монтирования/размонтирования.

**Подпути (Volume Subpaths)** — механизм Kubernetes для монтирования части тома. Создает дополнительные `bind mounts` в `/var/lib/kubelet/pods/<pod-uid>/volume-subpaths/`. Некорректная очистка подпутей — самая частая причина блокировки основного тома.

**Распространение монтирования (Mount Propagation)** — режимы `None`, `HostToContainer`, `Bidirectional`. При `Bidirectional` контейнер может создавать монтирования, которые "утекают" на хост и требуют ручной очистки при аварии контейнера.

**Lazy Unmount (`umount -l`)** — "ленивое" размонтирование. Немедленно удаляет точку из иерархии ФС, делая её недоступной для новых процессов, но ресурсы освобождаются только после закрытия всех существующих файловых дескрипторов.

---

## Базовые концепции

### Процесс очистки томов (Cleanup Workflow)

Когда Pod переходит в `Terminating`, Kubelet следует строгому алгоритму:

1.  **Graceful Shutdown контейнеров:** Ожидание завершения процессов.
2.  **Проверка Refcount:** Volume Manager проверяет, не используется ли том другими контейнерами того же Pod.
3.  **Очистка подпутей (Recursive Unmount):** Сначала очищаются все `bind mounts` в директории `volume-subpaths`.
4.  **NodeUnmount:** Выполняется системный вызов `umount` для пути в `/var/lib/kubelet/pods/<pod-uid>/volumes/`.
5.  **CSI NodeUnpublish:** Вызов метода `NodeUnpublish` у CSI-драйвера для финализации очистки на уровне узла (удаление устройств, закрытие LUKS).
6.  **Controller Detach:** Внешний AD-контроллер отсоединяет диск от ВМ в облаке (AWS Detach, GCP Unpublish).

### Механизмы блокировки размонтирования

| Фактор | Описание проблемы | Результат |
| :--- | :--- | :--- |
| **Открытые дескрипторы** | Процессы (включая зомби или sidecars) удерживают файлы. | `target is busy` |
| **Осиротевшие контейнеры** | CRI не удалил контейнер, процесс живет и держит том. | Блокировка Refcount |
| **Зависшие Subpaths** | Баг Kubelet при обработке рекурсивных монтирований. | Ошибка `tearDown failed` |
| **Сетевые сбои (NFS/iSCSI)** | При потере связи с сервером `umount` уходит в `D-state`. | Зависание `df`, `ls` |
| **SELinux / AppArmor** | Политики запрещают Kubelet выполнять `umount` из-за контекста. | `Permission denied` |
| **Shared Mounts** | Использование `mount --bind` сторонними агентами бэкапа. | `busy` |

---

## Практические сценарии

### Сценарий 1: Блокировка процессами (In-use)

**Симптом:** Логи Kubelet: `UnmountVolume.tearDown failed for volume ... volume is in use by another process`.

**Диагностика:**
1. Найти UID пода: `kubectl get pod <name> -o jsonpath='{.metadata.uid}'`.
2. Найти процессы, удерживающие файлы (выполнять на узле):
   ```bash
   # Поиск процессов по пути тома
   lsof +D /var/lib/kubelet/pods/<UID>/volumes
   # Альтернатива через fuser (PID и тип доступа)
   fuser -vm /var/lib/kubelet/pods/<UID>/volumes/*/*
   # Проверка осиротевших контейнеров через CRI
   crictl ps -a --pod $(crictl pods --uid <UID> -q)
   ```

**Решение:**
1. Если процесс — "осиротевший" контейнер: `crictl stop <ID> && crictl rm <ID>`.
2. Если процесс сторонний (антивирус, мониторинг) — настроить исключения.
3. Принудительное завершение (крайняя мера): `fuser -ck /var/lib/kubelet/pods/<UID>/volumes/*/*`.

### Сценарий 2: Зависшие подпути (Volume Subpaths)

**Симптом:** Основной том не размонтируется, хотя `lsof` ничего не находит в `volumes`.

**Диагностика:** Проверка активных монтирований в директории подпутей:
```bash
findmnt | grep <UID> | grep "volume-subpaths"
```

**Решение:** Размонтируйте подпути рекурсивно в обратном порядке:
```bash
for subpath in $(findmnt -rn -o TARGET | grep "<UID>/volume-subpaths" | tac); do
  umount -l "$subpath"
done
```

### Сценарий 3: Глубокая проверка через Mount Namespace

**Симптом:** Хост пуст, но Kubelet сообщает об ошибке. Монтирование "застряло" в его namespace.

**Решение:** Войти в namespace Kubelet и проверить `mountinfo`:
```bash
# 1. Найти PID Kubelet
KUBE_PID=$(pidof kubelet)
# 2. Проверка через nsenter
nsenter -t $KUBE_PID -m grep <UID> /proc/self/mountinfo
# 3. Размонтирование внутри namespace
nsenter -t $KUBE_PID -m umount -l <путь-из-mountinfo>
```

### Сценарий 4: Проблемы сетевых ФС (NFS/iSCSI)

**Симптом:** Команда `df -h` зависает. Тайм-аут RPC в логах.

**Диагностика:**
```bash
nfsstat -m
rpcinfo -p <nfs-server-ip>
```

**Решение:** Используйте принудительное (`-f`) и ленивое (`-l`) размонтирование:
```bash
umount -f -l /var/lib/kubelet/pods/<UID>/volumes/kubernetes.io~nfs/<vol-name>
```

### Сценарий 5: Конфликты SELinux

**Симптом:** Ошибки `denied { unmount }` в `audit.log`.

**Диагностика:**
```bash
ausearch -m avc -ts recent | grep unmount
```

**Решение:** Убедитесь, что установлен `container-selinux`. Временная проверка: `setenforce 0`. Если помогло — требуется перемаркировка (`restorecon`).

---

## Дополнительная информация

### Проверка Mount Propagation

При `mountPropagation: Bidirectional` контейнер может пробрасывать монтирования на хост. Если он "умрет", не очистив их, они блокируют родительский том. Ищите такие "утечки" в `/proc/self/mountinfo`.

### Полезные команды для глубокой отладки

*   `lsblk --fs` — проверка блочных устройств и файловых систем.
*   `find /var/lib/kubelet/pods/<UID> -maxdepth 3` — поиск пустых директорий.
*   `journalctl -u kubelet --grep "VolumeManager.*unmount"` — фильтрация логов.

**См. также:**
- [Финализаторы и проблемы CSI](./finalizer_issues.md) — если том не отсоединяется (Detach).
- [Диагностика Pod Terminating](./diagnostics.md) — основной алгоритм.
- [Определения Pod Terminating](./definitions.md) — системные механизмы.
- [Graceful Shutdown](./graceful_shutdown.md) — настройки завершения.
