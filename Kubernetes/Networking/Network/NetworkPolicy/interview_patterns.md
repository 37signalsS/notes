# NetworkPolicy: Паттерны для собеседований

## Определения

**Interview Patterns** — типичные вопросы и ответы по NetworkPolicy, встречающиеся на технических собеседованиях на позиции DevOps/SRE/System Administrator. Формат "Что будет если..." (What if...) проверяет глубокое понимание механизма работы политик.

**Default Allow vs Default Deny** — два противоположных поведения сетевой модели. Default Allow — всё разрешено, пока не запрещено явно. Default Deny — всё запрещено, пока не разрешено явно. Kubernetes по умолчанию использует Default Allow до создания первой NetworkPolicy.

**Аддитивность (Additive)** — ключевое свойство NetworkPolicy: итоговый набор правил для пода — это объединение (логическое ИЛИ) ВСЕХ политик, которые выбирают данный под. Каждая новая политика добавляет разрешения, а не заменяет их.

**conntrack** — механизм ядра Linux для отслеживания состояний соединений. NetworkPolicy является stateful: ответный трафик разрешается автоматически через conntrack.

## Базовые Концепции

### Структура ответа на "Что будет если..."

Хороший ответ на собеседовании должен включать:
1. **Прямой ответ** — что произойдет
2. **Почему** — техническое обоснование (какая часть стека отвечает)
3. **Практические следствия** — что сломается/работает
4. **Как исправить** — конкретные шаги

## Практические сценарии

### Вопрос 1: Что будет если удалить ВСЕ NetworkPolicy из namespace?

**Ответ:** Namespace вернется в режим Default Allow. Любой под в этом namespace сможет свободно взаимодействовать со всеми подами во всем кластере.

**Почему:** NetworkPolicy работает по принципу аддитивности. Когда под не попадает ни под одну политику, Kubernetes не применяет никаких ограничений. Удаление всех политик означает, что ни один под не изолирован.

**Практические следствия:**
- Полная потеря сетевой микросегментации
- Возможность lateral movement между подами
- Нарушение требований безопасности (PCI DSS, HIPAA)

**Как исправить:**
```bash
# Быстрое восстановление Default Deny
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
EOF
```

### Вопрос 2: Что будет если `policyTypes` не указан, но `ingress`/`egress` определены?

**Ответ:** Политика **неapplyется**. Kubernetes игнорирует правила, если направление не включено в `policyTypes`. Это самая частая ошибка новичков.

**Почему:** `policyTypes` — обязательное поле, определяющее, в каких направлениях политика активна. Без него правила are мертвы.

**Пример:**
```yaml
# ЭТА ПОЛИТИКА НЕ РАБОТАЕТ!
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: broken-example
spec:
  podSelector:
    matchLabels:
      app: my-app
  ingress:
  - from:
    - podSelector:
        matchLabels:
          role: frontend
# policyTypes отсутствует → правила не применяются!
```

### Вопрос 3: Что будет если `ingress: []` с `policyTypes: [Ingress]`?

**Ответ:** Default Deny для Ingress. Весь входящий трафик к подам, попадающим под `podSelector`, будет заблокирован, даже если есть разрешающие правила в других политиках.

**Почему:** Пустой массив `ingress: []` означает "нет разрешающих правил". Поскольку `policyTypes` включает `Ingress`, под переходит в режим Default Deny.

**Важно:** Это работает АДДИТИВНО. Если есть другая политика с разрешающими Ingress-правилами, трафик будет разрешен (логическое ИЛИ между политиками).

### Вопрос 4: Почему `ipBlock` не работает для East-West трафика?

**Ответ:** IP-адреса подов эфемерны и меняются при каждом перезапуске. `ipBlock` фиксирует CIDR, который не отражает текущие IP подов.

**Почему:** Pod IP выделяется из Pod CIDR узла и может измениться при:
- Перезапуске пода (Reschedule)
- Масштабировании (Scale up/down)
- Обновлении Deployment (Rolling update)

**Правильный подход:** Использовать `podSelector` + `namespaceSelector` для East-West трафика.

### Вопрос 5: Как работает conntrack с NetworkPolicy?

**Ответ:** NetworkPolicy является **stateful**. Если Egress-трафик разрешен, ответный Ingress-трафик (return traffic) разрешается автоматически через conntrack, даже если нет явных Ingress-правил.

**Практическое следствие:** При настройке Egress не нужно создавать зеркальные Ingress-правила для ответов. Однако это работает только для **ответов** на установленные соединения.

**Важно:** При переполнении таблицы conntrack (`nf_conntrack_max`) новые соединения отбрасываются, маскируясь под проблемы NetworkPolicy.

### Вопрос 6: Что будет если `podSelector: {}` с `ingress: []`?

**Ответ:** Default Deny Ingress для **всех** подов в namespace. `podSelector: {}` выбирает все поды; `ingress: []` запрещает весь входящий трафик.

### Вопрос 7: Как комбинируются `namespaceSelector` и `podSelector`?

**Ответ:** В одном элементе массива `from` — логическое И. В разных элементах — логическое ИЛИ.

**Пример:**
```yaml
# В одном объекте (И): под с label app=frontend В namespace tenant-a
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        tenant: tenant-a
    podSelector:
      matchLabels:
        app: frontend

# В разных объектах (ИЛИ): ЛЮБОЙ под в tenant-a ИЛИ frontend в текущем ns
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        tenant: tenant-a
  - podSelector:
      matchLabels:
        app: frontend
```

### Вопрос 8: Что будет если Default Deny Egress без DNS?

**Ответ:** Поды не смогут разрешать DNS-имена. Всё, что использует Service Discovery (а это почти всё), перестанет работать.

**Решение:** Всегда создавайте разрешающую политику для DNS (порт 53 UDP/TCP) ПЕРЕД применением Default Deny Egress.

### Вопрос 9: Как отличить проблему NetworkPolicy от conntrack?

**Ответ:**
- `conntrack -S` — если много `dropped` по `nf_conntrack_full`, проблема в размере таблицы
- `conntrack -L | grep <pod-ip>` — покажет активные соединения
- NetworkPolicy-проблемы проявляются как `connection timeout`
- conntrack-проблемы проявляются как `nf_conntrack: table full, dropping packet` в dmesg

### Вопрос 10: Как протестировать NetworkPolicy перед применением?

**Ответ:**
1. `kubectl apply --dry-run=client -f policy.yaml` — синтаксис
2. `kubectl exec -it <pod> -- curl -v <target>` — реальный тест
3. `hubble observe --verdict DROPPED` (Cilium) — визуализация
4. `conftest test` — семантическая валидация
5. Audit mode (Cilium/Calico) — мониторинг без блокировки

## Дополнительная информация

### Частые ошибки на собеседованиях

| Ошибка | Правильный ответ |
| :--- | :--- |
| "NetworkPolicy фильтрует по IP подов" | NetworkPolicy фильтрует по селекторам (labels), а не по IP |
| "ipBlock работает для East-West" | ipBlock для внешнего трафика; для East-West используйте podSelector |
| "Порядок правил важен" | Порядок в массиве ingress/egress НЕ важен; правила проверяются как набор |
| "NetworkPolicy работает с ClusterIP" | NetworkPolicy работает с IP подов, а не с ClusterIP |
| "hostNetwork поды фильтруются" | hostNetwork поды НЕ фильтруются стандартной NetworkPolicy |

### Чек-лист подготовки к собеседованию

| # | Тема | Что знать |
| :--- | :--- | :--- |
| 1 | Default Deny | Как создать, что блокирует, как разрешить DNS |
| 2 | policyTypes | Обязательное поле, Ingress/Egress |
| 3 | Аддитивность | ИЛИ между политиками, И внутри from/to |
| 4 | conntrack | Stateful, return traffic, переполнение |
| 5 | CNI | Кто исполняет (Cilium, Calico),iptables vs eBPF |
| 6 | Egress | DNS, metadata API, FQDN |
| 7 | hostNetwork | Не фильтруется, hostEndpoint |
| 8 | Тестирование | dry-run, kubectl exec, hubble |
| 9 | Control Plane | API Server (6443), etcd (2379), изоляция |
| 10 | ServiceAccount/RBAC | Три слоя: RBAC, NetworkPolicy, Admission |
| 11 | DNS | CoreDNS, NodeLocal DNSCache, ndots, conntrack race |
| 12 | kube-proxy/DNAT | NetworkPolicy проверяется после DNAT |
| 13 | Admission Webhooks | Порты webhook (8443, 9443), разрешение от API Server |
| 14 | PSS/PSA | Взаимодействие с NetworkPolicy, privileged vs restricted |
| 15 | Gateway API | Отличия от Ingress, NetworkPolicy для Gateway Controller |

### Вопрос 11: Как защитить Control Plane через NetworkPolicy?

**Ответ:** Ограничить доступ к API Server (6443) и etcd (2379) через NetworkPolicy:

```yaml
# API Server: разрешить только от CIDR узлов кластера
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-apiserver
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: kube-apiserver
  policyTypes:
  - Ingress
  ingress:
  - from:
    - ipBlock:
        cidr: 10.0.0.0/8  # CIDR узлов
    ports:
    - protocol: TCP
      port: 6443
```

**Важно:** etcd должен быть доступен ТОЛЬКО из API Server. В стековой топологии (kubeadm) etcd работает как static pod с hostNetwork — используйте firewall на уровне узла.

### Вопрос 12: Как RBAC и NetworkPolicy работают вместе?

**Ответ:** Это два независимых слоя безопасности:

1. **RBAC** разрешает/запрещает операции через API Server (get, create, delete)
2. **NetworkPolicy** разрешает/запрещает сетевой трафик (IP, порты)

**Пример конфликта:** RBAC разрешает чтение Secrets, но NetworkPolicy блокирует Egress к API Server (6443). Под не сможет прочитать Secret, даже если RBAC разрешает.

**Решение:** Всегда проверяйте оба слоя при диагностике проблем.

### Вопрос 13: Что такое NodeLocal DNSCache и зачем он нужен?

**Ответ:** DaemonSet, кэширующий DNS-ответы на каждом узле (IP: `169.254.20.10`).

**Проблема, которую решает:** UDP conntrack race conditions при высокой нагрузке на CoreDNS. Задержки 1-5 секунд при DNS-резолвинге.

**Преимущества:**
- Снижение нагрузки на CoreDNS
- Минимизация задержек DNS
- Решение conntrack race problems
- Локальное кэширование DNS-ответов

### Вопрос 14: Как работает NetworkPolicy с kube-proxy DNAT?

**Ответ:** NetworkPolicy проверяется ПОСЛЕ DNAT:

```
Клиент → Service ClusterIP → kube-proxy DNAT → Pod IP → NetworkPolicy Check
```

**Практическое следствие:** NetworkPolicy работает с IP подов, а не с ClusterIP. Ingress-правило должно разрешать трафик от источника (Ingress Controller), а не от Service IP.

### Вопрос 15: Как настроить NetworkPolicy для Admission Webhook?

**Ответ:** Разрешить Ingress к webhook подам от API Server:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-webhook
  namespace: kyverno
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: kyverno
  policyTypes:
  - Ingress
  ingress:
  - from:
    - ipBlock:
        cidr: 10.0.0.0/8  # master-узлы
    ports:
    - protocol: TCP
      port: 9443  # webhook порт
```

**Типичные порты:** Kyverno — 9443, Gatekeeper — 8443, OPA — 8443.

### См. также

* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины
* [NetworkPolicy: Логика правил](./rule_logic.md) — аддитивность и И/ИЛИ
* [NetworkPolicy: Control Plane](./control_plane_network_policy.md) — изоляция control plane
* [NetworkPolicy: DNS](./dns_network_policy.md) — DNS-политики и NodeLocal DNSCache
* [Вопросы по Kubernetes Networking](../kubernetes_networking_interview.md) — расширенный список вопросов
