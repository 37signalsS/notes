# vCluster — troubleshooting и отладка

> Документ описывает пошаговые алгоритмы диагностики проблем vCluster, инструменты отладки и типичные сценарии восстановления. Архитектура — в [обзоре](./vcluster_overview.md), мониторинг — в [vcluster_monitoring.md](./vcluster_monitoring.md), безопасность — в [vcluster_security_and_sync.md](./vcluster_security_and_sync.md).

## Определения

**Troubleshooting** — систематический процесс диагностики и устранения неполадок в IT-системах. Для vCluster включает проверку всех слоёв стека: сеть, Control Plane, Syncer, Backing Store, workload-приложения.

**Readiness Probe** — проверка готовности контейнера принимать трафик. kube-apiserver проверяет readiness перед включением пода в Endpoints сервиса. Если readiness падает — под исключается из балансировки.

**CrashLoopBackOff** — состояние пода, который постоянно падает и перезапускается с экспоненциальной задержкой (10s, 20s, 40s... до 5 минут). Обычно указывает на ошибку в конфигурации или нехватку ресурсов.

**OOMKilled** — завершение контейнера из-за превышения лимита памяти. kubelet убивает процесс, потребляющий больше `memory.limit`.

**Finalizer** — функция в Kubernetes, блокирующая удаление объекта до выполнения определённых действий. Если finalizer завис — объект не удаляется.

**Owner References** — ссылка на родительский объект (Deployment → ReplicaSet → Pod). Используется GC для каскадного удаления зависимых объектов.

## Основные концепции

### Алгоритм диагностики vCluster (пошаговый)

При возникновении проблемы выполняйте последовательную проверку всех слоёв:

```text
1. Состояние подов vCluster
   └─ kubectl get pods -n <ns> -l app=vcluster
      ├─ Все Running? → перейти к шагу 2
      ├─ CrashLoopBackOff? → проверить логи
      ├─ Pending? → проверить ресурсы/affinity
      └─ ImagePullBackOff? → проверить доступ к registry

2. Готовность Control Plane
   └─ kubectl -n <ns> exec <vcluster-pod> -- kubectl get nodes
      ├─ Виртуальные ноды видны? → перейти к шагу 3
      └─ Нет нод? → проверить sync.fromHost.nodes.enabled

3. Синхронизация с хостом
   └─ kubectl -n <ns> get pods -l vcluster.loft.sh/managed-by
      ├─ Теневые поды есть и Running? → проблема в самом приложении
      ├─ Теневые поды Pending? → проверить ресурсы хоста
      └─ Теневых подов нет? → проблема в Syncer

4. Сетевая доступность
   └─ curl -k https://127.0.0.1:<port>/healthz
      ├─ ok? → проблема в клиенте (kubeconfig, контекст)
      └─ timeout/refused? → проблема в сети/port-forward

5. Backing Store
   └─ kubectl -n <ns> exec <vcluster-pod> -- ls /data/pystate/
      ├─ Файлы есть? → перейти к шагу 6
      └─ Нет файлов? → проблема с PVC/диском

6. Логи Syncer
   └─ kubectl -n <ns> logs <vcluster-pod> -c syncer --tail=100
      ├─ Нет ошибок? → проблема в конфигурации тенанта
      └─ Есть ошибки? → анализировать конкретную ошибку
```

### Инструменты диагностики

| Инструмент | Назначение | Команда |
| :--- | :--- | :--- |
| `kubectl get pods` | Состояние подов Control Plane | `kubectl -n <ns> get pods -l app=vcluster` |
| `kubectl describe pod` | Детали конкретного пода (события, условия) | `kubectl -n <ns> describe pod <pod>` |
| `kubectl logs` | Логи контейнера | `kubectl -n <ns> logs <pod> -c syncer` |
| `kubectl exec` | Интерактивный доступ к поду | `kubectl -n <ns> exec -it <pod> -- sh` |
| `vcluster describe` | Состояние vCluster из CLI | `vcluster describe <name> -n <ns>` |
| `vcluster list` | Список всех vCluster | `vcluster list -n <ns>` |
| `kubectl auth can-i` | Проверка RBAC-прав | `kubectl auth can-i create pods --as=system:serviceaccount:<ns>:vcluster-syncer` |
| `kubectl get events` | События в namespace | `kubectl -n <ns> get events --sort-by=.lastTimestamp` |
| `kubectl get networkpolicy` | Проверка NetworkPolicy | `kubectl -n <ns> get networkpolicy` |
| `kubectl get secret` | Проверка секретов | `kubectl -n <ns> get secret vc-<name>` |
| `crictl logs` | Логи через container runtime | `crictl logs <container-id>` |
| `journalctl` | Логи systemd (Standalone) | `journalctl -u vcluster-<name> -f` |

### Типичные проблемы и решения

#### Проблемы Control Plane

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `vcluster create` зависает на `Waiting for vcluster` | ImagePullBackOff или CrashLoopBackOff | `kubectl -n <ns> describe pod <syncer>` | Проверить registry, версию образа, ресурсы |
| `error: failed to create statefulset: forbidden` | SA vcluster не имеет прав | `kubectl auth can-i create statefulset --as=system:serviceaccount:<ns>:vcluster` | Создать ClusterRoleBinding для SA |
| `x509: certificate signed by unknown authority` | CA перевыпустил сертификат | `kubectl -n <ns> get secret vc-<name> -o yaml` | `kubectl -n <ns> delete pod -l app=vcluster` (рестарт) |
| `etcd OOMKilled` | Превышен лимит RAM при большом числе объектов | `kubectl -n <ns> top pod` | Увеличить memory limit или перейти на external etcd |
| API Server не отвечает на `/healthz` | Backing Store недоступен | `kubectl -n <ns> logs <pod> -c syncer \| grep "backing store"` | Проверить PVC, etcd,permissions |
| `too many open files` | Лимит file descriptors | `kubectl -n <ns> exec <pod> -- cat /proc/1/limits \| grep "open files"` | Увеличить ulimit через SecurityContext |

#### Проблемы Syncer

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `failed to sync resource "pods"` | RBAC Syncer ограничен | `kubectl auth can-i create pods --as=system:serviceaccount:<ns>:vcluster-syncer` | Расширить Role Syncer |
| `watch timeout exceeded` | Высокая нагрузка на API | `kubectl -n <ns> logs <pod> -c syncer \| grep "watch timeout"` | Увеличить `--sync-interval`, оптимизировать количество объектов |
| Поды в vCluster Pending, на хосте нет | Syncer не создал теневые поды | `kubectl -n <ns> get pods -l vcluster.loft.sh/managed-by` | Проверить `sync.toHost.pods.enabled` |
| `forbidden: cannot create resource "networkpolicies"` | Syncer не имеет прав на NetworkPolicy | `kubectl auth can-i create networkpolicies` | Добавить `networking.k8s.io` в Role |
| Syncer не видит CRD из хоста | Generic Sync не включён | `kubectl -n <ns> logs <pod> -c syncer \| grep "crd"` | Включить `sync.toHost.customResources` в vcluster.yaml |
| Двойная синхронизация (объекты дублируются) | Два vCluster в одном namespace | `kubectl get pods -n <ns> -l app=vcluster` | Использовать отдельный namespace для каждого vCluster |

#### Проблемы сети и DNS

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `vcluster connect` зависает на 30s | NetworkPolicy блокирует egress Syncer | `kubectl -n <ns> get networkpolicy` | Добавить разрешающий egress для Syncer |
| DNS внутри vCluster не резолвит | CoreDNS не настроен или down | `kubectl -n <ns> exec <pod> -- nslookup kubernetes.default` | Проверить CoreDNS в `kube-system` vCluster |
| Сервисы хоста недоступны из vCluster | `sync.fromHost.services` отключён | `kubectl -n <ns> get svc` (в vCluster) | Включить `sync.fromHost.services.enabled` |
| `connection refused` при подключении | Port-forward не установлен | `curl -k https://127.0.0.1:<port>/healthz` | Перезапустить `vcluster connect --background` |
| Внешний IP не доступен для vCluster API | Не настроен Ingress/Gateway | `kubectl -n <ns> get ingress` | Настроить Ingress с ssl-passthrough или Gateway API |
| `i/o timeout` при обращении к API | Корпоративный прокси блокирует | `echo $HTTPS_PROXY; curl -v https://<vc-api>` | Настроить `NO_PROXY` для API endpoint |

#### Проблемы с ресурсами

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `forbidden: exceeds quota` | ResourceQuota заполнена | `kubectl describe resourcequota -n <ns>` | Увеличить quota или удалить неиспользуемые поды |
| `Insufficient cpu/memory` | Хост не может разместить поды | `kubectl describe node <node> \| grep "Allocated resources"` | Добавить узлы, уменьшить requests |
| `PersistentVolumeClaim pending` | Нет StorageClass или quota | `kubectl get pvc -n <ns>` | Включить `sync.fromHost.storageClasses`, проверить quota |
| `0/1 nodes are available: 1 Insufficient pod` | Лимит подов на узле | `kubectl describe node <node> \| grep "Allocated pods"` | Увеличить `maxPods` или добавить узлы |
| Control Plane потребляет много CPU | Большинство CRD (>100) | `kubectl -n <ns> top pod` | Увеличить ресурсы или уменьшить число CRD |

#### Проблемы удаления и финализаторов

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `vcluster delete` зависает | Finalizer на PVC или namespace | `kubectl -n <ns> get pod -o json \| jq '.metadata.finalizers'` | Удалить finalizers вручную |
| Namespace не удаляется | Pending finalizers от Syncer | `kubectl get namespace <ns> -o yaml` | `kubectl patch namespace <ns> -p '{"metadata":{"finalizers":null}}'` |
| PVC остаются после delete | Флаг `--keep-pvc` или finalizer | `kubectl get pvc -n <ns>` | `kubectl delete pvc --all -n <ns>` |
| `vcluster delete` падает с `not found` | Объект уже удалён или не создан | Проверить `vcluster list` | Повторить `vcluster delete` (идемпотентно) |

### Отладка Syncer: чтение логов

Логи Syncer — основной источник информации о проблемах. Формат — структурированный JSON.

#### Фильтрация по уровням

```bash
# Только ошибки
kubectl -n team-alpha logs <vcluster-pod> -c syncer | jq 'select(.level=="error")'

# Ошибки за последние 10 минут
kubectl -n team-alpha logs <vcluster-pod> -c syncer --since=10m | jq 'select(.level=="error")'

# Конкретный ресурс
kubectl -n team-alpha logs <vcluster-pod> -c syncer | jq 'select(.msg | contains("pods"))'

# Таймауты
kubectl -n team-alpha logs <vcluster-pod> -c syncer | jq 'select(.msg | contains("timeout"))'
```

#### Ключевые поля логов

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `level` | Уровень лога | `error`, `warning`, `info` |
| `msg` | Сообщение | `failed to sync resource` |
| `err` | Текст ошибки | `forbidden: cannot create` |
| `resource` | Тип ресурса | `pods`, `services`, `secrets` |
| `name` | Имя объекта | `my-app-abc123` |
| `namespace` | Namespace | `default` |

#### Примеры полезных запросов

```bash
# Найти все ошибки RBAC
kubectl -n <ns> logs <pod> -c syncer | jq 'select(.err | contains("forbidden"))'

# Найти проблемы с конкретным deployment
kubectl -n <ns> logs <pod> -c syncer | jq 'select(.name | startswith("my-deploy"))'

# Найти таймауты etcd
kubectl -n <ns> logs <pod> -c syncer | jq 'select(.msg | contains("etcd") and .level=="error")'
```

### Интерактивная отладка

#### Проверка API-сервера vCluster

```bash
# Прямой запрос к API
kubectl -n <ns> exec <vcluster-pod> -- wget -qO- --no-check-certificate https://localhost:8443/healthz
# → ok

# Версия API
kubectl -n <ns> exec <vcluster-pod> -- wget -qO- --no-check-certificate https://localhost:8443/version
# → {"major":"1","minor":"36",...}

# Проверка RBAC
kubectl -n <ns> exec <vcluster-pod> -- kubectl auth can-i list pods --as=system:serviceaccount:default:default
# → yes / no
```

#### Проверка Backing Store

```bash
# Для embedded etcd
kubectl -n <ns> exec <vcluster-pod> -c etcd -- etcdctl endpoint health
# → https://localhost:2379 is healthy: ...

# Для SQLite (K3s)
kubectl -n <ns> exec <vcluster-pod> -- ls -la /data/pystate/
# → db-state (file)

# Размер базы
kubectl -n <ns> exec <vcluster-pod> -c etcd -- etcdctl endpoint status --write-out=table
```

#### Проверка сетевой связности

```bash
# Из пода Syncer → API vCluster
kubectl -n <ns> exec <vcluster-pod> -c syncer -- wget -qO- --no-check-certificate https://localhost:8443/healthz

# Из пода Syncer → API хоста
kubectl -n <ns> exec <vcluster-pod> -c syncer -- wget -qO- --no-check-certificate https://kubernetes.default.svc/healthz

# DNS-резолв
kubectl -n <ns> exec <vcluster-pod> -- nslookup kubernetes.default.svc.cluster.local
```

### Восстановление после сбоев

#### Рестарт Control Plane

```bash
# Мягкий рестарт (без потери данных)
kubectl -n <ns> delete pod <vcluster-pod>
# StatefulSet пересоздаст под, etcd восстановится из PVC

# Принудительный рестарт (если pod завис)
kubectl -n <ns> delete pod <vcluster-pod> --grace-period=0 --force
```

#### Восстановление из CrashLoopBackOff

```bash
# 1. Последние логи
kubectl -n <ns> logs <vcluster-pod> --previous

# 2. Проверить конфигурацию
kubectl -n <ns> get configmap <vcluster-config> -o yaml

# 3. Проверить PVC
kubectl -n <ns> get pvc

# 4. Если PVC повреждён — удалить и пересоздать vCluster
kubectl -n <ns> delete pvc data-<vcluster-pod>
vcluster create <name> -n <ns> -f vcluster.yaml
```

#### Принудительное удаление зависшего vCluster

```bash
# 1. Удалить все поды vCluster
kubectl -n <ns> delete pods --all

# 2. Удалить StatefulSet
kubectl -n <ns> delete statefulset --all

# 3. Удалить Service и остальные ресурсы
kubectl -n <ns> delete svc,secret,configmap,role,rolebinding,serviceaccount --all

# 4. Удалить namespace
kubectl delete namespace <ns> --force --grace-period=0

# 5. Очистить контекст
kubectl config delete-context vcluster_<name>_<ns>
```

### Smoke-test после восстановления

```bash
# 1. Проверить поды
kubectl -n <ns> get pods -l app=vcluster
# → NAME    READY   STATUS    RESTARTS   AGE
# → my-vc   2/2     Running   0          5m

# 2. Подключиться
vcluster connect <name> -n <ns> --update-current

# 3. Проверить ноды
kubectl get nodes
# → NAME           STATUS   ROLES                  VERSION
# → vcluster-node  Ready    control-plane,master   v1.36.0

# 4. Создать тестовый под
kubectl run test --image=busybox --rm -it --restart=Never -- echo "OK"
# → OK

# 5. Проверить синхронизацию
kubectl -n <ns> get pods -l vcluster.loft.sh/managed-by
# → test-<vcluster>-xxx   1/1   Running
```

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — мониторинг и observability](./vcluster_monitoring.md)
- [vCluster — безопасность и синхронизация](./vcluster_security_and_sync.md)
- [vCluster — подключение и доступ](./vcluster_connectivity.md)

### См. также

- [Troubleshooting Kubernetes — обзор](../../Kubernetes/Troubleshooting/troubleshooting_overview.md)
- [etcd — troubleshooting](../../etcd/troubleshooting.md)
- [Prometheus Operator — troubleshooting](../../Prometheus/kubernetes/operator/troubleshooting.md)

### Внешние ссылки

- [vCluster Troubleshooting Guide](https://www.vcluster.com/docs/troubleshooting)
- [Kubernetes Troubleshooting Guide](https://kubernetes.io/docs/tasks/debug/)
- [etcd Troubleshooting](https://etcd.io/docs/v3.5/op-guide/maintenance/)
