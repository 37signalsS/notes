# Pod Evicted: PDB и Taint-based Eviction

## 4. Eviction из-за `PodDisruptionBudget`

**Сценарий:** PDB не позволяет выселить достаточно подов для обслуживания.

**Диагностика:**

```bash
# Проверка PDB
kubectl get pdb
kubectl describe pdb <pdb-name>

# Проверка disrupted подов
kubectl get events --field-selector reason=DisruptionBudgetExceeded
```

**Решение:**

- Пересмотреть PDB (увеличить `maxUnavailable`)
- Добавить узлы для размещения подов
- Временно удалить PDB (не рекомендуется для production)

## 5. Taint-based Eviction (`NoExecute`)

**Сообщение:**

```
Marking for deletion Pod <pod-name>
```

**Причина:** Узел получил taint с эффектом `NoExecute`, под не имеет соответствующего `toleration`.

**Диагностика:**

```bash
# Проверка taints узла
kubectl get node <node-name> -o jsonpath='{.spec.taints}'

# Проверка tolerations пода
kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}'
```

**Решение:**

```yaml
# Добавить toleration в под
spec:
  tolerations:
  - key: "node.kubernetes.io/unreachable"
    operator: "Exists"
    effect: "NoExecute"
    tolerationSeconds: 300
```
