# NetworkPolicy: Диагностика в продакшене

## Определения

**Production Debugging** — систематический подход к диагностике проблем с NetworkPolicy в работающих production-кластерах. Отличается от dev-среды необходимостью минимального воздействия на работающие сервисы, сбора доказательств перед изменениями и документирования каждого шага.

**Packet Drop Analysis** — анализ отброшенных пакетов для определения, какая именно NetworkPolicy блокирует трафик и почему. Основные инструменты: Cilium Hubble, Calico(calico-node logs), tcpdump, conntrack.

**Policy Verdict** — решение CNI-плагина о судьбе пакета (ALLOW/DROP). В Cilium отображается через `cilium monitor --type policy-verdict`. В Calico — через логи `calico-node`.

** conntrack State** — состояние соединения в таблице отслеживания. NetworkPolicy использует conntrack для stateful фильтрации; неправильное состояние conntrack может приводить к ложным блокировкам.

## Базовые Концепции

### Методология диагностики (6 шагов)

```
1. Определить симптом
   └─ Connection timeout / Connection refused / DNS failure
2. Проверить наличие NetworkPolicy
   └─ kubectl get networkpolicy -n <ns>
3. Определить, какие поды попадают под политику
   └─ kubectl get pods -l <selector>
4. Проверить логи CNI
   └─ hubble observe / calico-node logs
5. Проверить conntrack
   └─ conntrack -S / conntrack -L | grep <ip>
6. Протестировать с temporary pod
   └─ kubectl run debug --image=nicolaka/netshoot
```

### Инструменты диагностики

| Инструмент | Назначение | CNI |
| :--- | :--- | :--- |
| `hubble observe` | Визуализация трафика, DROP-причины | Cilium |
| `cilium monitor` | Мониторинг policy verdicts | Cilium |
| `calicoctl node status` | Статус Calico-узла | Calico |
| `calico-node logs` | Логи Calico с(policy) | Calico |
| `conntrack -L` | Просмотр таблицы соединений | Любой |
| `tcpdump` | Захват пакетов на интерфейсе | Любой |
| `kubectl exec + curl/nc` | Тест связности из пода | Любой |

### Классификация проблем

| Тип проблемы | Симптом | Вероятная причина |
| :--- | :--- | :--- |
| **Полная блокировка** | Connection timeout | Default Deny без разрешающих правил |
| **Частичная блокировка** | Timeout кบาง сервисам | Отсутствует правило для конкретного сервиса |
| **DNS блокировка** | `nslookup` fails | Egress не разрешает порт 53 |
| ** conntrack issue** | Интермитентные timeout | Переполнение conntrack или race condition |
| **Race condition** | Задержки 1-5с при DNS | UDP conntrack race |

## Практические сценарии

### Сценарий 1: Полная блокировка трафика

**Симптом:** Под A не может подключиться к поду B с `connection timed out`.

```bash
# Шаг 1: Проверка наличия политик
kubectl get networkpolicy -n production
# → NAME                    POD-SELECTOR   AGE
# → default-deny-all        <none>         5d
# → allow-frontend          app=frontend   3d

# Шаг 2: Определение целевого пода
kubectl get pods -n production --show-labels | grep api-server
# → api-server-abc123   1/1   Running   app=api-server

# Шаг 3: Проверка политик, которые применяются к целевому поду
kubectl describe networkpolicy default-deny-all -n production
# → PodSelector: {} (выбирает ВСЕ поды)
# → policyTypes: Ingress, Egress
# → Ingress: [] (пусто = запретить всё)
# → Egress: [] (пусто = запретить всё)

# Шаг 4: Проверка, есть ли разрешающие правила
kubectl describe networkpolicy allow-frontend -n production
# → PodSelector: {app: api-server}
# → Ingress from: [{namespaceSelector: {name: frontend}}]
# → Нет Egress правил!

# Шаг 5: Верификация через debug pod
kubectl run debug --image=nicolaka/netshoot --rm -it -n production -- \
  curl -v --connect-timeout 3 http://api-server.production.svc.cluster.local:8080
# → curl: (28) Connection timed out after 3 seconds

# Решение: Добавить Egress-правило для api-server
```

### Сценарий 2: DNS не работает после Default Deny

**Симптом:** Под не может разрешить имя сервиса.

```bash
# Шаг 1: Проверка DNS
kubectl exec -it <pod> -n production -- nslookup kubernetes.default
# → server: 10.96.0.10
# → ** server can't find kubernetes.default: SERVFAIL

# Шаг 2: Проверка Egress-политик
kubectl get networkpolicy -n production -o yaml | grep -A 10 "policyTypes.*Egress"
# → Egress: [] (пусто = всё заблокировано)

# Шаг 3: Проверка, есть ли политика для DNS
kubectl get networkpolicy -n production -o yaml | grep -B5 -A10 "port: 53"
# → Ничего не найдено

# Шаг 4: Верификация через temporary pod
kubectl run debug --image=busybox --rm -it -n production -- \
  nslookup kubernetes.default.svc.cluster.local
# → ** server can't find kubernetes.default.svc.cluster.local: NXDOMAIN

# Решение: Добавить Egress-правило для DNS
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Сценарий 3: conntrack table full

**Симптом:** `nf_conntrack: table full, dropping packet` в dmesg.

```bash
# Шаг 1: Проверка размера таблицы
sysctl net.netfilter.nf_conntrack_max
# → 262144

sysctl net.netfilter.nf_conntrack_count
# → 262100 (почти заполнена)

# Шаг 2: Проверка статистики
conntrack -S
# → cpu=0 found=123456 inserted=123400 dropped=500 invalid=120

# Шаг 3: Определение, какие соединения занимают места
conntrack -L | wc -l
# → 262100

conntrack -L | awk '{print $4}' | sort | uniq -c | sort -rn | head
# → 120000 ESTABLISHED
# → 80000 TIME_WAIT
# → 40000 CLOSE_WAIT

# Шаг 4: Увеличение лимита
sysctl -w net.netfilter.nf_conntrack_max=1048576

# Шаг 5: Снижение таймаутов
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=3600
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30

# Шаг 6: Очистка старых записей
conntrack -D --state TIME_WAIT
```

### Сценарий 4: Hubble/Cilium диагностика

**Симптом:** Cilium показывает DROP для определенного трафика.

```bash
# Шаг 1: Просмотр DROP в реальном времени
hubble observe --namespace production --verdict DROPPED
# → Sep  7 10:15:33.456: production/api-server-abc123:8080 <- production/frontend-def456:43210 DROPPED (Policy denied)

# Шаг 2: Детали конкретного DROP
hubble observe --namespace production --to-pod api-server-abc123 --verdict DROPPED
# → Shows: source pod, destination pod, policy name, reason

# Шаг 3: Проверка политики через Cilium
cilium policy get <policy-name>
# → Shows: endpoint selector, ingress/egress rules

# Шаг 4: Трассировка маршрута пакета
cilium monitor --type trace --from-pod production/frontend-def456
# → Shows: packet path through eBPF programs

# Шаг 5: Проверка identities
cilium identity list | grep api-server
# → 12345   api-server   production   labels:["k8s:app=api-server"]
```

### Сценарий 5: Calico диагностика

```bash
# Шаг 1: Статус Calico
calicoctl node status
# → IPv4 BGP status
# → +---------------+-------------------+-------+----------+-------------+
# │ PEER ADDRESS   │     PEER TYPE     │ STATE │  SINCE   │    INFO     │
# +---------------+-------------------+-------+----------+-------------+
# │ 10.0.0.2       │ global            │ up    │ 10:00:00 │ Established │
# +---------------+-------------------+-------+----------+-------------+

# Шаг 2: Логи Calico
kubectl logs -n kube-system -l k8s-app=calico-node --tail=100 | grep -i "policy\|drop"

# Шаг 3: Проверка iptables (если используется iptables dataplane)
iptables -L cali-pi-XXXX -n -v
# → pkts bytes target  prot opt in  out  source      destination
# →   12  1440 DROP    all  --  *   *    0.0.0.0/0   0.0.0.0/0   /* Calico policy: deny-all */

# Шаг 4: Проверка eBPF (если используется eBPF dataplane)
bpftool map list | grep calico
bpftool prog show | grep calico
```

## Дополнительная информация

### Чек-лист быстрой диагностики

| # | Проверка | Команда |
| :--- | :--- | :--- |
| 1 | Список политик | `kubectl get networkpolicy -A` |
| 2 | Описание политики | `kubectl describe networkpolicy <name> -n <ns>` |
| 3 | Метки подов | `kubectl get pods -n <ns> --show-labels` |
| 4 | DNS из пода | `kubectl exec -it <pod> -- nslookup kubernetes.default` |
| 5 | Связность из пода | `kubectl exec -it <pod> -- curl -v --timeout=3 http://<target>` |
| 6 | conntrack | `conntrack -S` |
| 7 | Логи CNI | `kubectl logs -n kube-system -l k8s-app=cilium --tail=50` |
| 8 | Hubble DROP | `hubble observe --namespace <ns> --verdict DROPPED` |

### Антипаттерны диагностики

1. **Удаление политик для "исправления"** — так вы скрываете проблему, а не решаете её
2. **Отсутствие сбора доказательств** — перед изменением политики сделайте `kubectl get networkpolicy -A -o yaml`
3. **Игнорирование conntrack** — переполнение conntrack маскируется под проблемы NetworkPolicy
4. **Тестирование только через ping** — NetworkPolicy фильтрует по TCP/UDP портам, а не ICMP

### См. также

* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины
* [NetworkPolicy: Логика правил](./rule_logic.md) — как работают правила
* [NetworkPolicy: Лучшие практики](./best_practices.md) — рекомендации
* [conntrack и NetworkPolicy](../traffic_path.md) — поведение conntrack
