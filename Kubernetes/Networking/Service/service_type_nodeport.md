# Тип Service — NodePort

## Предварительные требования

**Окружение:**
- Kubernetes v1.20+ (стабильная поддержка `internalTrafficPolicy`)
- kube-proxy в режиме iptables, IPVS или nftables
- CNI-плагин с поддержкой Service Discovery (Calico, Flannel, Cilium)
- Firewall с открытым диапазоном NodePort (30000–32767) для внешних клиентов

**Проверка готовности:**
```bash
# Проверка версии кластера
kubectl version --short
# → Client Version: v1.30.x
# → Server Version: v1.30.x

# Проверка режима kube-proxy
kubectl get configmap kube-proxy -n kube-system -o yaml | grep mode
# → mode: "iptables"  # или "ipvs" / "nftables" / "" (iptables по умолчанию)

# Проверка диапазона NodePort в API-сервере
kubectl get pod -n kube-system -l component=kube-apiserver -o yaml | grep service-node-port-range
# → --service-node-port-range=30000-32767

# Проверка работы kube-proxy на всех узлах
kubectl get pods -n kube-system -l k8s-app=kube-proxy
# → NAME                READY   STATUS    RESTARTS   AGE
# → kube-proxy-abc123   1/1     Running   0          xxm
# → kube-proxy-def456   1/1     Running   0          xxm
```

## Определения

**NodePort** — тип Service в Kubernetes, который открывает статический порт на каждом узле кластера (Node). Это обеспечивает доступ к приложению из внешней сети по адресу `<NodeIP>:<NodePort>`. 

**Ключевые характеристики:**
- **Наследование:** Является надстройкой над [ClusterIP](./service_type_clusterip.md). Каждый NodePort-сервис автоматически получает ClusterIP.
- **Диапазон портов:** По умолчанию используется диапазон **30000–32767**.
- **Связность:** Трафик, приходящий на NodePort любого узла, может быть перенаправлен на под, находящийся на *другом* узле (в зависимости от `externalTrafficPolicy`).

## Основные концепции

### Механика прохождения трафика

При обращении клиента к `NodeIP:NodePort` происходит следующая цепочка преобразований:

1.  **Вход на узел:** Пакет попадает в сетевой стек узла.
2.  **DNAT (Destination NAT):** `kube-proxy` (через `iptables`, `IPVS` или `nftables`) перехватывает пакет и подменяет `Destination IP:Port` (IP узла : NodePort) на виртуальный `ClusterIP:ServicePort`.
3.  **SNAT (Source NAT):** Если `externalTrafficPolicy` установлена в `Cluster` (по умолчанию), узел может выполнить SNAT, подменив IP клиента на свой внутренний IP, чтобы гарантировать возврат трафика через тот же узел.
4.  **Маршрутизация:** Пакет направляется в сеть CNI к целевому поду.

### Влияние на conntrack (Connection Tracking)

NodePort активно использует модуль ядра `nf_conntrack` для отслеживания состояний соединений. 
- **Риск:** При высоком количестве входящих соединений таблица conntrack может переполниться, что приведет к отбрасыванию пакетов (Drop). 
- **Оптимизация:** В режиме **IPVS** нагрузка на conntrack ниже, так как часть логики перенесена на хеш-таблицы уровня ядра.

### Политики трафика (Traffic Policies)

#### externalTrafficPolicy

Управляет тем, как узел обрабатывает трафик, приходящий из внешней сети.

| Режим | Поведение | Сохранение Source IP | Особенности |
| :--- | :--- | :--- | :--- |
| **`Cluster`** (Default) | Трафик балансируется по всему кластеру (hop между узлами возможен). | **Нет** (заменяется на IP узла) | Простой, но скрывает реальный адрес клиента. |
| **`Local`** | Трафик направляется только на поды, находящиеся на *том же* узле. | **Да** (сохраняется исходный IP) | Исключает лишний сетевой переход. Требует внешнего LB. |

**Механизм `Local` и Health Checks:**
Если установлена политика `Local`, Kubernetes открывает специальный **Health Check NodePort** (поле `healthCheckNodePort`). Внешний балансировщик (например, AWS NLB или F5) опрашивает этот порт:
- `200 OK` — на узле есть хотя бы один живой под этого сервиса.
- `503 Service Unavailable` — подов нет, не посылайте сюда трафик.

#### internalTrafficPolicy

Управляет трафиком, инициированным внутри кластера (East-West).
- **`Cluster`**: Стандартная балансировка между всеми подами.
- **`Local`**: Ограничивает трафик только подами на текущем узле (Node-local). Полезно для минимизации задержек между зависимыми сервисами (например, приложение и его sidecar-агент).

### Параметры конфигурации

- **nodePort:** Можно задать вручную. Если не указан, Kubernetes выберет свободный из диапазона.
- **service-node-port-range:** Настройка API-сервера (флаг `--service-node-port-range`) позволяет изменить стандартный диапазон (например, на `80-32767`).
- **allocateLoadBalancerNodePorts:** Поле в `spec` (для типа `LoadBalancer`), позволяющее отключить автоматическое выделение NodePort, если облачный провайдер поддерживает прямую доставку в поды.

## Практические сценарии

### Сценарии использования

- **Простой внешний доступ:** Когда приложения должны быть доступны извне кластера, NodePort обеспечивает простой способ доступа через IP-адрес узла и выделенный порт.
- **Тестирование и разработка:** NodePort полезен во время тестирования и отладки, позволяя разработчикам обращаться к сервисам со своих локальных компьютеров или из тестовых сред.
- **Комбинирование с внешними балансировщиками:** В on-premise средах NodePort часто используется вместе с классическими балансировщиками (например, HAProxy или Nginx), которые распределяют трафик по IP-адресам узлов и выделенному NodePort, обеспечивая базовую отказоустойчивость.
- **Интеграция устаревших решений:** Системы, не поддерживающие интеграцию с облачными LB или Ingress, могут получить доступ к сервисам кластера напрямую через NodePort.

### Стандартный манифест (Cluster Policy)

Типовой пример для публикации веб-приложения в тестовой среде.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-nodeport
spec:
  type: NodePort
  selector:
    app: nginx
  ports:
    - name: http
      protocol: TCP
      port: 80         # Порт внутри ClusterIP
      targetPort: 80   # Порт в контейнере
      nodePort: 32080  # Явно заданный порт на узлах
```

**Применение и проверка:**
```bash
# Применение манифеста
kubectl apply -f web-nodeport.yaml
# → service/web-nodeport created

# Проверка созданного сервиса
kubectl get svc web-nodeport
# → NAME          TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
# → web-nodeport   NodePort   10.96.x.x       <none>        80:32080/TCP   5s

# Проверка выделенного NodePort
kubectl get svc web-nodeport -o jsonpath='{.spec.ports[0].nodePort}'
# → 32080

# Проверка доступности порта на узлах
ss -tlpn | grep :32080
# → LISTEN  0  128  *:32080  *:*  users:(("kube-proxy",pid=1234,fd=10))

# Проверка доступности извне (с внешнего хоста)
curl http://<NodeIP>:32080
# → <!DOCTYPE html>
# → <html>
# → <head>
# → <title>Welcome to nginx!</title>
```

### Сценарий с сохранением Source IP (Local Policy)

Необходимо для систем логирования и защиты (WAF), когда важно знать реальный IP клиента.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: backend-local
spec:
  type: NodePort
  externalTrafficPolicy: Local
  healthCheckNodePort: 31234 # Порт для проверки состояния узла балансировщиком
  selector:
    app: api
  ports:
    - port: 8080
      targetPort: 8080
      nodePort: 30001
```

**Применение и проверка:**
```bash
# Применение манифеста
kubectl apply -f backend-local.yaml
# → service/backend-local created

# Проверка политики трафика
kubectl get svc backend-local -o jsonpath='{.spec.externalTrafficPolicy}'
# → Local

# Проверка healthCheckNodePort
kubectl get svc backend-local -o jsonpath='{.spec.healthCheckNodePort}'
# → 31234

# Проверка доступности health check (с внешнего LB)
curl http://<NodeIP>:31234/healthz
# → 200 OK  (если на узле есть живой под)
# → 503 Service Unavailable (если подов нет)

# Проверка сохранения Source IP (в логах пода)
kubectl logs -l app=api --tail=10
# → <реальный_IP_клиента> - - [date] "GET / HTTP/1.1" 200
```

**Важно:** При `externalTrafficPolicy: Local` если на узле нет подов сервиса, соединение будет сброшено. Убедитесь, что поды распределены по всем узлам или используйте DaemonSet.

### Мультипортовый сервис

NodePort позволяет открывать несколько портов в рамках одного сервиса.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: multi-port-service
spec:
  type: NodePort
  selector:
    app: database
  ports:
    - name: data
      port: 5432
      targetPort: 5432
      nodePort: 30432
    - name: metrics
      port: 9187
      targetPort: 9187
      nodePort: 30187
```

**Применение и проверка:**
```bash
# Применение манифеста
kubectl apply -f multi-port-service.yaml
# → service/multi-port-service created

# Проверка всех портов сервиса
kubectl get svc multi-port-service
# → NAME                TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)                         AGE
# → multi-port-service   NodePort   10.96.x.x       <none>        5432:30432/TCP,9187:30187/TCP   5s

# Проверка конкретного порта по имени
kubectl get svc multi-port-service -o jsonpath='{.spec.ports[?(@.name=="metrics")].nodePort}'
# → 30187

# Проверка доступности портов
curl http://<NodeIP>:30187/metrics
# → # HELP pg_stat_database ...
```

### Интеграция с внешним балансировщиком (HAProxy)

В on-premise средах NodePort часто используется с внешними балансировщиками для обеспечения отказоустойчивости.

**Конфигурация HAProxy:**
```bash
# /etc/haproxy/haproxy.cfg
frontend k8s_frontend
    bind *:80
    default_backend k8s_backend

backend k8s_backend
    balance roundrobin
    option httpchk GET /healthz
    server worker1 192.168.1.10:32080 check
    server worker2 192.168.1.11:32080 check
    server worker3 192.168.1.12:32080 check
```

**Проверка и перезагрузка:**
```bash
# Проверка конфигурации
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Перезагрузка
sudo systemctl reload haproxy
# → haproxy.service: reloaded

# Проверка статуса бэкендов
echo "show stat" | sudo socat stdio /var/run/haproxy.sock | grep k8s_backend
# → k8s_backend,worker1,0,0,0,0,,0,0,0,,0,,0,0,0,0,UP,1,1,0,1,1,5,,,,0,0,0,0,0,0,0,,0,0,0,0,0,0,0,0,0,
```

### Очистка ресурсов

```bash
# Удаление NodePort сервиса
kubectl delete svc web-nodeport
# → service "web-nodeport" deleted

# Удаление нескольких сервисов
kubectl delete svc web-nodeport backend-local multi-port-service
# → service "web-nodeport" deleted
# → service "backend-local" deleted
# → service "multi-port-service" deleted

# Проверка удаления правил kube-proxy (на узле)
sudo iptables -t nat -L KUBE-NODEPORTS -n | grep 32080
# → (пусто — правила удалены)
```

## Дополнительная информация

### Безопасность и сетевая изоляция

- **Слушает на всех интерфейсах (0.0.0.0):** По умолчанию NodePort открывается на всех IP-адресах всех узлов кластера. Это создает серьезный риск безопасности, если узлы имеют публичные IP.
- **Firewall (NGFW/SG):** Необходимо строго ограничивать доступ к диапазону 30000–32767 на уровне внешних сетевых экранов, разрешая входящий трафик только от доверенных источников (балансировщиков, VPN).
- **Control Plane:** Если мастера (control-plane) не имеют специальных запрещающих правил, порты будут открыты и на них. В промышленных кластерах рекомендуется использовать **Taints** и соответствующие правила Firewall, чтобы исключить мастера из балансировки внешнего трафика.
- **NetworkPolicy:** Стандартные NetworkPolicy не фильтруют трафик на уровне NodePort. Для защиты используйте Firewall на узлах или CNI с поддержкой preDNAT (Calico).

### Dual-stack (IPv4/IPv6)

Kubernetes поддерживает NodePort для обоих семейств протоколов. В режиме Dual-stack сервис может иметь `ipFamilyPolicy: PreferDualStack` или `RequireDualStack`, что создаст правила проброса как для IPv4, так и для IPv6 адресов узлов.

**Проверка Dual-stack:**
```bash
# Проверка ipFamilyPolicy
kubectl get svc web-nodeport -o jsonpath='{.spec.ipFamilyPolicy}'
# → PreferDualStack

# Проверка назначенных IP-семей
kubectl get svc web-nodeport -o jsonpath='{.spec.ipFamilies}'
# → ["IPv4","IPv6"]
```

### Сравнение с альтернативами

| Характеристика | NodePort | LoadBalancer | Gateway API (L4/L7) |
| :--- | :--- | :--- | :--- |
| **Уровень OSI** | L4 (TCP/UDP/SCTP) | L4 (TCP/UDP) | L4 - L7 |
| **Управление IP** | Вручную (IP узлов) | Автоматика провайдера | Централизованное (Gateway) |
| **Диапазон портов** | 30000–32767 | Любые | Любые |
| **Сохранение Source IP** | Только при `Local` policy | Зависит от реализации | Через Proxy Protocol или Policy |
| **Масштабируемость** | Низкая (ручной конфиг) | Высокая | Высокая (интеграция с LB) |

**Gateway API:** В современных архитектурах (2026) NodePort часто используется как «базовая инфраструктура» для реализации Gateway API в on-premise средах (например, через Envoy Gateway или Cilium).

---

## Troubleshooting: типичные проблемы и диагностика

**Проблема 1: NodePort недоступен извне**

*Симптом:* `Connection refused` или `Connection timeout` при обращении к `<NodeIP>:<NodePort>`.

*Причины:*
- Firewall блокирует диапазон 30000–32767
- kube-proxy не запущен или работает с ошибками
- Сервис не создан или не имеет Endpoint'ов

*Диагностика:*
```bash
# Проверка существования сервиса
kubectl get svc web-nodeport
# → NAME          TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
# → web-nodeport   NodePort   10.96.x.x       <none>        80:32080/TCP   5m

# Проверка Endpoint'ов
kubectl get endpoints web-nodeport
# → NAME          ENDPOINTS                     AGE
# → web-nodeport   10.244.0.10:80,10.244.0.11:80  5m

# Проверка состояния kube-proxy
kubectl get pods -n kube-system -l k8s-app=kube-proxy
# → NAME                READY   STATUS    RESTARTS   AGE
# → kube-proxy-abc123   1/1     Running   0          xxm

# Проверка логов kube-proxy
kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=50

# Проверка порта на узле
ss -tlpn | grep :32080
# → LISTEN  0  128  *:32080  *:*  users:(("kube-proxy",pid=1234,fd=10))

# Проверка правил iptables (на узле)
sudo iptables -t nat -L KUBE-NODEPORTS -n | grep 32080
# → DNAT       tcp  --  0.0.0.0/0            0.0.0.0/0            tcp dpt:32080 to:10.96.x.x:80
```

*Решение:*
```bash
# Открытие порта в firewall (firewalld)
sudo firewall-cmd --permanent --add-port=32080/tcp
sudo firewall-cmd --reload

# Или для всего диапазона NodePort
sudo firewall-cmd --permanent --add-port=30000-32767/tcp
sudo firewall-cmd --reload
```

**Проблема 2: Несбалансированная нагрузка при `externalTrafficPolicy: Cluster`**

*Симптом:* При большом количестве подов на разных узлах нагрузка распределяется неравномерно.

*Причина:* В режиме `Cluster` kube-proxy может направить трафик на любой под в кластере, включая поды на других узлах. Это создает дополнительный сетевой переход (hop).

*Диагностика:*
```bash
# Проверка распределения подов по узлам
kubectl get pods -l app=nginx -o wide
# → NAME                     READY   STATUS    IP           NODE
# → nginx-5d6b8c7d4f-abc12   1/1     Running   10.244.0.10   worker-1
# → nginx-5d6b8c7d4f-def34   1/1     Running   10.244.1.10   worker-2

# Проверка политики трафика
kubectl get svc web-nodeport -o jsonpath='{.spec.externalTrafficPolicy}'
# → Cluster
```

*Решение:* Используйте `externalTrafficPolicy: Local` для предотвращения межузлового перехода (но требуется внешний балансировщик).

**Проблема 3: Соединения обрываются под нагрузкой**

*Симптом:* Периодические таймауты, ошибки "Connection reset by peer".

*Причина:* Переполнение таблицы conntrack.

*Диагностика:*
```bash
# Проверка использования conntrack
sudo conntrack -C
# → 32768000    # текущее количество записей

# Проверка лимита
sysctl net.netfilter.nf_conntrack_max
# → 65536000

# Проверка ошибок в логах
journalctl -u kube-proxy | grep "conntrack table full"
# → ... table is full, dropping packet

# Проверка потерь
sudo conntrack -S
# → cpu=0 found=123456 invalid=789 lost=42 insert=0 insert_failed=10
```

*Решение:*
```bash
# Увеличение лимита conntrack (временно)
sudo sysctl -w net.netfilter.nf_conntrack_max=131072

# Постоянное изменение
echo "net.netfilter.nf_conntrack_max = 131072" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Или переход на режим IPVS (меньше нагрузка на conntrack)
```

**Проблема 4: Конфликт портов**

*Симптом:* `The Service "web-nodeport" is invalid: spec.ports[0].nodePort: Invalid value: 32080: provided port is already allocated`

*Причина:* Порт уже занят другим NodePort сервисом.

*Диагностика:*
```bash
# Поиск занятого порта
kubectl get svc --all-namespaces -o json | jq '.items[] | select(.spec.ports[]?.nodePort == 32080) | {name: .metadata.name, namespace: .metadata.namespace}'
# → {
# →   "name": "another-service",
# →   "namespace": "default"
# → }
```

*Решение:* Удалите конфликтующий сервис или не указывайте `nodePort` явно — Kubernetes выберет свободный автоматически.

**Проблема 5: `externalTrafficPolicy: Local` — поды не получают трафик**

*Симпом:* Некоторые узлы не получают трафик, хотя на них есть поды.

*Причина:* Внешний балансировщик не проверяет `healthCheckNodePort` и направляет трафик на узлы без подов.

*Диагностика:*
```bash
# Проверка healthCheckNodePort
kubectl get svc backend-local -o jsonpath='{.spec.healthCheckNodePort}'
# → 31234

# Проверка статуса health check на каждом узле
curl -v http://<NodeIP>:31234/healthz
# → 200 OK (под есть)
# → 503 Service Unavailable (пода нет)
```

*Решение:* Настройте внешний балансировщик на проверку `healthCheckNodePort`.

## Best Practices

1. **Используйте Firewall:** Всегда ограничивайте доступ к диапазону NodePort на уровне сетевых экранов, разрешая трафик только от доверенных источников.

2. **Явное указание nodePort:** Для production-сервисов указывайте `nodePort` явно в манифесте для предсказуемости. Для тестовых сред можно позволить Kubernetes выбрать автоматически.

3. **externalTrafficPolicy: Local для сохранения IP:** Используйте `Local` политику, когда приложению важен реальный IP клиента (WAF, логирование, rate limiting).

4. **Мониторинг conntrack:** Настройте мониторинг таблицы conntrack при высокой нагрузке. Используйте режим IPVS для снижения нагрузки.

5. **Изоляция Control Plane:** Используйте Taints и Firewall для исключения master-узлов из балансировки внешнего трафика.

6. **Документирование портов:** Ведите реестр используемых NodePort для предотвращения конфликтов.

7. **Интеграция с внешним LB:** Всегда используйте внешний балансировщик (HAProxy, Nginx, F5) для обеспечения отказоустойчивости и корректной проверки health checks.

8. **Проверка после деплоя:** Всегда проверяйте доступность NodePort извне после создания сервиса.

## Edge Cases и ограничения

1. **Ограничение диапазона:** По умолчанию доступно только 2768 портов (30000–32767). Этого может быть недостаточно для большого количества сервисов. Диапазон можно изменить через `--service-node-port-range`, но это требует перезапуска API-сервера.

2. **Нет встроенного Health Check:** NodePort не предоставляет встроенного механизма health check для внешних балансировщиков (кроме `healthCheckNodePort` при `externalTrafficPolicy: Local`).

3. **Несбалансированность при Cluster policy:** В режиме `Cluster` нагрузка может распределяться неравномерно, если поды неравномерно распределены по узлам.

4. **Зависимость от kube-proxy:** NodePort полностью зависит от kube-proxy. Если kube-proxy не работает, внешний доступ невозможен.

5. **Несовместимость с sessionAffinity:** `sessionAffinity` работает только на уровне ClusterIP, но не гарантирует сохранение сессии при доступе через NodePort (трафик может быть направлен на другой узел).

6. **Проблемы с MTU:** При использовании некоторых CNI (например, Flannel в режиме VXLAN) может возникнуть проблема с MTU, приводящая к потере пакетов при передаче больших объемов данных через NodePort.

7. **Dual-stack limitations:** В Dual-stack режиме NodePort создает отдельные правила для IPv4 и IPv6. Убедитесь, что внешний балансировщик поддерживает оба протокола.

8. **Миграция на LoadBalancer:** При переходе с NodePort на LoadBalancer (MetalLB) потребуется изменить DNS-записи и конфигурацию внешних систем.

---

## Совет по собеседованию

**Вопрос:** Что такое NodePort и когда его использовать?
**Ответ:** NodePort — тип Service, открывающий статический порт (30000–32767) на всех узлах кластера. Используется для:
1. **Тестирования и разработки** — быстрый внешний доступ без сложной инфраструктуры.
2. **On-premise среды** — когда нет облачного LoadBalancer, в сочетании с внешним балансировщиком (HAProxy, Nginx).
3. **Сохранение Source IP** — при `externalTrafficPolicy: Local` позволяет приложению видеть реальный IP клиента.

### См. также

- [Обзор Service](./service_overview.md)
- [Тип Service — LoadBalancer](./service_type_loadbalancer.md)
- [Gateway API — обзор](../gateway_api/definitions.md)
- [Сводка по типам Service](./service_types_summary.md)
- [Практические сценарии публикации](./service_practical_scenarios.md)
