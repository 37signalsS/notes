# Kubespray: Политики безопасности и доступности

## Определения

**Pod Disruption Budget (PDB)** — объект Kubernetes, который ограничивает количество одновременных осознанных нарушений (disruptions) для группы подов. PDB гарантирует, что во время обслуживания (обновление узла, масштабирование вниз) всегда будет работать минимальное количество подов.

**Pod Security Standards (PSS)** — набор профилей безопасности, определяющих уровень изоляции подов. Заменили устаревшие Pod Security Policy начиная с Kubernetes 1.25.

**Pod Security Admission (PSA)** — механизм admission-контроля, который применяет Pod Security Standards к неймспейсам через лейблы.

**Disruption Budget** — политика, определяющая, сколько подов может быть одновременно недоступно при осознанных операциях (обслуживание, обновления).

**Волатильные поды (Ephemeral Pods)** — поды, которые могут быть удалены без нарушения PDB (например, поды с `restartPolicy: Never`).

---

## Основные концепции

### Pod Disruption Budget (PDB)

PDB защищает приложения от потери доступности во время планового обслуживания. Kubernetes-контроллеры (Deployment, StatefulSet) и инструменты обслуживания (kubectl drain, Cluster Autoscaler) проверяют PDB перед удалением подов.

**Типы ограничений:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **minAvailable** | Минимальное количество доступных подов | `minAvailable: 3` — всегда работают минимум 3 пода |
| **maxUnavailable** | Максимальное количество недоступных подов | `maxUnavailable: 1` — не более 1 пода недоступен |

**Важные особенности:**
- PDB применяется только к **осознанным** нарушениям (planned disruptions).
- PDB **не защищает** от аварийных сбоев (node failure, OOMKill).
- PDB работает с **самоуправляющимися подами** (Deployment, StatefulSet, DaemonSet).

### Pod Security Standards (PSS)

PSS определяют три профиля безопасности:

| Профиль | Описание | Примеры ограничений |
| :--- | :--- | :--- |
| **privileged** | Без ограничений (по умолчанию) | Запуск от root, привилегированные контейнеры, hostPath |
| **baseline** | Минимальные ограничения | Запрет privileged, hostNetwork, hostPID, hostIPC |
| **restricted** | Строгие ограничения | Запрет hostPath, capabilities, только non-root, read-only rootfs |

**Настройка PSA через лейблы:**

```bash
# Применение baseline для неймспейса
kubectl label ns production \
  pod-security.kubernetes.io/enforce=baseline \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/audit=restricted

# Проверка лейблов
kubectl get ns production -o json | jq '.metadata.labels | with_entries(select(.key | startswith("pod-security")))'
```

**Режимы PSA:**

| Режим | Действие | Рекомендация |
| :--- | :--- | :--- |
| **enforce** | Блокирует создание подов, нарушающих политику | Используйте после тестирования |
| **warn** | Выдает предупреждение пользователю | Включите для мониторинга |
| **audit** | Записывает нарушение в лог аудита | Включите для аудита |

---

## Практические сценарии

### 1. Создание Pod Disruption Budget

**PDB с minAvailable (рекомендуется):**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: backend-pdb
  namespace: production
spec:
  minAvailable: 3
  selector:
    matchLabels:
      app: backend
```

**PDB с maxUnavailable:**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: frontend-pdb
  namespace: production
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: frontend
```

**PDB для StatefulSet:**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: postgres-pdb
  namespace: production
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: postgres
      statefulset.kubernetes.io/pod-name: postgres-0
```

### 2. Проверка PDB

```bash
# Проверка PDB в неймспейсе
kubectl get pdb -n production
# → NAME          MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → backend-pdb   3               <none>            0                     5m
# → frontend-pdb  <none>          1                 0                     5m

# Проверка деталей PDB
kubectl describe pdb backend-pdb -n production
# → Name:           backend-pdb
# → Namespace:      production
# → Selector:       app=backend
# → Min Available:  3
# → Pod Status:
# →   Served:       5
# →   Healthy:      5
# → Disruptions Allowed: 0
```

### 3. Тестирование PDB

```bash
# Попытка удалить под с учетом PDB
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --grace-period=60

# Если PDB не позволяет удалить под, drain остановится с ошибкой:
# error: cannot delete pods that violate pod disruption budget
```

### 4. Настройка Pod Security Standards для неймспейсов

**Базовая настройка:**

```bash
# Применение baseline для неймспейса production
kubectl label ns production \
  pod-security.kubernetes.io/enforce=baseline \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/audit=restricted

# Применение restricted для неймспейса security-sensitive
kubectl label ns secure-apps \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/audit=restricted
```

**Проверка:**

```bash
# Проверка лейблов
kubectl get ns -o custom-columns=NAME:.metadata.name,ENFORCE:.metadata.labels.pod-security\.kubernetes\.io/enforce,WARN:.metadata.labels.pod-security\.kubernetes\.io/warn
# → NAME            ENFORCE     WARN
# → production      baseline    restricted
# → secure-apps     restricted  restricted

# Попытка создать привилегированный под в restricted-неймспейсе
kubectl run test --image=nginx --restart=Never -n secure-apps --overrides='{"spec":{"securityContext":{"privileged":true}}}'
# → Error from server (Forbidden): pods "test" is forbidden: violates PodSecurity "restricted:latest"
```

### 5. Интеграция с kubectl drain

При обслуживании узлов kubectl drain автоматически проверяет PDB:

```bash
# Безопасное обслуживание узла
kubectl cordon <node>  # Пометить узел как непригодный для планирования
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --grace-period=300

# Если PDB не позволяет удалить под, drain остановится
# Решение: увеличьте время ожидания или измените PDB
```

### 6. Практические примеры PDB

**Для веб-приложения с 5 репликами:**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-app-pdb
  namespace: production
spec:
  maxUnavailable: 2  # Не более 2 подов недоступны одновременно
  selector:
    matchLabels:
      app: web-app
```

**Для критичной службы с 3 репликами:**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: critical-service-pdb
  namespace: production
spec:
  minAvailable: 2  # Всегда работают минимум 2 пода
  selector:
    matchLabels:
      app: critical-service
```

**Для DaemonSet ( kube-system):**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: monitoring-pdb
  namespace: kube-system
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: monitoring
```

### 7. Проверка соответствия PSS

**Проверка пода на соответствие restricted:**

```bash
# Запуск пода с restricted-профилем
kubectl run restricted-test --image=nginx --restart=Never \
  --overrides='{
    "spec": {
      "securityContext": {
        "runAsNonRoot": true,
        "runAsUser": 1000,
        "fsGroup": 2000
      },
      "containers": [{
        "name": "nginx",
        "image": "nginx",
        "securityContext": {
          "allowPrivilegeEscalation": false,
          "readOnlyRootFilesystem": true,
          "capabilities": {
            "drop": ["ALL"]
          }
        }
      }]
    }
  }'
```

**Проверка с помощью kubectl:**

```bash
# Проверка security context пода
kubectl get pod restricted-test -o jsonpath='{.spec.securityContext}'

# Проверка容器 security context
kubectl get pod restricted-test -o jsonpath='{.spec.containers[*].securityContext}'
```

---

## Дополнительная информация

### Частые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| PDB не защищает от аварийных сбоев | PDB работает только с осознанными нарушениями | Используйтеmultiple replicas и anti-affinity |
| drain останавливается с ошибкой | PDB не позволяет удалить под | Увеличьте `--grace-period` или измените PDB |
| Pod блокируется PSA | Pod нарушает Pod Security Standards | Измените конфигурацию пода или ослабьте PSA |
| PSA warn не показывается | PSA не настроен для неймспейса | Добавьте лейблы `pod-security.kubernetes.io/warn` |

### Рекомендации

1. **Всегда создавайте PDB** для критичных приложений.
2. **Используйте `maxUnavailable`** для Stateless приложений и `minAvailable` для StatefulSet.
3. **Тестируйте PDB** перед обслуживанием узлов.
4. **Начинайте с `audit` и `warn`** при внедрении PSA, затем переходите к `enforce`.
5. **Используйте `baseline`** для большинства приложений и `restricted` для安全敏感ных.

### См. также

- [Обзор Kubespray](./overview.md) — базовые принципы.
- [Безопасность в Kubespray](./overview.md#безопасность-в-kubespray) — RBAC, сертификаты, NetworkPolicy.
- [Управление кластером](./cluster_management.md) — обслуживание узлов (drain/cordon).
- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/) — официальная документация.
- [Pod Disruption Budgets](https://kubernetes.io/docs/tasks/run-application/configure-pdb/) — официальная документация.

### Внешние ресурсы

- [Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/) — официальная документация PSA.
- [Pod Disruption Budgets](https://kubernetes.io/docs/tasks/run-application/configure-pdb/) — официальная документация PDB.
- [CIS Kubernetes Benchmark](https://www.cisecurity.org/benchmark/kubernetes) — стандарты безопасности Kubernetes.