# Pod в состоянии `CrashLoopBackOff`: Диагностика

## Пошаговый чек-лист

### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в выводе:**

```
State:          Waiting
  Reason:       CrashLoopBackOff
Last State:     Terminated
  Reason:       Error (или OOMKilled)
  Exit Code:    <код>
Restart Count:  <число>
```

---

### Шаг 2: Просмотр логов

```bash
# Логи предыдущего запуска (критично!)
kubectl logs <pod-name> --previous

# Логи текущего запуска (если контейнер еще жив)
kubectl logs <pod-name>

# Для pod с несколькими контейнерами
kubectl logs <pod-name> -c <container-name> --previous

# Стриминг в реальном времени
kubectl logs <pod-name> -f --previous
```

---

### Шаг 3: Проверка конфигурации

```bash
# Проверка ConfigMap
kubectl get configmap <configmap-name> -o yaml

# Проверка Secret
kubectl get secret <secret-name> -o yaml

# Проверка переменных окружения в поде
kubectl exec <pod-name> -- env 2>/dev/null || kubectl run debug --image=busybox --rm -it --restart=Never -- env
```

---

### Шаг 4: Проверка зависимостей

```bash
# Проверка доступности сервисов
kubectl get svc
kubectl get endpoints <service-name>

# Проверка DNS
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup <service-name>.<namespace>.svc.cluster.local

# Проверка Network Policies
kubectl get networkpolicy -n <namespace>
```

---

### Шаг 5: Проверка RBAC (если приложение обращается к API K8s)

```bash
# Определение ServiceAccount пода
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'

# Проверка прав
kubectl auth can-i get pods --as=system:serviceaccount:<namespace>:<sa-name>
kubectl auth can-i list secrets --as=system:serviceaccount:<namespace>:<sa-name>
```

---

## Ссылки

- **[Распространенные случаи и решения](./common_cases_and_solutions.md)** — решения для типичных проблем
- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
