# Pod Evicted: Обслуживание узлов

## 3. Eviction при обслуживании узла (`drain`)

**Сообщение:**

```
pod evicted from node <node-name> by user request
```

**Причина:** Администратор выполнил `kubectl drain` для обслуживания узла.

**Решение:**

### Стандартная процедура обслуживания

```bash
# 1. Cordon (запрет новых подов)
kubectl cordon <node-name>

# 2. Drain (выселение подов)
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# 3. Обслуживание узла
# ... reboot, update, etc.

# 4. Uncordon (возврат в работу)
kubectl uncordon <node-name>
```
