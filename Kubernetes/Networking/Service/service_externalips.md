# ExternalIPs в Service

## Предварительные требования

**Окружение:**
- Kubernetes v1.36+ (для использования Feature Gate `AllowServiceExternalIPs=false`)
- CNI-плагин с поддержкой kube-proxy (kube-router, Calico, Flannel)
- kube-proxy в режиме iptables или nftables (IPVS также поддерживается)

**Проверка готовности:**
```bash
# Проверка версии кластера
kubectl version --short
# → Client Version: v1.36.x
# → Server Version: v1.36.x

# Проверка режима kube-proxy
kubectl get configmap -n kube-system kube-proxy -o yaml | grep mode
# → mode: "iptables"  # или "nftables" или "ipvs"

# Проверка текущего состояния Feature Gate
kubectl get --raw /metrics | grep -i featuregate
# → или проверка флага в манифесте kube-proxy
```

**Важно:** Данный документ описывает устаревший функционал. Рекомендуется использовать альтернативы: [MetalLB](../metallb.md) или [Gateway API](../gateway_api/definitions.md).

## Определения

**ExternalIPs** — поле в спецификации `Service` (`spec.externalIPs`), позволяющее привязать сервис к одному или нескольким статическим IP-адресам, которые не управляются Kubernetes. Трафик, поступающий на эти IP-адреса с любого узла кластера, перехватывается и направляется на эндпоинты данного сервиса.

**Важный статус (Июль 2026):** Поле `externalIPs` официально **объявлено устаревшим (Deprecated)** начиная с Kubernetes **v1.36** (апрель 2026). Причиной послужила критическая уязвимость безопасности и наличие более совершенных альтернатив (Gateway API, MetalLB).

## Техническая реализация

### Принцип работы через kube-proxy

Когда в манифесте Service указаны IP-адреса в поле `externalIPs`, компонент `kube-proxy` на каждом узле кластера настраивает правила перенаправления. 

1.  **Перехват (Traffic Interception):** Создаются правила NAT, которые отслеживают входящие пакеты на указанные внешние IP.
2.  **DNAT:** Пакет проходит через цепочку `KUBE-SERVICES`, где его `Destination IP` подменяется на `ClusterIP` сервиса, а затем на IP-адрес конкретного выбранного пода.
3.  **Hairpin NAT:** Если трафик инициирован подом внутри кластера и направлен на `externalIP` того же сервиса, `kube-proxy` обеспечивает корректную маршрутизацию пакета обратно в кластер, предотвращая его уход в таблицу маршрутизации узла.
#### Реализация в iptables (v1.30 и ранее)

В режиме `iptables` правила для `externalIPs` создаются в цепочке `KUBE-SERVICES`:

```bash
# Просмотр правил для externalIPs
iptables -t nat -L KUBE-SERVICES -n | grep external
# → -A KUBE-SERVICES -d 203.0.113.50/32 -p tcp -m tcp --dport 80 -j KUBE-SVC-XXXXX
```

Каждый `externalIP` создаёт отдельное правило в цепочке, что приводит к линейному росту количества правил O(n) при увеличении числа внешних IP.

#### Реализация в nftables (v1.31+)

В современном режиме `nftables` правила для `externalIPs` выглядят как вхождения в карту (map) переходов NAT:

```bash
# Просмотр правил nftables
nft list table ip kube-proxy
```

```bash
# Пример концептуального правила nftables
table ip kube-proxy {
    chain services {
        # Прямое перенаправление трафика на внешний IP в цепочку сервиса
        ip daddr 203.0.113.50 tcp dport 80 jump service-my-app
    }
}
```

**Преимущество nftables:** Использование hash-карт обеспечивает константную сложность O(1) для поиска правил, что критично для кластеров с большим количеством сервисов.

**Критическое ограничение:** Kubernetes **не управляет** маршрутизацией этих IP-адресов во внешней сети. Это означает, что:
- Узлы кластера не анонсируют эти IP через ARP/NDP или BGP самостоятельно.
- Администратор должен гарантировать, что внешние маршрутизаторы знают, на какие узлы кластера отправлять трафик для этих IP.
- Необходима настройка статических маршрутов или использование протоколов маршрутизации на внешних маршрутизаторах.

**Валидация работы externalIPs:**
```bash
# Создание тестового сервиса с externalIP
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: test-external-ip
spec:
  selector:
    app: test
  ports:
    - port: 80
      targetPort: 8080
  externalIPs:
    - 192.168.1.100
EOF

# Проверка назначения IP
kubectl get svc test-external-ip
# → NAME               TYPE        CLUSTER-IP     EXTERNAL-IP     PORT(S)
# → test-external-ip   ClusterIP   10.96.0.100    192.168.1.100   80/TCP

# Проверка правил на узле (iptables)
iptables -t nat -L KUBE-SERVICES -n -v | grep 192.168.1.100
# → -A KUBE-SERVICES -d 192.168.1.100/32 -p tcp -m tcp --dport 80 -j KUBE-SVC-XXXXX
```

### Сравнение с альтернативами

| Характеристика | ExternalIPs | LoadBalancer | Gateway API |
| :--- | :--- | :--- | :--- |
| **Управление IP** | Вручную (Администратор) | Автоматически (Cloud/MetalLB) | Автоматически (Controller) |
| **Безопасность** | Низкая (CVE-2020-8554) | Высокая | Высокая (RBAC + Policies) |
| **Уровень OSI** | L4 (TCP/UDP) | L4 (TCP/UDP) | L4 - L7 |
| **Статус в 2026** | **Deprecated (v1.36)** | Stable | **Primary Standard** |
## Безопасность: CVE-2020-8554

Основная причина депрекации `externalIPs` — уязвимость **CVE-2020-8554** (Man-in-the-Middle).

**Суть проблемы:** Любой пользователь с правами на создание сервисов может указать в `externalIPs` любой IP-адрес (например, публичный DNS Google `8.8.8.8`). В этом случае `kube-proxy` перехватит весь трафик от подов кластера, идущий на этот адрес, и направит его в под злоумышленника внутри кластера.

### Детальный сценарий атаки

1. **Злоумышленник** создаёт вредоносный под с приложением, способным принимать трафик (например, прокси-сервер).
2. **Создание сервиса** с `externalIPs`, указывающим на критически важный IP (например, `8.8.8.8` для DNS или IP внешней базы данных).
3. **Перехват трафика:** `kube-proxy` на всех узлах начинает перенаправлять трафик на указанный IP в под злоумышленника.
4. **Возможные последствия:**
   - Перехват конфиденциальных данных (учётные данные, токены)
   - Манипуляция ответами (подмена DNS-ответов)
   - Отказ в обслуживании (если злоумышленник не проксирует трафик)

### Меры защиты (до полного удаления функции)

1.  **Feature Gate:** Начиная с v1.36 рекомендуется отключать поддержку через флаг `--feature-gates=AllowServiceExternalIPs=false`.

2.  **Admission Controllers:** Использование политик для запрета поля `externalIPs`.

**Пример политики Kyverno (рекомендуется):**
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: restrict-external-ips
spec:
  validationFailureAction: Enforce
  background: true
  rules:
  - name: check-external-ips
    match:
      any:
      - resources:
          kinds:
          - Service
    validate:
      message: "Использование externalIPs запрещено из-за CVE-2020-8554."
      pattern:
        spec:
          # Запрещает наличие поля externalIPs
          X(externalIPs): null
```

**Пример политики OPA/Gatekeeper:**
```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8sdisallowexternalips
spec:
  crd:
    spec:
      names:
        kind: K8sDisallowExternalIPs
  targets:
    - target: admission.k8s.io
      rego: |
        package k8sdisallowexternalips
        violation[{"msg": msg}] {
          input.review.object.kind == "Service"
          input.review.object.spec.externalIPs
          msg := "Использование externalIPs запрещено из-за CVE-2020-8554"
        }
---
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sDisallowExternalIPs
metadata:
  name: disallow-external-ips
spec:
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Service"]
```

3.  **RBAC:** Строгое ограничение прав на создание и редактирование объектов `Service`.

**Проверка эффективности защиты:**
```bash
# Попытка создания сервиса с externalIP (должна быть отклонена)
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: test-attack
spec:
  selector:
    app: test
  ports:
    - port: 80
  externalIPs:
    - 8.8.8.8
EOF
# → Error from server: error when creating "STDIN": admission webhook "kyverno" denied the request:
# → Использование externalIPs запрещено из-за CVE-2020-8554.
```

## Практические сценарии

### Сценарий 1: Использование externalIPs (Legacy)

**Предусловия:**
- Маршрутизатор настроен для отправки трафика на внешний IP на узлы кластера
- IP-адрес не используется другими устройствами в сети

**Шаг 1: Создание приложения**
```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: legacy-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: legacy-app
  template:
    metadata:
      labels:
        app: legacy-app
    spec:
      containers:
      - name: app
        image: nginx:latest
        ports:
        - containerPort: 8080
EOF
```

**Шаг 2: Создание сервиса с externalIP**
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: legacy-app-service
spec:
  selector:
    app: legacy-app
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8080
  # Трафик на 203.0.113.50:80 будет перехвачен
  externalIPs:
    - 203.0.113.50
EOF
```

**Шаг 3: Валидация**
```bash
# Проверка сервиса
kubectl get svc legacy-app-service
# → NAME                 TYPE        CLUSTER-IP     EXTERNAL-IP       PORT(S)
# → legacy-app-service   ClusterIP   10.96.0.100    203.0.113.50      80/TCP

# Проверка эндпоинтов
kubectl get endpoints legacy-app-service
# → NAME                 ENDPOINTS                                   AVAILABLE
# → legacy-app-service   10.244.0.10:8080,10.244.0.11:8080,10.244.0.12:8080

# Проверка правил на узле
iptables -t nat -L KUBE-SERVICES -n -v | grep 203.0.113.50
# → -A KUBE-SERVICES -d 203.0.113.50/32 -p tcp -m tcp --dport 80 -j KUBE-SVC-XXXXX

# Тест доступности (с внешнего хоста, если маршрутизация настроена)
curl http://203.0.113.50:80
# → <html>...nginx response...</html>
```

### Сценарий 2: Миграция с externalIPs на MetalLB

**Предусловия:**
- Установлен MetalLB в кластере (см. [Настройка MetalLB](../metallb.md))
- Настроен IP-пул для MetalLB

**Шаг 1: Создание сервиса типа LoadBalancer**
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: migrated-app-service
  annotations:
    metallb.universe.tf/loadBalancerIPs: 203.0.113.50
spec:
  type: LoadBalancer
  selector:
    app: legacy-app
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8080
EOF
```

**Шаг 2: Валидация миграции**
```bash
# Проверка назначения IP от MetalLB
kubectl get svc migrated-app-service
# → NAME                    TYPE           CLUSTER-IP     EXTERNAL-IP       PORT(S)
# → migrated-app-service    LoadBalancer   10.96.0.101    203.0.113.50      80:3XXXX/TCP

# Проверка анонса ARP (на узле кластера)
arping -c 3 203.0.113.50
# → Unicast reply from 203.0.113.50 [XX:XX:XX:XX:XX:XX]  0.XXX ms
```

**Шаг 3: Удаление legacy-сервиса**
```bash
kubectl delete svc legacy-app-service
# → service "legacy-app-service" deleted
```

### Рекомендуемый план миграции в 2026 году

| Исходная среда | Рекомендуемая замена |
| :--- | :--- |
| **Bare Metal** | Переход на **MetalLB** (L2 или BGP) или **Cilium L2 Announce**. Эти решения предоставляют полноценный тип `LoadBalancer` без рисков `externalIPs`. |
| **Облако (AWS/GCP/YC)** | Использование нативного типа `LoadBalancer` с привязкой статического IP через аннотации провайдера. |
| **Сложная маршрутизация** | Внедрение **Gateway API**. Это позволяет разделить ответственность: сетевые инженеры управляют IP через объекты `Gateway`, а разработчики настраивают маршруты через `HTTPRoute/TCPRoute`. |

## Дополнительная информация

### Что НЕ затрагивает депрекация

Удаление `externalIPs` касается **только** поля в спецификации Service. Это не влияет на:
- Внешние IP-адреса узлов (`Node ExternalIP`).
- Поле `status.loadBalancer.ingress` для сервисов типа LoadBalancer.
- Использование внешних DNS-имен через тип `ExternalName`.

### Troubleshooting: типичные проблемы и диагностика

**Проблема 1: Трафик не доходит до сервиса**

*Причины:*
- Маршрутизатор не настроен для отправки трафика на externalIP на узлы кластера
- Firewall блокирует трафик на externalIP
- kube-proxy не создал правила для externalIP

*Диагностика:*
```bash
# Проверка наличия правил iptables
iptables -t nat -L KUBE-SERVICES -n -v | grep <externalIP>
# → Если правило отсутствует — проблема в kube-proxy

# Проверка логов kube-proxy
kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=100
# → Поиск ошибок, связанных с externalIPs

# Проверка маршрутизации (с внешнего хоста)
traceroute <externalIP>
# → Должен показать путь до узла кластера
```

**Проблема 2: Hairpin NAT не работает**

*Симптом:* Под внутри кластера не может обратиться к сервису через externalIP.

*Решение:*
```bash
# Проверка правил Hairpin NAT
iptables -t nat -L KUBE-POSTROUTING -n -v | grep MASQUERADE
# → Должны быть правила для masquerade

# Включение hairpin mode в kube-proxy (если отключен)
kubectl edit configmap -n kube-system kube-proxy
# → hairpinMode: "hairpinVeth"
```

**Проблема 3: Конфликт IP-адресов**

*Симптом:* Два сервиса с одинаковым externalIP.

*Диагностика:*
```bash
# Поиск дубликатов externalIP
kubectl get svc -A -o json | jq '.items[] | select(.spec.externalIPs != null) | {name: .metadata.name, namespace: .metadata.namespace, externalIPs: .spec.externalIPs}'
```

### Best Practices

1. **Избегайте использования externalIPs** — переходите на MetalLB или Gateway API.
2. **Если использование неизбежно:**
   - Ограничьте доступ через RBAC (только администраторы могут создавать сервисы с externalIPs)
   - Внедрите admission-контроллеры (Kyverno/OPA) для автоматического запрета
   - Документируйте все используемые externalIPs во избежание конфликтов
3. **Мониторинг:** Настройте алерты на создание сервисов с externalIPs.
4. **Сетевая изоляция:** Используйте NetworkPolicy для ограничения трафика между сервисами.
5. **Планирование миграции:** Создайте roadmap перехода на альтернативы до полного удаления функции.

### Edge Cases и ограничения

1. **Ограничение на количество IP:** Нет явного ограничения на количество externalIPs в одном сервисе, но каждый IP создаёт отдельное правило в kube-proxy, что влияет на производительность.

2. **Нет проверки уникальности:** Kubernetes не проверяет, используется ли externalIP в другом сервисе. Это может привести к непредсказуемому поведению.

3. **Зависимость от маршрутизации:** Функциональность полностью зависит от внешней маршрутизации. При смене топологии сети требуется ручная перенастройка.

4. **Несовместимость с некоторыми CNI:** Некоторые CNI-плагины (например, Cilium в режиме kube-proxy replacement) могут иметь особенности работы с externalIPs.

5. **Проблемы с IPv6:** Поддержка IPv6 для externalIPs зависит от режима kube-proxy и CNI. Требуется дополнительная настройка.

### См. также

- [Обзор Service](./service_overview.md)
- [Обзор Gateway API](../gateway_api/definitions.md)
- [Настройка MetalLB](../metallb.md)
