# Pod Terminating: PDB блокирует удаление

## 5. PodDisruptionBudget блокирует удаление

**Сообщение:**

```
Cannot evict pod as it would violate the pod's disruption budget.
```

**Причина:** PDB не позволяет удалить под, так как это нарушит `minAvailable`.

**Диагностика:**

```bash
kubectl get pdb
kubectl describe pdb <pdb-name>
```

**Решение:**

### Временное удаление PDB (не рекомендуется для production)

```bash
kubectl delete pdb <pdb-name>
```

### Увеличение maxUnavailable

```bash
kubectl patch pdb <pdb-name> -p '{"spec":{"maxUnavailable":2}}'
```
