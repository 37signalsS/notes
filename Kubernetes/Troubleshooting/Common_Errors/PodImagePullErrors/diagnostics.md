# Диагностика ошибок загрузки образов (Image Pull Errors): Пошаговое руководство

## Определения

Основные понятия, термины и архитектурное взаимодействие Kubelet ↔ CRI приведены в разделе [Определения](./definitions.md).

---

## Основные концепции

### Алгоритм системной диагностики

Диагностика в Kubernetes требует последовательного спуска по уровням абстракции:

1.  **L1: API/Resource (Pod)** — Анализ событий и статусов через `kubectl`.
2.  **L2: Authorization (Secrets)** — Проверка `imagePullSecrets` и RBAC.
3.  **L3: Infrastructure (Network)** — DNS, Proxy, Firewall, MTU.
4.  **L4: Runtime Interface (CRI/gRPC)** — Анализ взаимодействия Kubelet с `containerd`/`CRI-O`.
5.  **L5: Host/Storage** — Дисковое пространство, Inodes, Snapshotters (OverlayFS).

### Анализ статус-кодов gRPC в событиях

При взаимодействии Kubelet с рантаймом через CRI, ошибки часто содержат gRPC-коды. Их понимание критично для быстрой локализации:

| Код gRPC | Интерпретация | Значение для анализа |
| :--- | :--- | :--- |
| `DeadlineExceeded` | Timeout | Проблемы сети или крайне медленная загрузка слоев. |
| `Unauthenticated` | 401 Unauthorized | Неверный или отсутствующий `imagePullSecret`. |
| `PermissionDenied` | 403 Forbidden | У учетной записи нет прав на чтение (Pull) в реестре. |
| `NotFound` | 404 Not Found | Образ или тег не существует. |
| `ResourceExhausted` | No space | Переполнение диска на узле (`/var/lib/containerd`). |

---

## Практические сценарии

### Сценарий 1: Инспекция через kubectl (L1-L2)

Первичный сбор данных без доступа к узлу.

**1. Просмотр текущего статуса и причины ожидания:**
```bash
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].state.waiting}'
```

**2. Анализ событий (Events):**
```bash
kubectl get events --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp'
```
*Ищите события `Failed` и сообщения `rpc error`.*

**3. Проверка цепочки секретов:**
```bash
# Проверка домена и auth-данных внутри секрета
kubectl get secret <secret-name> -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .auths
```

### Сценарий 2: Сетевая отладка через эфемерные контейнеры (L3)

Использование `kubectl debug` позволяет запустить отладочный контейнер в сетевом пространстве имен целевого пода.

```bash
# Запуск netshoot внутри неймспейса пода
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<app-container>
```

**Внутри отладочного контейнера:**
```bash
# Проверка разрешения имен реестра
nslookup registry.example.com

# Проверка MTU (частая причина зависания при загрузке больших слоев)
ping -M do -s 1472 registry.example.com

# Проверка TLS-цепочки
openssl s_client -connect registry.example.com:443 -showcerts
```

### Сценарий 3: Глубокая диагностика на узле через crictl (L4)

Если проблема не на уровне Kubernetes, требуется инспекция рантайма.

**1. Подключение к узлу с системным профилем:**
```bash
kubectl debug node/<node-name> -it --image=busybox --profile=sysadmin
# Внутри: chroot /host
```

**2. Инспекция манифеста и архитектуры образа:**
Частая проблема: образ скачан, но не запускается из-за несоответствия архитектуры (например, `arm64` на `amd64`).
```bash
crictl inspecti <image-id> | jq .info.labels
```

**3. Ручная проверка Pull с логированием:**
```bash
# Попытка пулла через CRI с явными кредами
crictl pull --creds "user:pass" registry.example.com/my-app:1.0
```

### Сценарий 4: Отладка Kubelet и CRI (L4-L5)

При сложных ошибках (например, таймауты gRPC или ошибки snapshotter) необходимо повысить уровень логирования Kubelet.

**1. Временное повышение verbosity Kubelet (без перезагрузки):**
```bash
# На узле через SSH/Debug
# ПРИМЕЧАНИЕ: Работает, если Kubelet поддерживает runtime-конфигурацию
curl -X PUT http://localhost:10248/debug/flags/v -d "4"
```

**2. Анализ системных логов:**
```bash
# Логи containerd с фокусом на ошибки snapshotter
journalctl -u containerd -g "error|snapshot"

# Логи Kubelet с фокусом на CRI
journalctl -u kubelet -f | grep "PullImage"
```

---

## Контрольный список (Interview Checklist)

1.  **Namespace-scoped Secrets:** Секрет должен быть в том же неймспейсе, что и Под.
2.  **Architecture Mismatch:** Проверьте, что образ поддерживает архитектуру процессора узла (`amd64`/`arm64`).
3.  **Image GC:** Проверьте, не удаляет ли Garbage Collector (`ImageGCHighThresholdPercent`) образы сразу после загрузки из-за нехватки места.
4.  **Insecure Registry:** Если реестр без TLS, он должен быть явно указан в `config.toml` (containerd).
5.  **Kubelet Serialize Image Pulls:** Если поды зависают на `Pulling`, возможно, включена сериализация (`serializeImagePulls: true`), что замедляет массовые запуски.

---

## Дополнительная информация

### Связанные темы

- [Определения и базовые концепции](./definitions.md) — терминология и статус-коды.
- [Распространённые ошибки](./common_errors.md) — классификация 404, 401, 403.
- [Сетевые проблемы](./network_issues.md) — настройка Proxy, MTU и локальных зеркал.
- [Air-gapped кластеры](./airgapped.md) — диагностика и конфигурация `hosts.toml`.
- [Среды выполнения контейнеров](../../../Concepts/container_runtime.md) — архитектура CRI и низкоуровневая отладка.

