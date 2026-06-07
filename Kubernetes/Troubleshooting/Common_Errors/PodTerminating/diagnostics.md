# Pod Terminating — диагностика

## Определения

**Диагностическое дерево Pod Terminating** — логическая последовательность проверок для выявления первопричины зависания Pod в состоянии `Terminating`. Включает анализ томов (volumes), финализаторов (finalizers), состояния узлов (nodes) и бюджетов прерываний (PDB).

**UID (Unique Identifier)** — уникальный идентификатор объекта Pod, необходимый для точного поиска точек монтирования на файловой системе узла и связи с объектами `VolumeAttachment`.

**Метка удаления (Deletion Timestamp)** — временной маркер в метаданных объекта. В диагностике критично сравнение этой метки с текущим временем: если разница превышает `terminationGracePeriodSeconds`, это подтверждает наличие блокировки завершения.

---

## Базовые концепции

### Алгоритм диагностики

Процесс анализа строится от общего состояния к специфичным компонентам:

1. **Общий аудит** → анализ `kubectl describe` (события, финализаторы, условия).
2. **Классификация блокировки** → отнесение проблемы к одной из категорий: тома, финализаторы, узел или PDB.
3. **Глубокий анализ** → использование специализированных инструментов для подтвержденной категории.
4. **Устранение** → применение инструкций из профильных разделов.

### Ключевые маркеры в выводе describe

```yaml
Status:             Terminating
Deletion Timestamp:  2026-03-05T10:00:00Z    # Сравнить с текущим временем
Finalizers:         [kubernetes.io/pod-protection external-attacher/csi-driver] # Причина блокировки
```

### Инструменты анализа

| Инструмент | Сфера применения | Искомые данные |
| :--- | :--- | :--- |
| `kubectl describe pod` | Общий аудит и события (Events) | Ошибки монтирования, таймауты узла, финализаторы. |
| `kubectl get pod -o json` | Полная спецификация объекта | `deletionTimestamp`, полные списки условий и финализаторов. |
| `findmnt` / `lsof` | Локальная диагностика на узле | Процессы, блокирующие размонтирование томов. |
| `kubectl get volumeattachment` | Проверка связей томов | Зависшие объекты в CSI (Container Storage Interface). |

---

## Практические сценарии

### Пошаговый алгоритм проверки

#### Этап 1: Первичный сбор данных

```bash
# Проверка распределения по узлам
kubectl get pod <pod-name> -o wide

# Анализ событий и конфигурации
kubectl describe pod <pod-name>
```

**Анализ результатов:**

- `DeletionTimestamp` значительно старше ожидаемого времени завершения → переход к классификации.
- В списке `Finalizers` присутствуют записи → блокировка логикой контроллеров.
- В `Events` видны ошибки CSI или тайм-ауты узла → переход к этапу 2.

#### Этап 2: Классификация причины блокировки

| Признак | Категория | Ссылка на решение |
| :--- | :--- | :--- |
| Финализатор: `external-attacher/...` | Проблемы томов CSI | [Ошибки размонтирования томов](./volume_unmount_issues.md) |
| Финализатор: `kubernetes.io/pvc-protection` | Защита ресурсов | [Проблемы финализаторов](./finalizer_issues.md) |
| Статус узла: `NotReady` или `Unknown` | Недоступность узла | [Недоступность узла](./node_unavailable_issues.md) |
| Событие: `violate disruption budget` | Блокировка через PDB | [Блокировка PDB](./pdb_blocking.md) |

#### Этап 3: Диагностика подсистемы хранения

```bash
# Список описанных томов
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes}'

# Получение UID для поиска на узле
kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}'

# Проверка точек монтирования на узле (через SSH)
findmnt | grep <pod-uid>
lsof +D /var/lib/kubelet/pods/<pod-uid>/volumes
```

Детальное руководство: [Ошибки размонтирования томов](./volume_unmount_issues.md).

#### Этап 4: Анализ финализаторов и CSI-объектов

```bash
# Проверка связи тома с узлом
kubectl get volumeattachment | grep <pod-uid>

# Статус контроллеров CSI
kubectl get pods -n kube-system -l app=csi-driver
```

Детальное руководство: [Проблемы финализаторов](./finalizer_issues.md).

#### Этап 5: Проверка состояния инфраструктуры

```bash
# Общий статус узла
kubectl get node <node-name>

# События, относящиеся к узлу
kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node-name>
```

Детальное руководство: [Недоступность узла](./node_unavailable_issues.md).

### Сценарий автоматизированной диагностики

Скрипт для экспресс-анализа зависшего Pod:

```bash
#!/bin/bash
POD=$1
NS=${2:-default}

echo "=== Статус и локация ==="
kubectl get pod $POD -n $NS -o wide

echo -e "\n=== Активные финализаторы ==="
kubectl get pod $POD -n $NS -o jsonpath='{.metadata.finalizers}'
echo

echo -e "\n=== Конфигурация томов ==="
kubectl get pod $POD -n $NS -o jsonpath='{.spec.volumes}'
echo

echo -e "\n=== Ключевые метрики состояния ==="
kubectl describe pod $POD -n $NS | grep -A 10 "Status:\|Finalizers:\|Conditions:"

echo -e "\n=== История событий ==="
kubectl get events -n $NS --field-selector involvedObject.name=$POD --sort-by='.lastTimestamp'
```

---

## Дополнительная информация

**См. также:**

- [Определения Pod Terminating](./definitions.md) — базовые термины и системные механизмы.
- [Ошибки размонтирования томов](./volume_unmount_issues.md) — детальный анализ проблем хранилищ.
- [Проблемы финализаторов](./finalizer_issues.md) — ручная очистка и CSI-специфика.
- [Недоступность узла](./node_unavailable_issues.md) — действия при отказе инфраструктуры.
- [Блокировка PDB](./pdb_blocking.md) — анализ бюджетов прерываний (Pod Disruption Budget).
- [Graceful Shutdown (корректное завершение)](./graceful_shutdown.md) — настройки периодов завершения.
- [Обзор Troubleshooting](../../troubleshooting_overview.md) — общая классификация ошибок Kubernetes.
