# NetworkPolicy: Реализация CNI-плагинами

## Определения

**CNI (Container Network Interface) плагин с поддержкой NetworkPolicy** — сетевой компонент Kubernetes, ответственный не только за обеспечение связности между Pod (подами) на уровнях L2/L3, но и за принудительное исполнение (Enforcement) правил фильтрации трафика, описанных в ресурсах `NetworkPolicy`.

**Data Plane (Плоскость данных)** — уровень сетевого стека, на котором происходит фактическая обработка пакетов (маршрутизация, инкапсуляция, фильтрация). Реализация NetworkPolicy происходит именно здесь.

**Enforcement Point (Точка исполнения)** — место в сетевом пути, где CNI-плагин применяет разрешающие или запрещающие правила. Обычно это происходит на виртуальном интерфейсе пода (`veth-pair`) или внутри сетевого пространства имен пода.

**Identity-based Security (Безопасность на основе идентификаторов)** — метод фильтрации трафика (используется в Cilium), при котором политики применяются не к IP-адресам, а к числовым идентификаторам, присвоенным группам подов на основе их меток (Labels). Это исключает задержки на обновление правил при динамическом изменении IP-адресов.

**Алгоритмическая сложность поиска (O(1) vs O(n))**:
*   **O(n)** — линейный поиск, при котором пакет проверяется против каждого правила по очереди. Характерен для `iptables`.
*   **O(1)** — константный поиск через хеш-таблицы, где время принятия решения не зависит от количества правил. Характерен для eBPF и IPSet.

**Пакетная обработка (Batch Processing)** — подход, при котором множественные изменения правил объединяются в одну атомарную операцию обновления. В `iptables` каждое правило обновляется отдельно (высокий overhead при большом количестве правил). В eBPF и nftables пакетная обработка снижает нагрузку на ядро.

**Важное замечание:** Ресурс NetworkPolicy в Kubernetes является лишь декларацией намерения. Если установленный CNI-плагин не поддерживает этот API (например, стандартный Flannel), политики будут успешно созданы в API-сервере, но никакого эффекта на трафик не окажут.

## Базовые концепции

### Механизмы исполнения правил

Различные CNI используют разные технологии ядра Linux для реализации политик:

1.  **iptables / Netfilter:** Традиционный подход (Calico в стандартном режиме, Kube-router). Правила Kubernetes транслируются в цепочки iptables. При большом количестве подов и политик (свыше 1000) производительность резко снижается из-за линейного перебора и накладных расходов на атомарное обновление таблиц.
2.  **eBPF (Extended Berkeley Packet Filter):** Высокопроизводительный подход (Cilium, Calico eBPF mode). Программы фильтрации загружаются в ядро и выполняются на сетевых событиях. Обеспечивает время поиска O(1) и позволяет анализировать трафик на уровне L7 без переключения контекста и sidecar-прокси.
3.  **Open vSwitch (OVS):** Используется в Antrea и OVN-Kubernetes. Позволяет строить сложные программируемые конвейеры обработки пакетов в пространстве пользователя или ядра через OpenFlow, обеспечивая гибкость и поддержку гибридных сред.
4.  **VPP (Vector Packet Processing):** Поддерживается в Calico. Технология обработки пакетов группами (векторами), обеспечивающая экстремальную пропускную способность для высоконагруженных систем (Telco/HPC).

### Сравнительный анализ CNI-плагинов (Состояние на 2026 год)

| CNI | Основной механизм | L7 / FQDN | Windows | Особенности реализации |
| :--- | :--- | :--- | :--- | :--- |
| **Cilium** | eBPF | Да (Native) | Нет | Identity-based безопасность, замена kube-proxy, встроенный Hubble и Tetragon. |
| **Calico** | iptables / eBPF / VPP | Да (Envoy) | Да | Поддержка BGP, HostEndpoint, GlobalNetworkPolicy, максимальная универсальность. |
| **Antrea** | OVS / eBPF | Да | Да | Иерархические политики (Tiers), интеграция с VMware NSX, SmartNIC offload. |
| **Kube-OVN** | OVN / eBPF | Нет | Нет | Мульти-тенантность (VPC), поддержка KubeVirt, статические IP для подов. |
| **Flannel** | Отсутствует | — | Да | Реализация политик возможна только через Canal (Flannel + Calico). |

### Версии Kubernetes и поддержка NetworkPolicy

| Версия K8s | API-группа | Особенности |
| :--- | :--- | :--- |
| < 1.7 | `extensions/v1beta1` | Устаревший API, не рекомендуется. |
| 1.7 — 1.20 | `networking.k8s.io/v1` | Стабильный API. Базовая поддержка Ingress/Egress. |
| 1.21+ | `networking.k8s.io/v1` | Метка `kubernetes.io/metadata.name` для namespace, `endPort` для диапазонов портов. |
| 1.28+ | `policy.networking.k8s.io/v1alpha1` | AdminNetworkPolicy (ANP) и BaselineAdminNetworkPolicy (BANP). |

### Порядок проверки политик в Data Plane

Пакет проходит через следующие этапы (порядок зависит от CNI):

1.  **ANP (Tier 1):** Если найдено совпадение с `Allow`/`Deny` — оценка прекращается.
2.  **NetworkPolicy (Tier 2):** Аддитивная логика (логическое «ИЛИ»). Если хотя бы одна политика разрешает — трафик проходит.
3.  **BANP (Tier 3):** Правила «по умолчанию», если трафик не был обработан на Tier 1-2.
4.  **Default Allow:** Если ни одна политика не选择了 под — трафик разрешен (стандартное поведение K8s).

> **Примечание:** Если под попал под действие хотя бы одной NetworkPolicy (даже пустой с `policyTypes`), он переходит в режим Default Deny для указанных направлений.

## Практические сценарии

### Архитектурный выбор CNI

При выборе решения следует руководствоваться следующими критериями:

1.  **Высокая нагрузка и Zero Trust:** **Cilium**. eBPF позволяет эффективно обрабатывать десятки тысяч соединений, а Hubble/Tetragon обеспечивают аудит безопасности и визуализацию сетевых аномалий в реальном времени.
2.  **Гибридные среды (Linux + Windows) и Bare-metal:** **Calico**. Позволяет использовать BGP-маршрутизацию для анонсирования IP-адресов напрямую в физическую сеть и обеспечивает единую политику безопасности для разных ОС.
3.  **Виртуализация внутри K8s (KubeVist):** **Kube-OVN**. Предоставляет функции классической сети (подсети, шлюзы, изоляция на уровне L2/L3), необходимые для запуска ВМ.

### Верификация NetworkPolicy после развертывания CNI

После установки CNI-плагина необходимо убедиться, что он реально применяет правила:

```bash
# 1. Проверка поддержки NetworkPolicy CNI
# Calico:
kubectl get pods -n kube-system -l k8s-app=calico-node -o wide
calicoctl node status

# Cilium:
kubectl get pods -n kube-system -l k8s-app=cilium -o wide
cilium status
cilium encrypt status

# 2. Проверка создания правил в ядре
# Calico (iptables):
iptables -L calico-pool -n -v
iptables -L FORWARD -n -v | grep cali

# Calico (eBPF):
bpftool prog show | grep calico

# Cilium (eBPF):
bpftool map list | grep cilium
cilium bpf policy list

# 3. Проверка через временный под с инструментами
kubectl run test-netshoot --rm -it --image=nicolaka/netshoot -- /bin/bash

# Из test-netshoot:
curl -v <service-name>.<namespace>.svc.cluster.local:<port>
nslookup <service-name>.<namespace>.svc.cluster.local
nc -zv <pod-ip> <port>

# 4. Проверка политики через кластерные логи (Cilium)
cilium monitor --type drop
cilium monitor --type policy-verdict

# 5. Проверка через Hubble (Cilium)
hubble observe --namespace <ns> --verdict DROPPED
hubble observe --namespace <ns> --protocol dns
```

### Миграция CNI (например, Flannel -> Cilium)

Миграция CNI — операция с высоким риском, требующая очистки сетевого состояния:

1.  **Подготовка:**
    ```bash
    # Резервное копирование текущих политик
    kubectl get networkpolicy -A -o yaml > backup-networkpolicies.yaml
    
    # Установка нового CNI-оператора (Cilium)
    helm install cilium cilium/cilium --namespace kube-system \
      --set policyEnforcementMode=audit \
      --set hubble.enabled=true
    ```

2.  **Остановка старого CNI:**
    ```bash
    # Удаление Flannel
    kubectl delete daemonset kube-flannel-ds -n kube-system
    kubectl delete configmap kube-flannel-cfg -n kube-system
    
    # На этом этапе связность будет нарушена
    ```

3.  **Очистка узлов (на каждом узле):**
    ```bash
    # Удаление виртуальных интерфейсов
    ip link delete flannel.1
    ip link delete cni0
    ip link delete docker0 2>/dev/null || true
    
    # Очистка конфигурации CNI
    rm -rf /etc/cni/net.d/*
    
    # Сброс правил фильтрации
    iptables -F
    iptables -t nat -F
    iptables -t mangle -F
    ipvsadm -C  # если использовался IPVS
    ```

4.  **Запуск нового CNI и верификация:**
    ```bash
    # Проверка статуса Cilium на каждом узле
    cilium status
    cilium encrypt status
    
    # Проверка связности между подами
    kubectl run test --rm -it --image=busybox -- wget -qO- --timeout=5 http://<service>
    ```

5.  **Ротация подов:** Все прикладные поды должны быть перезапущены для пересоздания интерфейсов. До перезапуска поды могут быть недоступны.
    ```bash
    # Перезапуск всех подов в production namespace
    kubectl rollout restart deployment -n production
    kubectl rollout restart statefulset -n production
    ```

### Пошаговая миграция Calico iptables → Calico eBPF

В Calico возможен плавный переход с iptables на eBPF без полной миграции CNI:

```bash
# 1. Включение eBPF в Calico (все узлы)
calicoctl patch felixconfiguration default --patch='{"spec": {"bpfEnabled": true}}'

# 2. Проверка статуса
calicoctl node status
# Должно показать: "BPF enabled: true"

# 3. Верификация
# Убедиться, что правила работают через eBPF, а не iptables
bpftool prog show | grep calico
iptables -L -n | grep cali  # должно быть меньше правил

# 4. Отключение kube-proxy (опционально, если Calico заменяет его)
kubectl patch daemonset kube-proxy -n kube-system -p '{"spec":{"template":{"spec":{"nodeSelector":{"non-existing": "true"}}}}}'
```

### Решение типичных проблем CNI + NetworkPolicy

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| NetworkPolicy не применяется | CNI не поддерживает NetworkPolicy | `kubectl get pods -n kube-system -l k8s-app=<cni>` | Установить CNI с поддержкой (Calico, Cilium, Antrea) |
| Трафик блокируется, хотя политика разрешает | Приоритет правил или некорректный селектор | `kubectl describe networkpolicy <name>` | Проверить `policyTypes`, `podSelector`, `namespaceSelector` |
| DNS не резолвится после Default Deny | Egress не разрешает порт 53 | `kubectl exec -it <pod> -- nslookup kubernetes.default` | Добавить Egress-правило для kube-dns |
| Высокий CPU на узле | Линейный перебор iptables при >1000 правил | `top` + `iptables -L -n -v \| wc -l` | Перейти на eBPF-based CNI (Cilium) |
| Под не может связаться с другим подом | NetworkPolicy работает с IP подов, а не ClusterIP | `kubectl exec -it <pod> -- curl <service-ip>:<port>` | Использовать `podSelector` вместо `ipBlock` |
| Связность восстанавливается не сразу | conntrack кэширует старые решения | `conntrack -L \| grep <pod-ip>` | Очистить conntrack: `conntrack -D -s <pod-ip>` |

### Тестирование NetworkPolicy перед применением

```bash
# 1. Симуляция через临时 под
kubectl run test-allowed --rm -it --image=nicolaka/netshoot -- \
  curl -v --connect-timeout 3 http://<target-service>:<port>

# 2. Проверка через кластерные инструменты (Cilium)
cilium policy trace -s <source-pod-label> -d <dest-pod-label> --dport <port>

# 3. Проверка DNS-связности
kubectl exec -it <pod> -- nslookup <service>.<namespace>.svc.cluster.local

# 4. Визуализация маршрута пакета (Cilium)
cilium monitor --type trace --from-pod <source-pod>

# 5. Проверка через Hubble (визуальная карта)
hubble observe --namespace <ns> --to-pod <dest-pod> --protocol http

# 6. Тест через OPA/Conftest (GitOps)
conftest test network-policies/ --policy tests/policy_test.rego
```

## Дополнительные сведения

### Архитектурные детали ключевых решений

#### Calico: Универсальность и масштабируемость
*   **HostEndpoint:** Применение NetworkPolicy к интерфейсам хоста (`eth0`). Позволяет защитить узел от внешних атак, превращая каждый сервер в распределенный файрвол.
*   **VPP Data Plane:** Использование Vector Packet Processing позволяет достигать скоростей 100G и выше, что критично для высоконагруженных систем (Telco/HPC).
*   **Dual-stack (IPv4/IPv6):** Полная поддержка политик для обоих протоколов одновременно.

#### Cilium: Интеллект на базе eBPF
*   **L7 Enforcement:** Cilium может фильтровать запросы по HTTP-путям, методам или заголовкам напрямую в ядре или через прозрачный прокси Envoy.
*   **FQDN-фильтрация:** Разрешение доступа к внешним ресурсам по доменным именам (например., `*.example.com`), динамически отслеживая DNS-ответы.
*   **Tetragon:** Система обеспечения безопасности (Security Observability) на базе eBPF, которая может блокировать процессы при попытке нарушения сетевых или системных политик.

#### Antrea: Enterprise возможности
*   **Policy Tiers:** Иерархия (например, `Emergency` > `SecurityAdmin` > `Application`). Правила верхних тиров имеют приоритет и не могут быть переопределены пользователями.
*   **SmartNIC Offload:** Возможность выноса обработки правил OVS на аппаратные сетевые карты, освобождая ресурсы CPU хоста.

### Наблюдаемость и аудит (Logging)

Стандартный API Kubernetes не предусматривает механизмов логирования срабатывания политик. Реализация аудита полностью ложится на CNI-плагин:

*   **Cilium (Hubble):** Позволяет видеть каждый отброшенный пакет в реальном времени через UI или CLI, с указанием ID политики и причины (Deny/Drop).
*   **Calico:** Поддерживает логирование в файл или отправку в системный лог (syslog) через настройку `audit: true` в правилах.
*   **Antrea:** Предоставляет инструмент `Traceflow` для пошаговой визуализации прохождения пакета через цепочки правил.

### Критерии выбора CNI для NetworkPolicy

| Критерий | Calico | Cilium | Antrea |
| :--- | :--- | :--- | :--- |
| eBPF Data Plane | Да (опционально) | Да (по умолчанию) | Нет (Open vSwitch) |
| L7-политики | Ограниченные (Envoy) | Полные (HTTP, gRPC, Kafka) | Ограниченные |
| FQDN Egress | Нет | Да (DNS-based) | Нет |
| Hubble/Tetragon | Нет | Да (встроенная наблюдаемость) | Нет |
| Audit Mode | Да (`audit: true`) | Да (`policyAuditMode`) | Да (Traceflow) |
| Производительность при >1000 правил | Средняя (iptables) / Высокая (eBPF) | Высокая (eBPF) | Средняя (OVS) |
| Интеграция с OPA/Gatekeeper | Да | Да | Да |
| Windows поддержка | Да | Нет | Да |

### См. также
* [NetworkPolicy: Лучшие практики](./best_practices.md) — Zero Trust стратегия и именование.
* [NetworkPolicy: Определения и концепции](./definitions.md) — 3-Tier модель и терминология.
* [NetworkPolicy: Логика правил](./rule_logic.md) — аддитивность и приоритеты.
* [Cilium: Высокопроизводительный CNI](../CNI/cilium.md) — глубокое погружение в eBPF архитектуру.
* [eBPF в Kubernetes](../CNI/ebpf.md) — оптимизация сети, безопасности и наблюдаемости.
