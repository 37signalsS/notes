# Pod Terminating — финализаторы и проблемы CSI

## Определения

**Финализатор (Finalizer)** — механизм защиты от удаления: API server не удаляет объект из `etcd`, пока массив `metadata.finalizers` не станет пустым. Каждый финализатор представляет собой строку-идентификатор контроллера, ответственного за очистку (cleanup).

**VolumeAttachment** — объект Kubernetes, представляющий операцию присоединения тома (PersistentVolume) к узлу. Управляется компонентом `external-attacher` CSI-драйвера.

**CSI-драйвер (Container Storage Interface driver)** — стандартный интерфейс для подключения внешних систем хранения к Kubernetes. Состоит из центральных контроллеров (attacher, provisioner) и агентов на узлах (node plugin в виде DaemonSet).

**`external-attacher/<driver-name>`** — стандартный финализатор, добавляемый контроллером `external-attacher`. Блокирует удаление объекта Pod до успешного подтверждения отсоединения тома (detach).

---

## Базовые концепции

### Механизм блокировки удаления

Процесс удаления объекта с финализаторами:

1. Выполнение команды `kubectl delete`.
2. API server устанавливает `deletionTimestamp`.
3. API server проверяет наличие финализаторов в `metadata.finalizers`.
4. Если список не пуст — объект переходит в состояние `Terminating`, но остается в `etcd`.
5. Соответствующий контроллер (например, CSI) выполняет операции очистки.
6. Контроллер удаляет свой идентификатор из списка финализаторов.
7. Когда список становится пустым, API server окончательно удаляет объект.

### Типичные финализаторы, блокирующие удаление

| Финализатор | Контроллер | Описание блокировки |
| :--- | :--- | :--- |
| `external-attacher/<csi-driver>` | CSI external-attacher | Ожидание отсоединения тома (Volume detachment). |
| `kubernetes.io/pvc-protection` | PVC protection controller | Защита PVC от удаления, пока он используется подом. |
| `foregroundDeletion` | Garbage Collector | Ожидание удаления дочерних объектов. |
| `kubernetes.io/pod-protection` | Kubelet / API server | Общая защита жизненного цикла пода. |

### Роль CSI-драйвера в блокировке

CSI-драйвер управляет жизненным циклом томов через несколько компонентов:

- **external-attacher** — управляет объектами `VolumeAttachment` (операции attach/detach).
- **external-provisioner** — создание и удаление физических томов.
- **node plugin (DaemonSet)** — операции монтирования и размонтирования (mount/unmount) на файловой системе узла.

Зависание пода в `Terminating` часто вызвано тем, что `external-attacher` не может завершить операцию `detach` и снять финализатор.

Подробная диагностика: [Диагностика](./diagnostics.md). Базовые термины: [Определения](./definitions.md).

---

## Практические сценарии

### Сценарий 1: Финализатор CSI не удаляется

**Симптом:**
Под находится в состоянии `Terminating`, в списке финализаторов присутствует запись `external-attacher/...`.

```bash
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'
# → ["external-attacher/ebs.csi.aws.com"]
```

**Причина:** Контроллер `external-attacher` не может выполнить `detach` из-за ошибок Cloud Provider API, таймаутов или лимитов (rate limiting).

**Диагностика:**

```bash
# 1. Проверка статуса компонентов CSI
kubectl get pods -n kube-system -l app.kubernetes.io/instance=<driver-name>

# 2. Поиск связанных VolumeAttachment
kubectl get volumeattachment | grep <pod-uid>

# 3. Анализ ошибок в VolumeAttachment
kubectl describe volumeattachment <attachment-name>
# Искать: FailedDetachVolume, таймауты API

# 4. Проверка логов контроллера
kubectl logs -n kube-system -l app=csi-attacher -c csi-attacher --tail=100
```

**Решение А: Удаление зависшего VolumeAttachment**
Если контроллер застрял на удалении объекта, можно попробовать удалить его вручную:

```bash
kubectl delete volumeattachment <attachment-name>
```

После удаления объекта контроллер обычно снимает финализатор с пода.

**Решение Б: Принудительная очистка финализаторов (крайняя мера)**
Используется только если инфраструктура (узел/хранилище) уничтожена и корректный `detach` невозможен.

```bash
kubectl patch pod <pod-name> -p '{"metadata":{"finalizers":null}}' --type=merge
```

**Внимание:** это действие не отсоединяет том физически. Том может остаться «примонтированным» к узлу на уровне облачного провайдера.

### Сценарий 2: Ошибки внутреннего состояния CSI-драйвера

**Симптом:**
В логах или событиях видны ошибки `rpc error: code = Internal desc = volume detachment failed`.

**Причина:** Сбой в работе подов драйвера, рассинхронизация состояния между Kubernetes и storage backend.

**Решение:**

1. Перезапуск контроллеров драйвера:

   ```bash
   kubectl rollout restart deployment -n kube-system <csi-controller-deployment>
   ```

2. Перезапуск агентов на узлах:

   ```bash
   kubectl rollout restart daemonset -n kube-system <csi-node-daemonset>
   ```

### Сценарий 3: Блокировка финализатором PVC protection

**Симптом:**
Финализатор `kubernetes.io/pvc-protection` мешает удалению объекта.

**Диагностика и решение:**

1. Проверьте, не используется ли PVC другими подами:

   ```bash
   kubectl describe pvc <pvc-name>
   ```

2. Если PVC свободен, но финализатор остался, его можно снять вручную:

   ```bash
   kubectl patch pvc <pvc-name> -p '{"metadata":{"finalizers":null}}'
   ```

---

## Дополнительная информация

**См. также:**

- [Ошибки размонтирования томов](./volume_unmount_issues.md) — проблемы на уровне узла (mount point).
- [Диагностика Pod Terminating](./diagnostics.md) — общий алгоритм поиска причин зависания.
- [Определения Pod Terminating](./definitions.md) — базовые термины и механизмы.
