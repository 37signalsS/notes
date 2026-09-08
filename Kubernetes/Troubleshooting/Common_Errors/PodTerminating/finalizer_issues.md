# Pod Terminating — финализаторы и проблемы CSI

## Определения

**Финализатор (Finalizer)** — механизм в Kubernetes, предотвращающий окончательное удаление объекта из базы данных `etcd`, пока список в поле `metadata.finalizers` не станет пустым. Каждая запись в этом списке сигнализирует API-серверу, что определенный контроллер (или оператор) должен выполнить операции по очистке ресурсов (cleanup) перед физическим удалением записи.

**CSI (Container Storage Interface)** — стандарт, через который Kubernetes взаимодействует с внешними системами хранения. Большинство проблем с удалением подов связано с зависанием финализаторов CSI-контроллеров при попытке отсоединить тома.

**VolumeAttachment** — объект API, представляющий привязку конкретного тома (PersistentVolume) к узлу. Наличие этого объекта с активным финализатором `external-attacher` является основной причиной блокировки завершения Pod.

**AD-контроллер (Attach/Detach Controller)** — компонент `kube-controller-manager`, который координирует операции привязки и отсоединения томов, взаимодействуя с CSI-драйверами.

**Мягкое удаление (Graceful Deletion)** — процесс, при котором объект получает `deletionTimestamp` и ожидает, пока все финализаторы будут сняты соответствующими контроллерами.

**Зависший финализатор (Stuck Finalizer)** — состояние, при котором контроллер, ответственный за снятие финализатора, не может выполнить задачу (из-за ошибки API, отсутствия связи или бага в логике), что блокирует удаление записи из `etcd`. Финализатор считается зависшим, если он не снят более 5 минут после установки `deletionTimestamp`.

**Operator Finalizer** — кастомный финализатор, добавляемый Kubernetes-оператором или Helm для контроля жизненного цикла ресурса. Отличается от системных финализаторов тем, что его снятие зависит от работоспособности конкретного контроллера или оператора.

---

## Базовые концепции

### Дерево решений для быстрой диагностики

```
Pod в Terminating с финализатором
│
├─ Финализатор: kubernetes.io/pod-protection
│  └─ Kubelet не может подтвердить завершение
│     ├─ Узел доступен? → См. node_unavailable_issues.md
│     ├─ Том не размонтируется? → См. volume_unmount_issues.md
│     └─ Kubelet не отвечает? → Проверьте kubelet logs
│
├─ Финализатор: external-attacher/<csi-driver>
│  └─ CSI не может отсоединить том
│     ├─ VolumeAttachment есть? → См. Сценарий 1
│     └─ VolumeAttachment нет? → Проверьте CSI-controller logs
│
├─ Финализатор: kubernetes.io/pvc-protection
│  └─ PVC используется активным подом
│     └─ Найдите под, ссылающийся на PVC → См. Сценарий 3
│
├─ Финализатор: kubernetes.io/pv-protection
│  └─ PV привязан к активному PVC
│     └─ Проверьте, не удалён ли PVC → См. Сценарий 3
│
├─ Финализатор: helm.sh/resource-policy, helm.sh/hooks
│  └─ Helm-ресурс с политикой удаления
│     └─ Проверьте annotations → См. Сценарий 5
│
├─ Финализатор: custom (оператор/CRD)
│  └─ Кастомный контроллер не снимает финализатор
│     ├─ Контроллер работает? → Проверьте deployment/controller logs
│     └─ CR удалён? → Проверьте, не блокирует ли CRD-оператор → См. Сценарий 6
│
└─ Финализатор: vault.security.banzaicloud.com/vault-secrets-webhook
   └─ Сторонний webhook/агент не снимает финализатор
      └─ Проверьте webhook logs → См. Сценарий 7
```

### Механика блокировки на уровне хранилища

Процесс удаления пода со стейтом (PV/PVC) проходит через несколько уровней защиты:

1.  **Pod Protection:** Финализатор `kubernetes.io/pod-protection` гарантирует, что объект Pod не исчезнет из API, пока `kubelet` не подтвердит остановку контейнеров и размонтирование томов на узле.
2.  **Volume Detach:** После размонтирования на узле, AD-контроллер создает запрос к CSI-драйверу на `ControllerUnpublishVolume` (отсоединение от ВМ). Пока это действие не подтверждено облачным API, финализатор `external-attacher` удерживает объект `VolumeAttachment`.
3.  **PVC/PV Protection:** Финализаторы `kubernetes.io/pvc-protection` и `kubernetes.io/pv-protection` предотвращают удаление ресурсов хранения, пока они связаны с активным подом или друг с другом.

### Роль CSI Sidecar-контейнеров

Проблемы часто кроются в сбоях вспомогательных контейнеров драйвера:

| Компонент | Роль | Признак сбоя |
| :--- | :--- | :--- |
| **`csi-attacher`** | Следит за `VolumeAttachment`, снимает финализатор `external-attacher`. | Под висит в `Terminating`, том не отключается в облаке. |
| **`csi-provisioner`** | Удаляет физические диски в облаке при удалении PV. | PV застрял в `Terminating`, диск продолжает потреблять бюджет. |
| **`csi-resizer`** | Управляет изменением размера томов. | Блокирует завершение, если операция расширения не финализирована. |
| **`csi-snapshotter`** | Управляет снимками томов. | Блокирует удаление тома, если процесс создания снимка «завис». |

### Типы финализаторов и их поведение

| Тип финализатора | Источник | Кто снимает | Типичная задержка |
| :--- | :--- | :--- | :--- |
| `kubernetes.io/pod-protection` | Ядро K8s | kubelet | <1с (если узел здоров) |
| `external-attacher/<driver>` | CSI-драйвер | csi-attacher | 5-60с (зависит от CSI) |
| `kubernetes.io/pvc-protection` | Ядро K8s | kube-controller-manager | <1с (если PVC не используется) |
| `kubernetes.io/pv-protection` | Ядро K8s | kube-controller-manager | <1с (если PV не привязан) |
| `helm.sh/resource-policy` | Helm | helm uninstall | До удаления ресурса |
| Кастомные (оператор) | Оператор | Оператор-контроллер | Зависит от логики оператора |

---

## Практические сценарии

### Быстрый чек-лист диагностики (start here)

```bash
# 1. Определите финализаторы
kubectl get pod <pod-name> -o jsonpath='DeletionTimestamp: {.metadata.deletionTimestamp}{"\n"}Finalizers: {.metadata.finalizers}'

# 2. Проверьте, когда началось завершение
kubectl get pod <pod-name> -o jsonpath='deletionGracePeriodSeconds: {.metadata.deletionGracePeriodSeconds}s'

# 3. Events (быстрый поиск причин)
kubectl describe pod <pod-name> | grep -A 20 Events

# 4. Проверьте CSI-controller (если финализатор external-attacher)
kubectl logs -n kube-system -l app=csi-attacher --tail=50

# 5. Проверьте, есть ли VolumeAttachment
kubectl get volumeattachment | grep $(kubectl get pod <pod-name> -o jsonpath='{.spec.nodeName}')
```

### Сценарий 1: Зависание на отсоединении тома (external-attacher)

**Симптом:** Pod находится в `Terminating`, в метаданных виден финализатор `external-attacher/...`.

**Диагностика:**
1.  Найдите объекты `VolumeAttachment` для этого пода:
    ```bash
    kubectl get volumeattachment | grep $(kubectl get pod <pod-name> -o jsonpath='{.spec.nodeName}')
    ```
2.  Проверьте ошибки в описании объекта:
    ```bash
    kubectl describe volumeattachment <attachment-name>
    ```
    *Ищите ошибки: `FailedDetachVolume`, `RateLimitExceeded`, `InternalError`, `VolumeInUse` (диск захвачен другим процессом).*

3.  Проверьте логи CSI-аттачера:
    ```bash
    kubectl logs -n kube-system -l app=csi-attacher -c csi-attacher --tail=100
    # Ищите: "error", "failed", "timeout"
    ```

**Решение:**
1.  **Удаление VolumeAttachment**: Если вы уверены, что том физически отсоединен:
    ```bash
    kubectl delete volumeattachment <attachment-name> --wait=false
    ```

2.  **Проверка CSI-драйвера**: Если VolumeAttachment повторно создаётся, проблема в CSI-контроллере:
    ```bash
    kubectl get pods -n kube-system -l app=csi-controller
    kubectl logs -n kube-system -l app=csi-controller --tail=100 | grep -i error
    ```

3.  **Проверка лимитов API**: Если ошибка `RateLimitExceeded`, увеличьте `--kube-api-qps` в CSI-драйвере или подождите.

### Сценарий 2: Очистка финализаторов на недоступном узле (K8s 1.24+)

**Симптом:** Узел упал (Hardware failure), поды застряли в `Terminating` с финализатором `kubernetes.io/pod-protection`.

**Решение:**
Используйте механизм `out-of-service`, чтобы контроллеры безопасно сняли финализаторы:
```bash
# Пометить узел как окончательно недоступный
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service=NoExecute:NoExecute
```
После этого системные контроллеры автоматически очистят финализаторы томов и подов.

**Проверка результата:**
```bash
# Дождитесь исчезновения подов с упавшего узла
kubectl get pods -o wide | grep <node-name>

# Проверьте, что поды пересоздались на других узлах
kubectl get pods -o wide | grep <pod-name>

# Удалите taint перед возвращением узла в строй
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service-
```

**Важно:** Этот механизм работает для всех типов workload. Для StatefulSet контроллер ждет полного удаления старого объекта перед созданием нового с тем же индексом.

### Сценарий 3: Зависание PVC/PV из-за связанных ресурсов

**Симптом:** PVC висит в `Terminating` с финализатором `kubernetes.io/pvc-protection`.

**Диагностика:**
Поиск подов (включая Job в других namespace), использующих этот PVC:
```bash
kubectl get pods --all-namespaces -o json | jq -r '.items[] | select(.spec.volumes[]?.persistentVolumeClaim.claimName == "<pvc-name>") | "\(.metadata.namespace)/\(.metadata.name)"'
```

Проверка, используется ли PVC в StatefulSet:
```bash
kubectl get statefulsets --all-namespaces -o json | jq -r '.items[] | select(.spec.volumeClaimTemplates[]?.metadata.name == "<pvc-name>") | "\(.metadata.namespace)/\(.metadata.name)"'
```

**Решение:**
Если ресурс физически не нужен и под-потребитель удален, очистите финализаторы:
```bash
kubectl patch pvc <pvc-name> -p '{"metadata":{"finalizers":null}}' --type=merge
```

**Важно:** Удаление PVC с активными подами приведёт к потере данных. Убедитесь, что ни один под не монтирует этот PVC.

### Сценарий 4: Финализаторы и блокировка ResourceQuota

**Симптом:** Namespace заблокирован, новые поды не создаются. В `kubectl describe resourcequota` видно, что `used` ресурсов исчерпано, но подов в `Running` нет.

**Диагностика:**
```bash
# Проверка ResourceQuota
kubectl get resourcequota -n <namespace> -o yaml
# Ищите: "pods" в "used" vs "hard"

# Поиск подов в Terminating с финализаторами
kubectl get pods -n <namespace> -o json | jq -r '.items[] | select(.metadata.deletionTimestamp != null and (.metadata.finalizers | length) > 0) | "\(.metadata.name): \(.metadata.finalizers)"'
```

**Причина:** Pod в `Terminating` **всё ещё считается** в ResourceQuota. Если контроллер не снимает финализатор, под не исчезает, и квота не освобождается.

**Решение:**
1. Найдите и устраните причину зависания финализатора (CSI, оператор).
2. Если это невозможно — снимите финализатор вручную:
   ```bash
   kubectl patch pod <pod-name> -n <namespace> -p '{"metadata":{"finalizers":null}}' --type=merge
   ```

### Сценарий 5: Helm-ресурсы с политиками удаления

**Симптом:** При `helm uninstall` ресурсы не удаляются, висят в `Terminating` с финализатором.

**Диагностика:**
```bash
# Проверка annotations Helm
kubectl get <resource-type> <name> -o jsonpath='{.metadata.annotations}'
# Ищите: "helm.sh/resource-policy: keep" или "helm.sh/hook-delete-policy"

# Поиск всех ресурсов с Helm-политиками
kubectl get all -n <namespace> -o json | jq -r '.items[] | select(.metadata.annotations["helm.sh/resource-policy"] != null) | "\(.kind)/\(.metadata.name): \(.metadata.annotations["helm.sh/resource-policy"])"'
```

**Решение:**
- Если политика `keep`: ресурс intentionally сохраняется. Удалите вручную при необходимости.
- Если политика `hook`: проверьте, что хук выполнился. Удалите финализатор вручную:
  ```bash
  kubectl patch <resource-type> <name> -p '{"metadata":{"finalizers":null}}' --type=merge
  ```

### Сценарий 6: CRD и кастомные финализаторы операторов

**Симптом:** Custom Resource (CR) висит в `Terminating` с кастомным финализатором (например, `dex.connector.coreos.com/cleanup`).

**Диагностика:**
```bash
# Проверка финализаторов CR
kubectl get <crd-type> <cr-name> -o jsonpath='{.metadata.finalizers}'

# Проверка, работает ли оператор
kubectl get deployment -n <operator-namespace> -o wide
kubectl logs -n <operator-namespace> -l app=<operator-name> --tail=100 | grep -i error

# Проверка CRD-контроллера
kubectl get crd <crd-name> -o jsonpath='{.spec.scope}'
```

**Решение:**
1. Если оператор работает, но не снимает финализатор — проверьте его логи на ошибки.
2. Если оператор удалён/не работает — снимите финализатор вручную:
   ```bash
   kubectl patch <crd-type> <cr-name> -p '{"metadata":{"finalizers":null}}' --type=merge
   ```
3. При удалении CRD все связанные CR также удаляются. Если CRD застряёт из-за финализаторов на CR, сначала очистите CR.

**Важно:** Удаление CR с финализаторами без очистки ресурсов может привести к утечке ресурсов в облаке (тома, балансировщики, DNS-записи).

### Сценарий 7: Сторонние webhook и агенты

**Симптом:** Pod или Secret висит в `Terminating` с финализатором от стороннего компонента (vault-webhook, cert-manager, external-secrets).

**Диагностика:**
```bash
# Проверка финализатора
kubectl get <resource-type> <name> -o jsonpath='{.metadata.finalizers}'
# Пример: ["vault.security.banzaicloud.com/vault-secrets-webhook"]

# Проверка webhook deployment
kubectl get pods -n <webhook-namespace> -l app=<webhook-name>
kubectl logs -n <webhook-namespace> -l app=<webhook-name> --tail=100 | grep -i error
```

**Решение:**
1. Убедитесь, что webhook/агент работает и доступен.
2. Проверьте его логи на ошибки API или тайм-ауты.
3. Если webhook не работает — снимите финализатор вручную:
   ```bash
   kubectl patch <resource-type> <name> -p '{"metadata":{"finalizers":null}}' --type=merge
   ```

### Сценарий 8: Орфанные PV при удалении узла

**Симптом:** Node удалён, но PersistentVolume остаётся привязанным к нему. Новый под не может примонтировать том (ошибка `Multi-Attach`).

**Диагностика:**
```bash
# Проверка VolumeAttachment для упавшего узла
kubectl get volumeattachment | grep <node-name>

# Проверка статуса PV
kubectl get pv <pv-name> -o jsonpath='{.spec.phase} {"\n"}{.spec.claimRef.name}'

# Проверка финализаторов PV
kubectl get pv <pv-name> -o jsonpath='{.metadata.finalizers}'
```

**Решение:**
1. Пометьте узел taint `out-of-service` (если не сделано):
   ```bash
   kubectl taint nodes <node-name> node.kubernetes.io/out-of-service=NoExecute:NoExecute
   ```
2. Дождитесь автоматического отсоединения тома CSI-контроллером.
3. Если не помогает — удалите VolumeAttachment:
   ```bash
   kubectl delete volumeattachment <attachment-name>
   ```
4. **Крайняя мера:** Если том всё ещё примонтирован к мёртвому узлу, это может потребовать ручного вмешательства в консоль СХД (отсоединение диска).

---

## Дополнительная информация

### Риски и "Split Brain"

**ВНИМАНИЕ:** Ручное снятие финализаторов — крайняя мера.
1.  **Повреждение ФС**: Если контроллер не успел сделать `detach`, а вы удалили финализатор и запустили под на другом узле, облачный провайдер может отдать диск новому узлу, пока старый еще держит его. Это приведет к **необратимой коррупции данных**.
2.  **Утечка ресурсов**: Облачные диски могут остаться «висеть» в вашем аккаунте, так как Kubernetes «забыл» о них.
3.  **Split-brain для StatefulSet**: Принудительное удаление пода StatefulSet на недоступном узле может привести к одновременному доступу к томам с двух узлов.

**Чек-лист перед снятием финализаторов:**
- [ ] Узел физически недоступен или процессы гарантированно не работают
- [ ] Тома физически отмонтированы (проверьте `VolumeAttachment`)
- [ ] Нет риска одновременного доступа к томам с двух узлов
- [ ] Вы понимаете, какие ресурсы могут остаться «осиротевшими»

### Взаимодействие с reclaimPolicy

Если `reclaimPolicy` в `StorageClass` установлена в `Delete`:
1. Снимается финализатор `pvc-protection`.
2. Объект PV переходит в `Terminating`.
3. `csi-provisioner` пытается удалить диск в облаке.
4. Только после успеха снимается финализатор с PV.

Если `csi-provisioner` не может удалить диск (ошибка API, тайм-аут), финализатор остаётся, и диск продолжает потреблять бюджет.

### Мониторинг зависших финализаторов

```bash
# Все поды с финализаторами в Terminating
kubectl get pods -A -o json | jq '.items[] | select(.metadata.deletionTimestamp != null and (.metadata.finalizers | length) > 0) | {name: .metadata.name, namespace: .metadata.namespace, finalizers: .metadata.finalizers, deletionTimestamp: .metadata.deletionTimestamp}'

# Все PV с финализаторами
kubectl get pv -o json | jq '.items[] | select(.metadata.finalizers != null) | {name: .metadata.name, finalizers: .metadata.finalizers, phase: .status.phase}'

# Все PVC с финализаторами
kubectl get pvc -A -o json | jq '.items[] | select(.metadata.finalizers != null) | {name: .metadata.name, namespace: .metadata.namespace, finalizers: .metadata.finalizers}'

# Все CR с финализаторами
kubectl get <crd-type> -A -o json | jq '.items[] | select(.metadata.finalizers != null) | {name: .metadata.name, namespace: .metadata.namespace, finalizers: .metadata.finalizers}'
```

### PromQL для мониторинга

```promql
# Поды в Terminating дольше 5 минут (зависшие финализаторы)
(time() - kube_pod_created) * on(pod, namespace) group_left() (kube_pod_status_phase{phase="Running"} == 0) > 300

# Количество подов с финализаторами (требует кастомного метрика или scraping из kubectl)
```

---

## Связанные команды kubectl

| Команда | Назначение |
| :--- | :--- |
| `kubectl get pod <name> -o jsonpath='{.metadata.finalizers}'` | Просмотр финализаторов пода |
| `kubectl get pod <name> -o jsonpath='{.metadata.deletionTimestamp}'` | Проверка, начато ли удаление |
| `kubectl patch pod <name> -p '{"metadata":{"finalizers":null}}'` | Снятие финализаторов с пода |
| `kubectl patch pvc <name> -p '{"metadata":{"finalizers":null}}'` | Снятие финализаторов с PVC |
| `kubectl patch pv <name> -p '{"metadata":{"finalizers":null}}'` | Снятие финализаторов с PV |
| `kubectl patch <crd-type> <name> -p '{"metadata":{"finalizers":null}}'` | Снятие финализаторов с CR |
| `kubectl delete volumeattachment <name>` | Удаление привязки тома |
| `kubectl taint nodes <name> node.kubernetes.io/out-of-service=NoExecute:NoExecute` | Пометка узла для out-of-service |
| `kubectl get volumeattachment | grep <node-name>` | Проверка привязки томов к узлу |
| `kubectl logs -n kube-system -l app=csi-attacher` | Логи CSI-аттачера |
| `kubectl logs -n kube-system -l app=csi-controller` | Логи CSI-контроллера |
| `kubectl get resourcequota -n <ns>` | Проверка квот (поды в Terminating считаются) |

---

## Edge Cases

**PVC с `reclaimPolicy: Retain` и упавший узел:**
```bash
# PV остаётся в Bound к "мёртвому" PVC
# Новый под не может примонтировать том
# Решение: очистите VolumeAttachment и pomett узел out-of-service
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service=NoExecute:NoExecute
# Подождите CSI-контроллер отсоединит том
kubectl get volumeattachment | grep <node-name>
```

**DaemonSet с финализаторами:**
```bash
# DaemonSet поды не используют PDB
# При drain узла поды DaemonSet удаляются принудительно
# Если DaemonSet имеет финализатор — поды застрянут
kubectl get pods -n kube-system -l name=<daemonset-name> -o jsonpath='{.items[*].metadata.finalizers}'
```

**Namespace с активным ResourceQuota и Terminating-подами:**
```bash
# Pod в Terminating всё ещё считается в ResourceQuota
# Это блокирует создание новых подов
# Проверка:
kubectl get resourcequota -n <namespace> -o jsonpath='{.items[*].status}'
# Ищите: "pods" в "used" vs "hard"
```

**CRD-контроллер не работает:**
```bash
# Если оператор-контроллер удалён/не работает, финализаторы на CR не будут сняты
# Кластерные CRD: проверьте, есть ли другой экземпляр контроллера
# Namespaced CRD: проверьте, что namespace оператора доступен
kubectl get deployment -A | grep <operator-name>
```

---

**См. также:**
- [Диагностика Pod Terminating](./diagnostics.md) — пошаговый план поиска причин.
- [Ошибки размонтирования томов](./volume_unmount_issues.md) — проблемы уровня ОС и `mount`.
- [Определения Pod Terminating](./definitions.md) — базовые механизмы.
- [Graceful Shutdown](./graceful_shutdown.md) — настройки завершения.
- [Недоступность узла](./node_unavailable_issues.md) — действия при отказе инфраструктуры.
- [Блокировка через PDB](./pdb_blocking.md) — разрешение блокировок при drain.
