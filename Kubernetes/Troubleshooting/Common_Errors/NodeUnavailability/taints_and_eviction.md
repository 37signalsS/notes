# Node Unavailability: Taints and Eviction

> **Важно**: Общие концепции и описание механизмов Taints и Tolerations доступны в основном разделе планирования:
> **[Taints и Tolerations: Управление размещением подов](../../../Scheduling/taints_and_tolerations.md)**

Данный документ фокусируется на специфических сценариях выселения подов при недоступности узлов и методах их решения.

## Основные концепции (кратко)

При недоступности узла (`Ready=Unknown` или `Ready=False`) Kubernetes автоматически добавляет taints:
* `node.kubernetes.io/unreachable:NoExecute`
* `node.kubernetes.io/not-ready:NoExecute`

Поды без соответствующих tolerations выселяются через `tolerationSeconds` (по умолчанию 300с). Подробный процесс описан в **[основном документе](../../../Scheduling/taints_and_tolerations.md#процесс-выселения-eviction-timeline)**.

---

## Практические сценарии диагностики

### Сценарий 1: Диагностика eviction при недоступности узла

**Симптомы**: Поды на узле удалены через ~5 минут после потери связи.

**Диагностика**:
```bash
# Проверка taints узла
kubectl describe node <node-name> | grep -A 5 "Taints:"

# События выселения (eviction)
kubectl get events --field-selector reason=TaintManagerEviction --sort-by='.lastTimestamp'
```

### Сценарий 2: PodDisruptionBudget (PDB) блокирует выселение

**Симптомы**: Узел недоступен, но поды не выселяются, так как PDB не позволяет удалить достаточно реплик.

**Диагностика**:
```bash
# Проверка разрешенных прерываний
kubectl get pdb <pdb-name> -o jsonpath='{.status.disruptionsAllowed}'
```

**Решение**: Временно скорректировать PDB или дождаться восстановления узла.

### Сценарий 3: Принудительное удаление «зависших» подов

Если узел окончательно вышел из строя, а поды остаются в статусе `Terminating`:

```bash
# Принудительное удаление из API
kubectl delete pod <pod-name> --force --grace-period=0
```

> **Осторожно**: Принудительное удаление может привести к конфликтам, если контейнер на самом деле всё еще работает на узле (проблема split-brain для StatefulSet).

---

## Дополнительная информация

* [Диагностика узлов](./diagnostics.md)
* [Выселение при нехватке ресурсов](./resource_pressure.md)
* [Обслуживание узлов (Cordon/Drain)](./maintenance.md)
