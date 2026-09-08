# Kubespray: Offline установка — Проверка кластера

## Определения

**Валидация кластера (Cluster Verification)** — комплекс мероприятий по проверке работоспособности всех системных компонентов после завершения установки в изолированной среде. В offline-режиме валидация критичнее, чем в облачных кластерах: отсутствие доступа к публичным реестрам делает невозможным быстрое исправление через повторную загрузку образов. Каждая ошибка на этом этапе требует возврата к pc-inet и повторного формирования артефактов.

**Сквозная проверка (E2E Check)** — тестирование цепочки «Registry -> Runtime -> Pod -> Network -> Ingress» для подтверждения отсутствия блокировок в закрытом контуре. Имитирует реальную нагрузку: поды должны не только запуститься, но и получить сетевую связность, DNS-резолвинг и внешний доступ через Ingress.

**Диагностика контейнерного рантайма (Runtime Diagnostics)** — проверка состояния containerd на отдельных узлах через утилиту `crictl`. Позволяет выявить проблемы на уровне рантайма (кэш образов, сокет, логи контейнеров), которые не видны через `kubectl`.

**Проверка источника образов (Image Provenance Check)** — убеждение, что все образы загружены из локального Harbor, а не из публичных реестров. Критично для offline-кластера: образы из публичных реестров недоступны после установки и могут исчезнуть при перезапуске пода.

---

## Основные концепции

### Методология offline-валидации

Валидация offline-кластера отличается от онлайн-кластера по трём параметрам:

1. **Нет повторной загрузки:** Если образ не скачался или повреждён, повторный pull невозможен без доступа к pc-inet. Поэтому проверка образов — первый приоритет.
2. **Доверие к реестру:** Harbor является единственным источником образов. Любая ошибка DNS или TLS по отношению к Harbor блокирует все новые развёртывания.
3. **Физическая изоляция:** Невозможно быстро подключить внешний диск или переключиться на облачный реестр. Все проблемы решаются локальными средствами.

### Многоуровневая модель проверки

Проверка проходит по пяти последовательным слоям. Нарушение порядка приводит к маскировке ошибок нижних уровней.

```text
Уровень 5: Приложения и Ingress ──────────────► Внешний доступ, Hubble UI
           │
Уровень 4: Сеть (Cilium / DNS) ──────────────► Связность подов, резолвинг
           │
Уровень 3: Рантайм (containerd) ─────────────► crictl, кэш образов
           │
Уровень 2: Хранение (etcd) ──────────────────► Кворум, целостность данных
           │
Уровень 1: Инфраструктура (Nodes) ───────────► SSH, Ready, kubelet
```

### Предпосылка: здоровье Harbor

Все проверки образов предполагают, что Harbor работает и доступен. Перед началом валидации кластера убедитесь:

```bash
# На master-1 (или любой узел с доступом к Harbor)
curl -sk https://harbor.domain.local/api/v2.0/health
# → {"status":"healthy"}

# Проверка DNS-резолвинга Harbor
nslookup harbor.domain.local
# → Address: 192.168.1.100

# Проверка доступа к API реестра
curl -sk https://harbor.domain.local/v2/
# → {"errors":[{"code":"UNAUTHORIZED","message":"authentication required"}]}
#    (ожидаемая ошибка — реестр работает, требует токен)
```

Если Harbor недоступен — все последующие проверки бессмысленны. Сначала восстановите реестр (см. [Troubleshooting](./troubleshooting.md)).

### Критерии успешной установки в offline-режиме

В закрытом контуре критически важно убедиться, что образы загружаются исключительно из локального реестра и сетевая связность (eBPF) работает без задержек.

**Ключевые показатели:**

- **Узлы (Nodes):** все участники кластера находятся в статусе `Ready`.
- **Реестр (Registry):** системные образы загружены из локального Harbor (проверка через `crictl`).
- **Источник образов:** ни один под не использует образы из публичных реестров.
- **etcd:** хранилище состояния консистентно и доступно со всех мастеров.
- **Сеть (Network):** Cilium показывает полную связность (Status: OK).
- **DNS:** кластерные имена разрешаются корректно, включая имена Harbor.
- **Балансировщик:** MetalLB успешно назначает VIP-адреса.
- **Ingress:** внешний доступ к сервисам работает через Ingress-контроллер.
- **Сертификаты:** самоподписанные сертификаты Harbor доверены на всех узлах.
- **Инструментарий:** Hubble UI доступен и визуализирует трафик.

---

## Практические сценарии

### 1. Проверка состояния узлов и системных подов

Первичная диагностика через стандартные средства Kubernetes.

**Статус узлов:**
```bash
kubectl get nodes -o wide
# → master-1   Ready   control-plane   v1.34.3   192.168.1.101   containerd://1.7.x
```

**Статус системных компонентов:**
```bash
kubectl get pods -n kube-system
# → cilium-xxxxx           1/1     Running   0          10m
# → kube-apiserver-xxx     1/1     Running   0          12m
```

**Проверка отсутствия ошибок:**
```bash
kubectl get pods -A --no-headers | grep -v Running | grep -v Completed
# → Результат должен быть пустым
```

**Проверка событий кластера:**
```bash
kubectl get events -A --sort-by='.lastTimestamp' | tail -n 20
# → Ищем Warning-события: FailedScheduling, FailedMount, FailedPull
```

### 2. Диагностика контейнерного рантайма (crictl)

Проверка состояния containerd на отдельных узлах. Выполняется по SSH на каждом узле кластера.

**Настройка crictl (если не настроена):**
```bash
cat <<EOF | sudo tee /etc/crictl.yaml
runtime-endpoint: unix:///run/containerd/containerd.sock
image-endpoint: unix:///run/containerd/containerd.sock
timeout: 10
debug: false
EOF
```

**Проверка информации о рантайме:**
```bash
sudo crictl info
# → Проверяем: "sandboxImage", "snapshotter", "registry" mirrors
# → В offline-режиме в "registry" должны быть прописаны mirrors для harbor
```

**Проверка запущенных контейнеров:**
```bash
sudo crictl ps
# → Должны быть видны kube-apiserver, kube-scheduler, kube-controller-manager,
#   coredns, kube-proxy, cilium (на соответствующих узлах)
```

**Проверка образов на узле:**
```bash
sudo crictl images
# → Ожидаемый формат:
# → harbor.domain.local/k8s/registry.k8s.io/kube-apiserver   v1.34.3    abc123   120MB
# → harbor.domain.local/k8s/registry.k8s.io/coredns           v1.12.0    def456   50MB
```

**Проверка логов пода (если под работает):**
```bash
# Найти ID контейнера
sudo crictl ps | grep kube-apiserver
# → abc123def456   harbor.domain.local/k8s/.../kube-apiserver   ...

# Посмотреть логи
sudo crictl logs abc123def456
```

**Очистка мусора (если нужны ресурсы):**
```bash
sudo crictl rmi --prune    # Удалить неиспользуемые образы
sudo crictl rmp -fa         # Удалить завершённые поды (осторожно!)
```

### 3. Валидация хранилища etcd

Проверка здоровья распределенной базы данных. Выполняется на любом мастере.

```bash
# Использование контейнеризированного etcdctl
export ETCDCTL_API=3
kubectl -n kube-system exec -it etcd-master-1 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/ssl/etcd/ca.crt \
  --cert=/etc/kubernetes/ssl/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/ssl/etcd/healthcheck-client.key \
  endpoint health --cluster
# → https://192.168.1.101:2379 is healthy: successfully committed proposal: lasted = 10.2ms
```

**Проверка статуса и кворума:**
```bash
kubectl -n kube-system exec -it etcd-master-1 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/ssl/etcd/ca.crt \
  --cert=/etc/kubernetes/ssl/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/ssl/etcd/healthcheck-client.key \
  endpoint status -w table
# → Критично: RAFT TERM должен быть одинаковым, REVISION не должен сильно расходиться
```

### 4. Проверка DNS внутри кластера

Валидация разрешения имен без выхода за пределы контура.

**Внутренний DNS:**
```bash
kubectl run dns-test --image=busybox:1.37 --rm -it --restart=Never -- nslookup kubernetes.default
# → Server:    10.233.0.3
# → Address:   10.233.0.3#53
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.233.0.1
```

**DNS для Harbor (критично для offline):**
```bash
kubectl run dns-harbor --image=busybox:1.37 --rm -it --restart=Never -- nslookup harbor.domain.local
# → Server:    10.233.0.3
# → Address:   10.233.0.3#53
# → Name:      harbor.domain.local
# → Address:   192.168.1.100
```

**Проверка DNS для кластерных сервисов:**
```bash
kubectl run dns-cilium --image=busybox:1.37 --rm -it --restart=Never -- nslookup hubble-peer.kube-system.svc.cluster.local
# → Должен разрешиться в IP сервиса Hubble
```

### 5. Проверка источника образов

Убеждаемся, что ни один под не загружает образы из публичных реестров.

**Проверка всех образов в кластере:**
```bash
kubectl get pods -A -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' | sort -u
# → Ожидаемый формат:
# → harbor.domain.local/k8s/registry.k8s.io/kube-apiserver:v1.34.3
# → harbor.domain.local/k8s/docker.io/coredns/coredns:v1.12.0
# → harbor.domain.local/helm/cilium/cilium:v1.19.6
#
# → НЕ должно быть:
# → registry.k8s.io/kube-apiserver:...    (публичный реестр)
# → docker.io/library/...                  ( Docker Hub)
# → gcr.io/...                             (Google Container Registry)
```

**Быстрая проверка на наличие публичных реестров:**
```bash
kubectl get pods -A -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' \
  | grep -v "harbor.domain.local" | grep -v "^$"
# → Результат должен быть пустым (все образы из Harbor)
```

**Проверка init-контейнеров:**
```bash
kubectl get pods -A -o jsonpath='{range .items[*]}{range .spec.initContainers[*]}{.image}{"\n"}{end}{end}' \
  | grep -v "harbor.domain.local" | grep -v "^$"
# → Также должен быть пустым
```

### 6. Валидация сетевого плагина Cilium

Проверка eBPF-связности и статуса Hubble.

**Общий статус Cilium:**
```bash
kubectl -n kube-system exec ds/cilium -- cilium status
# → KVStore:                Ok
# → Kubernetes:             Ok 1.34 (v1.34.3)
# → Cluster health:         reachable (all nodes)
```

**Тест связности (Connectivity Test):**
Если установлена утилита `cilium` cli на master-1:
```bash
cilium connectivity test
# → connectivity test passed
```

**Проверка Hubble:**
```bash
# Статус Hubble
kubectl -n kube-system exec ds/cilium -- cilium status --verbose | grep -A5 Hubble
# → Hubble:   Ok   (ui: json-codec)

# Проверка доступности Hubble UI через порт-форвардинг
kubectl -n kube-system port-forward svc/hubble-ui 12000:80 &
# → Открываем http://localhost:12000 в браузере
# → Визуализация:拓扑ology сети, HTTP/gRPC запросы между подами
```

**Проверка Hubble через Ingress (если настроен):**
```bash
kubectl get ingress -n kube-system | grep hubble
# → hubble-ui   hubble-ui.kube-system.svc.cluster.local   192.168.1.201   80

# Тест доступа
curl -s http://192.168.1.201/api/v1/flowslimit
# → Должен вернуть JSON с потоками (или 401 если включена авторизация)
```

### 7. Проверка сертификатов

В offline-кластере Harbor использует самоподписанные сертификаты. Убедитесь, что CA-сертификат доверен на всех узлах.

**Проверка наличия CA-сертификата Harbor:**
```bash
for ip in 192.168.1.{101,102,103,104,105}; do
  ssh admin@$ip "ls /usr/local/share/ca-certificates/harbor* 2>/dev/null && echo '$ip: OK' || echo '$ip: MISSING'"
done
```

**Проверка доверия containerd к Harbor:**
```bash
# На любом узле
sudo crictl pull harbor.domain.local/k8s/registry.k8s.io/pause:3.10
# → Если ошибка x509 — CA-сертификат не установлен или не обновлён
# → После установки CA: sudo update-ca-certificates
```

**Проверка TLS-соединения с Harbor:**
```bash
echo | openssl s_client -connect harbor.domain.local:443 -servername harbor.domain.local 2>/dev/null \
  | openssl x509 -noout -subject -issuer
# → subject: /CN=harbor.domain.local
# → issuer: /CN=harbor.domain.local (самоподписанный) или /CN=Your CA
```

### 8. Тестирование балансировщика и Ingress

Проверка цепочки внешнего доступа.

**Проверка пула MetalLB:**
```bash
kubectl get ipaddresspool -n metallb-system
# → primary-pool   192.168.1.200-192.168.1.210
```

**Проверка внешнего IP для Ingress-контроллера:**
```bash
kubectl get svc -n ingress-nginx ingress-nginx-controller
# → TYPE           EXTERNAL-IP
# → LoadBalancer   192.168.1.200
```

**Тест доступа через Ingress (создание тестового сервиса):**
```bash
# Развернуть тестовый под
kubectl create deployment nginx-test --image=harbor.domain.local/k8s/docker.io/nginx:1.27 --replicas=2
kubectl expose deployment nginx-test --port=80

# Создать Ingress
kubectl create ingress nginx-test --rule="nginx-test.local/*=nginx-test:80"

# Тест доступа (с DNS-записью на IP Ingress)
curl -s -H "Host: nginx-test.local" http://192.168.1.200 | head -5
# → <!DOCTYPE html>
# → <html>
# → <head><title>Welcome to nginx!</title>...

# Удалить тестовый ресурс
kubectl delete deployment nginx-test && kubectl delete svc nginx-test && kubectl delete ingress nginx-test
```

### 9. Тестирование планировщика (Scheduling)

Убеждаемся, что планировщик корректно распределяет поды по узлам.

**Проверка распределения подов:**
```bash
kubectl get pods -A -o wide | awk '{print $8}' | sort | uniq -c | sort -rn
# → Должны быть поды на всех узлах (не только на master-1)
```

**Тест масштабирования:**
```bash
# Создать deployment с 3 репликами
kubectl create deployment scale-test --image=harbor.domain.local/k8s/registry.k8s.io/pause:3.10 --replicas=3

# Проверить, что поды распределены
kubectl get pods -o wide -l app=scale-test
# → Поды должны быть на разных узлах (если есть worker nodes)

# Удалить
kubectl delete deployment scale-test
```

### 10. Проверка PersistentVolume (CSI)

Если используется CSI-плагин для дискового хранилища.

**Проверка StorageClass:**
```bash
kubectl get storageclass
# → NAME                 PROVISIONER                    RECLAIMPOLICY   VOLUMEBINDINGMODE
# → local-path (default)   rancher.io/local-path         Delete          WaitForFirstConsumer
```

**Тест PVC:**
```bash
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
EOF

kubectl get pvc test-pvc
# → STATUS: Bound (если StorageClass поддерживает provisioning)

# Удалить
kubectl delete pvc test-pvc
```

---

## Типовые ошибки при валидации

| Ошибка | Уровень | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `Node NotReady` | Инфраструктура | kubelet не запущен или containerd недоступен | `sudo systemctl status kubelet containerd` |
| `ImagePullBackOff` | Рантайм | Образ недоступен в Harbor или DNS не резолвится | Проверить Harbor, DNS, CA-сертификат |
| `x509: certificate signed by unknown authority` | Рантайм | CA Harbor не установлен на узле | `sudo update-ca-certificates` |
| `etcd: member has too many leaders` | Хранение | Split-brain в etcd (проблема с сетью или временем) | Проверить NTP (`chronyc tracking`), сеть между мастерами |
| `DNS: SERVFAIL` | Сеть | CoreDNS не работает или конфликтует с host DNS | `kubectl -n kube-system logs -l k8s-app=kube-dns` |
| `cilium: BPF datapath errors` | Сеть | Несовместимость ядра и eBPF или MTU mismatch | Проверить `uname -r` >= 5.10, MTU 1450-1500 |
| `LoadBalancer: <pending>` | Ingress | MetalLB не может назначить IP (пул исчерпан или L2-проблема) | `kubectl get events -n metallb-system` |
| `Hubble UI: connection refused` | Приложения | Hubble UI не запущен или Ingress не настроен | `kubectl -n kube-system get pods -l app.kubernetes.io/name=hubble-ui` |
| `PVC: Pending` | Хранение | Нет подходящего StorageClass или узла для provisioning | `kubectl describe pvc <name>` |
| `Pod Evicted` | Рантайм | Нехватка ресурсов (RAM/disk) | `kubectl describe node <name>` -> Conditions |

---

## Чек-лист финальной приемки

### Инфраструктура
- [ ] Все узлы в статусе `Ready`.
- [ ] Версии `kubelet` и `containerd` соответствуют целевым.
- [ ] SSH-доступ работает со всех узлов.
- [ ] NTP-сервис (`chrony`) синхронизирован на всех узлах (`chronyc tracking`).

### Хранение
- [ ] `etcd` кластер находится в состоянии Healthy (все эндпоинты доступны).
- [ ] RAFT TERM одинаков для всех узлов etcd.

### Рантайм
- [ ] `crictl ps` показывает запущенные системные поды на каждом узле.
- [ ] `crictl images` показывает образы из Harbor (не из публичных реестров).
- [ ] Отсутствуют ошибки `ImagePullBackOff` в системных неймспейсах.

### Сеть и DNS
- [ ] Cilium status: `Cluster health: reachable (all nodes)`.
- [ ] DNS-резолвинг работает для кластерных сервисов и Harbor.
- [ ] MetalLB успешно назначил IP из пула.
- [ ] Ingress-контроллер доступен по внешнему IP.

### Приложения
- [ ] Hubble UI доступен по DNS-имени (через Ingress или port-forward).
- [ ] Тестовые поды успешно разрешают внутренние DNS-имена.
- [ ] Тестовый Deployment корректно масштабируется и распределяется по узлам.

### Безопасность
- [ ] CA-сертификат Harbor установлен на всех узлах.
- [ ] TLS-соединение с Harbor работает без ошибок.
- [ ] Все образы загружены из Harbor (нет публичных реестров).

---

## Дополнительная информация

### См. также

- **[Основные концепции](./offline_concepts.md)** — логика перенаправления трафика, настройка containerd и hosts.toml.
- **[План offline-установки](./offline_practical.md)** — дорожная карта проекта и E2E-валидация.
- **[Управление после установки](./post_install_management.md)** — регламент тестирования после изменений.

### Похожие руководства

- **[Верификация HA кластера](../../../../Kubernetes/Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_verification.md)** — детальная проверка etcd, VIP и отказоустойчивости (без offline-специфики).
