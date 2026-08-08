# Расширенные сценарии работы с PV и PVC

## Определения

В данном файле рассматриваются продвинутые механизмы управления жизненным циклом, производительностью и поведением постоянных томов в Kubernetes.

**Смежные темы:**
- [Базовые концепции PV и PVC](./pv_and_pvc.md) — основы, режимы доступа, политики возврата.
- [StorageClass](./storageclass.md) — параметры динамического провижининга и `VolumeAttributesClass`.
- [Volume Claims в StatefulSet](../Base/StatefulSet/statefulset_core_concepts.md#persistentvolumeclaim-pvc) — специфика работы с шаблонами.

---

## Основные концепции

### Алгоритм связывания PV и PVC (Binding Loop)

Kubernetes связывает PVC с PV по строгому алгоритму. Процесс выполняется контроллером `pv-controller`:

1. **StorageClassName**: PV с совпадающим классом. Если в PVC класс не указан, ищется PV без класса (или используется Default StorageClass).
2. **AccessModes**: PV должен поддерживать все режимы доступа, указанные в PVC.
3. **VolumeMode**: Совпадение `Filesystem` или `Block`.
4. **Размер**: PV должен иметь емкость не меньше запрошенной в PVC.
5. **Selector**: Если в PVC указан `selector`, PV должен иметь соответствующие метки.
6. **Best Fit**: Из всех подходящих PV выбирается тот, чей размер наиболее близок к запрошенному (минимизация потерь пространства).

#### Нюансы Best Fit
- Если PVC запрашивает 5 ГБ, а доступен только PV на 100 ГБ, PVC будет привязан к нему. Оставшиеся 95 ГБ будут фактически недоступны.
- PVC остается в статусе `Pending`, пока не появится PV, удовлетворяющий **всем** критериям.

### Режимы объема (Volume Mode)

Определяют, как том представляется внутри контейнера:

| Режим | Описание | Применение |
|---|---|---|
| **`Filesystem`** (Default) | Том монтируется как директория. K8s сам создает ФС (ext4/xfs), если её нет. | Обычные приложения, логи, конфигурации. |
| **`Block`** | Том пробрасывается как "сырое" блочное устройство (`/dev/sdb`). ФС отсутствует. | Высоконагруженные БД (Oracle, SAP), виртуализация (KubeVirt), Ceph OSD. |

### Эксклюзивный доступ (ReadWriteOncePod)

Режим доступа (GA в 1.29), обеспечивающий строгую изоляцию на уровне пода, а не узла:
- **RWO (ReadWriteOnce)**: Несколько подов на **одном узле** могут одновременно использовать том.
- **RWOP (ReadWriteOncePod)**: Только **один под во всем кластере** может монтировать том. Это предотвращает порчу данных при "split-brain" сценариях, когда старый под еще не завершился, а новый уже пытается писать в тот же диск.

### Механизмы защиты (Finalizers)

Kubernetes защищает данные от случайного удаления через финализаторы:
- `kubernetes.io/pvc-protection`: Блокирует удаление PVC, пока он примонтирован к активному поду.
- `kubernetes.io/pv-protection`: Блокирует удаление PV, пока он связан с любым PVC.
- **Политика возврата (Reclaim Policy)**: Начиная с K8s 1.33 GA, политика (Delete/Retain) соблюдается всегда, независимо от порядка удаления объектов (PV или PVC).

---

## Практические сценарии

### Динамическое расширение тома (Volume Expansion)

Позволяет увеличить размер диска без удаления PVC и потери данных.

**Алгоритм и особенности:**
1. Отредактируйте PVC: `spec.resources.requests.storage`.
2. **Восстановление после сбоя (K8s 1.34 GA):** Если расширение невозможно (например, лимит квоты в облаке), можно уменьшить значение в PVC до доступного максимума без удаления тома.
3. **Online vs Offline:** Большинство современных CSI-драйверов поддерживают Online-расширение (без остановки пода).

### Generic Ephemeral Volumes (Эфемерные PVC)

Позволяют использовать все возможности динамического провижининга (SSD, снапшоты) для временных данных с жизненным циклом пода.

```yaml
kind: Pod
spec:
  volumes:
    - name: scratch-space
      ephemeral:
        volumeClaimTemplate:
          spec:
            storageClassName: "fast-ssd"
            accessModes: [ "ReadWriteOnce" ]
            resources:
              requests:
                storage: 20Gi
```
*PVC создается вместе с подом и автоматически удаляется при его завершении.*

### Использование источников данных (Volume Data Sources)

#### 1. Клонирование тома (Volume Cloning)
Создание тома на основе существующего PVC в том же Namespace.
```yaml
spec:
  dataSource:
    name: source-pvc
    kind: PersistentVolumeClaim
```

#### 2. Восстановление из снимка (Volume Snapshot)
```yaml
spec:
  dataSource:
    name: my-snapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

#### 3. Групповые снимки (Volume Group Snapshots)
В K8s 1.34 (Beta) доступен API `VolumeGroupSnapshot` для создания согласованных снимков нескольких томов одновременно (например, для базы данных, у которой данные и логи на разных дисках).

### Привязка к конкретному PV (ClaimRef)

Администратор может зарезервировать PV для конкретного PVC, указав `claimRef` в PV:
```yaml
# В PersistentVolume
spec:
  claimRef:
    name: specific-pvc
    namespace: prod
```

### Передача владения PV (Ownership Transfer)

Для перемещения PV между Namespace (миграция):
1. Измените `reclaimPolicy` у PV на `Retain`.
2. Удалите старый PVC. PV перейдет в статус `Released`.
3. Отредактируйте PV, удалив `.spec.claimRef` (чтобы сделать его `Available`).
4. Создайте новый PVC в целевом Namespace, указав `volumeName: <имя-pv>`.

---

## Диагностика и Troubleshooting

| Состояние PVC | Вероятная причина | Действие |
|---|---|---|
| `Pending` (no PV) | Нет подходящих PV и не работает SC. | `kubectl describe pvc`, проверьте наличие `StorageClass`. |
| `Pending` (WaitForFirstConsumer) | Под не назначен на узел. | Проверьте статус пода. Возможно, он не может быть запланирован из-за ресурсов или Taints. |
| `Terminating` | Используется подом или активен финализатор. | Проверьте `kubectl get pod --all-namespaces` на предмет использования PVC. |
| `WaitingForCondition` (Resize) | Расширение требует перезагрузки пода или ограничено драйвером. | Перезапустите под. Проверьте события: `kubectl describe pvc`. |

---

## Дополнительная информация

- [CSI Advanced — снимки, клонирование, топология](./CSI/csi_advanced.md)
- [StorageClass и управление производительностью](./storageclass.md)
- [Официальная документация: Generic Ephemeral Volumes](https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/#generic-ephemeral-volumes)
- [Официальная документация: Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
