# IPVS (IP Virtual Server) в Kubernetes

## Определения

**IPVS (IP Virtual Server)** — высокопроизводительный балансировщик нагрузки транспортного уровня (L4), реализованный в виде модуля ядра Linux. Является частью проекта LVS (Linux Virtual Server) и работает внутри сетевого стека ядра (Netfilter).

**kube-proxy в режиме IPVS** — режим работы сетевого прокси Kubernetes, при котором балансировка трафика между подами реализуется через хеш-таблицы IPVS вместо цепочек правил `iptables`.

**ipset** — вспомогательная утилита ядра Linux, позволяющая хранить большие наборы IP-адресов, сетей или портов в виде эффективных структур данных (хеш-таблиц). В режиме IPVS `kube-proxy` использует `ipset` для реализации исключений (например, `--no-masquerade-cidr`) и управления трафиком, который не подлежит балансировке через IPVS.

**kube-ipvs0** — виртуальный (dummy) сетевой интерфейс, создаваемый `kube-proxy` на каждом узле. Он служит «якорем» для назначения виртуальных IP-адресов сервисов (`ClusterIP`), чтобы ядро Linux понимало, что пакеты, адресованные на VIP, должны обрабатываться локально.

**Hairpin NAT (Loopback NAT)** — механизм ядра Linux, позволяющий поду обращаться к ClusterIP сервиса, в котором он участвует, без потери пакета. Без Hairpin NAT пакет, отправленный подом на VIP и перенаправленный ядром обратно на IP того же пода, был бы отброшен как некорректный.

---

## Основные концепции

### Механизм работы

IPVS предназначен для высокопроизводительного распределения нагрузки. В Kubernetes он перехватывает трафик, направленный на VIP (Virtual IP) сервиса, и выполняет трансляцию адресов (DNAT) на конкретные IP-адреса подов-эндпоинтов.

В отличие от `iptables`, где правила проверяются последовательно (сложность $O(n)$), IPVS использует **хеш-таблицы** (сложность $O(1)$). Это критически важно для кластеров с тысячами сервисов, где `iptables` вызывает значительную нагрузку на CPU и задержки при обновлении правил.

### Внутреннее взаимодействие: IPVS, kube-proxy, CNI и conntrack

Понимание полного пути пакета необходимо для диагностики:

1.  **EndpointSlice Controller** отслеживает изменения в EndpointSlice и передает дельты в `kube-proxy`.
2.  **kube-proxy** на каждом узле получает дельты и инкрементально обновляет таблицы IPVS:
    *   Создает виртуальный сервер (`kube-ipvs0`) для каждого Service ClusterIP.
    *   Добавляет эндпоинты как реальные серверы (backend) в хеш-таблицу.
    *   Настраивает `ipset` для исключений (например, CIDR без маскарадинга).
3.  **CNI-плагин** (Calico, Cilium, Flannel) отвечает за доставку пакета до узла и в namespace пода:
    *   Настраивает veth-пары, маршруты и политики.
    *   При использовании оверлея (VXLAN) инкапсулирует пакет.
4.  **conntrack (Connection Tracking):** IPVS полагается на `nf_conntrack` для отслеживания состояния соединений. Это необходимо для:
    *   **Graceful Termination:** Активные соединения завершаются плавно при удалении пода.
    *   **Hairpin NAT:** Отслеживание возвратного трафика от того же пода.
    *   **Session Affinity:** Привязка клиента к поду по Source IP.

### Алгоритмы балансировки (Schedulers)

IPVS предоставляет широкий выбор алгоритмов распределения трафика, которые настраиваются через `KubeProxyConfiguration`:

| Алгоритм | Код | Описание |
| :--- | :--- | :--- |
| **Round Robin** | `rr` | Простое циклическое распределение (по умолчанию). |
| **Weighted Round Robin** | `wrr` | Учитывает веса целевых узлов (в K8s веса обычно равны). |
| **Least Connection** | `lc` | Отправляет пакет на под с наименьшим количеством активных соединений. |
| **Source Hashing** | `sh` | Гарантирует попадание клиента на тот же под по Source IP (Sticky Sessions). |
| **Destination Hashing** | `dh` | Хеширование по целевому IP-адресу. |
| **Shortest Expected Delay** | `sed` | Минимизирует ожидаемую задержку на основе количества соединений и весов. |
| **Never Queue** | `nq` | Если есть свободный бэкенд, отправляет туда, иначе использует `sed`. |

### Сравнение технологий балансировки

| Критерий | iptables | IPVS | nftables | eBPF (Cilium) |
| :--- | :--- | :--- | :--- | :--- |
| **Масштабируемость** | Низкая (линейная) | Высокая | Высокая | Очень высокая |
| **Скорость поиска** | $O(n)$ | $O(1)$ | $O(1)$ (Sets) | $O(1)$ |
| **Обновление правил** | Полная перезапись | Инкрементальное | Атомарное/Инкрем. | Мгновенное |
| **Алгоритмы** | Только случайный | Множество | Случайный/Round Robin | Любая логика |
| **Зависимости** | Встроено в ядро | Модули ядра + ipset | Ядро 5.x+ | Ядро 5.10+ |

### Ограничения и масштабируемость

- **Максимальное количество сервисов:** IPVS теоретически поддерживает десятки тысяч виртуальных сервисов, но на практике ограничение возникает из-за `conntrack` и `ipset`.
- **Максимальное количество бэкендов:** Ограничено размером хеш-таблицы ядра (по умолчанию 0 = auto, обычно 4096). Для очень больших эндпоинтов может потребоваться увеличение через `/etc/sysconfig/ipvsadm` или sysctl.
- **Режим masquerade:** IPVS использует SNAT для трафика, идущего через виртуальный сервер. Это требует наличия правил `POSTROUTING` в `iptables`/`nftables` или может быть отключено для определенных CIDR.

---

## Предварительные требования

### Аппаратные требования

*   **Процессор:** x86_64 (Intel/AMD) или ARM64.
*   **Память:** Минимум 4 GB RAM на узел. Для кластеров с >5000 сервисами рекомендуется 8+ GB (хеш-таблицы IPVS и `conntrack` занимают невытесняемую память).
*   **Сеть:** Доступность выделенных подсетей без пересечения с существующей инфраструктурой.

### Программные требования

*   **Ядро Linux:** Минимум 4.19 для базового режима IPVS; рекомендуется 5.10+ для стабильной работы `nf_conntrack` и `ipset`.
*   **Пакеты:**
    *   `ipset` (утилита для управления наборами)
    *   `ipvsadm` (утилита для просмотра таблиц IPVS)
    *   Модули ядра: `ip_vs`, `ip_vs_rr`, `ip_vs_wrr`, `ip_vs_sh`, `nf_conntrack`, `nf_conntrack_ipv4`/`nf_conntrack_ipv6`
*   **Kubernetes:** Версия 1.20+ для стабильной поддержки IPVS в `kube-proxy`.
*   **CNI-плагин:** Любой совместимый (Calico, Cilium, Flannel).

### Проверка текущего состояния

```bash
# Проверка версии ядра
uname -r
# → 5.15.0-78-generic

# Проверка загруженных модулей IPVS
lsmod | grep -E 'ip_vs|nf_conntrack'
# → ip_vs_rr                16384  0
# → ip_vs_wrr               16384  0
# → nf_conntrack           163840  12

# Проверка установленных утилит
which ipvsadm ipset
# → /usr/sbin/ipvsadm
# → /usr/sbin/ipset

# Проверка текущего режима kube-proxy
kubectl -n kube-system get configmap kube-proxy -o yaml | grep mode
# → mode: "ipvs"

# Проверка наличия интерфейса kube-ipvs0
ip addr show kube-ipvs0
# → 3: kube-ipvs0: <BROADCAST,NOARP> mtu 1500 qdisc noop state DOWN group default
# →     inet 10.96.0.1/32 scope global kube-ipvs0
```

---

## Практические сценарии

### 1. Подготовка узлов

Для включения режима необходимо установить пакеты и загрузить модули ядра на всех узлах кластера.

```bash
# Установка утилит (Debian/Ubuntu)
sudo apt-get update && sudo apt-get install -y ipset ipvsadm

# Установка утилит (RHEL/CentOS/Rocky)
sudo dnf install -y ipset ipvsadm

# Автозагрузка модулей
cat <<EOF | sudo tee /etc/modules-load.d/ipvs.conf
ip_vs
ip_vs_rr
ip_vs_wrr
ip_vs_sh
nf_conntrack
EOF

# Применение
sudo modprobe ip_vs ip_vs_rr ip_vs_wrr ip_vs_sh nf_conntrack

# Проверка
lsmod | grep -E 'ip_vs|nf_conntrack'
# → ip_vs                 36864  0
# → ip_vs_rr              16384  0
# → nf_conntrack         163840  12
```

### 2. Настройка KubeProxyConfiguration

В ConfigMap `kube-proxy` измените режим и параметры синхронизации:

```yaml
kind: ConfigMap
apiVersion: v1
metadata:
  name: kube-proxy
  namespace: kube-system
data:
  config.conf: |
    kind: KubeProxyConfiguration
    mode: "ipvs"
    ipvs:
      strictARP: true          # Обязательно для MetalLB L2
      scheduler: "rr"          # Выбор алгоритма (например, lc для БД)
      syncPeriod: 30s          # Период полной синхронизации правил
      minSyncPeriod: 2s        # Минимальный интервал между обновлениями
```

**Применение:**

```bash
# Применение конфигурации
kubectl apply -f kube-proxy-config.yaml

# Перезапуск DaemonSet kube-proxy для применения изменений
kubectl rollout restart daemonset/kube-proxy -n kube-system

# Проверка статуса
kubectl rollout status daemonset/kube-proxy -n kube-system
# → daemon set "kube-proxy" successfully rolled out
```

### 3. Валидация работы IPVS

После перезапуска `kube-proxy` проверьте корректность настройки:

```bash
# 1. Проверка режима в ConfigMap
kubectl -n kube-system get configmap kube-proxy -o yaml | grep -A 6 'mode:'
# → mode: "ipvs"
# →   strictARP: true
# →   scheduler: "rr"
# →   syncPeriod: 30s
# →   minSyncPeriod: 2s

# 2. Проверка интерфейса kube-ipvs0
ip addr show kube-ipvs0
# → 3: kube-ipvs0: <BROADCAST,NOARP> mtu 1500 qdisc noop state DOWN group default
# →     inet 10.96.0.1/32 scope global kube-ipvs0

# 3. Проверка виртуальных сервисов и бэкендов
sudo ipvsadm -Ln
# → Prot LocalAddress:Port Scheduler Flags
# →   -> RemoteAddress:Port           Forward Weight ActiveConn InActConn
# → TCP  10.96.0.1:443 rr
# →   -> 192.168.1.10:6443            Masq    1      0          0

# 4. Проверка статистики в реальном времени
sudo watch -n 1 ipvsadm -Ln --stats
# → InActConn и ActiveConn должны расти при трафике

# 5. Проверка работы через Service
kubectl run test-pod --image=busybox --restart=Never -- sleep 3600
kubectl exec -it test-pod -- wget -qO- http://<service-name>:<port>
# → должен вернуть ответ от приложения
```

### 4. Graceful Termination (Завершение соединений)

В режиме IPVS реализован механизм корректного завершения соединений при удалении подов:
1. Когда под переходит в состояние `Terminating`, он помечается как `Weight: 0` в таблице IPVS.
2. Новые соединения на этот под не направляются.
3. **Активные соединения (ActiveConn)** продолжают обслуживаться до их закрытия клиентом или сервером.
4. После закрытия всех соединений под полностью удаляется из таблицы.

### 5. Использование с MetalLB (strictARP)

Параметр `strictARP: true` необходим в L2-режиме MetalLB. Он заставляет ядро игнорировать ARP-запросы для VIP на тех интерфейсах, где этот VIP не настроен явно, предотвращая конфликты, когда несколько узлов пытаются отвечать на один ARP-запрос.

### 6. Тюнинг conntrack для IPVS

IPVS полагается на `nf_conntrack` для отслеживания соединений. В высоконагруженных кластерах необходимо увеличивать лимиты:

```bash
# Проверка текущего использования
sudo sysctl net.netfilter.nf_conntrack_count
# → 342       # текущее количество отслеживаемых соединений

sudo sysctl net.netfilter.nf_conntrack_max
# → 65536     # максимальное значение

# Увеличение лимита (временно)
sudo sysctl -w net.netfilter.nf_conntrack_max=1000000
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=7200

# Проверка таблицы после увеличения
sudo sysctl net.netfilter.nf_conntrack_max
# → 1000000

# Постоянное сохранение (Debian/Ubuntu)
cat <<EOF | sudo tee /etc/sysctl.d/99-ipvs-conntrack.conf
net.netfilter.nf_conntrack_max = 1000000
net.netfilter.nf_conntrack_tcp_timeout_established = 7200
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_loose = 0
EOF
sudo sysctl -p /etc/sysctl.d/99-ipvs-conntrack.conf
```

**Важные параметры:**
*   `nf_conntrack_max`: Общее количество отслеживаемых соединений. Для кластеров с >10k подов рекомендуется минимум 1M.
*   `nf_conntrack_tcp_timeout_established`: Таймаут для установленных TCP-соединений (по умолчанию 5 дней). Уменьшение до 2 часов снижает нагрузку на память.
*   `nf_conntrack_tcp_loose`: Отключение (0) повышает безопасность, rejecting невалидные пакеты, но требует корректной работы `sessionAffinity`.

---

## Диагностика и устранение неполадок

### Использование ipvsadm

```bash
# Просмотр виртуальных сервисов и бэкендов
sudo ipvsadm -Ln
# Prot LocalAddress:Port Scheduler Flags
#   -> RemoteAddress:Port           Forward Weight ActiveConn InActConn
# TCP  10.96.0.10:80 rr
#   -> 10.244.1.5:8080    Masq    1      0          0

# Статистика трафика в реальном времени
sudo watch ipvsadm -Ln --stats

# Просмотр таймаутов TCP/UDP
sudo ipvsadm -L --timeout
# → Timeout(tcp): 900 seconds
# → Timeout(tcpfin): 120 seconds
# → Timeout(udp): 300 seconds
```

### Использование ipset

Просмотр наборов, которые `kube-proxy` использует для исключений:

```bash
# Список всех сетов
sudo ipset list -n
# → KUBE-LOOP-BACK
# → KUBE-MARK-MASQ
# → KUBE-SVC-XXXXXXXX

# Просмотр конкретного сета (например, для локального трафика)
sudo ipset list KUBE-LOOP-BACK
# → Name: KUBE-LOOP-BACK
# → Type: hash:ip,port,ip
# → Revision: 6
# → Size in memory: 16384
# → Number of entries: 12
# → Members:
# → 10.244.0.5,tcp:8080,0.0.0.0
```

### Проверка состояния conntrack

```bash
# Общее количество соединений
sudo conntrack -C
# → 342

# Статистика по ядрам
sudo conntrack -S
# → cpu=0 found=123456 invalid=789 lost=0 insert=0 insert_failed=0

# Список активных соединений (ограничить вывод)
sudo conntrack -L -p tcp --dport 80 | head -n 20
# → tcp      6 431999 ESTABLISHED src=10.244.1.5 dst=10.244.2.3 sport=80 dport=54321 ...
```

### Типичные проблемы и решения

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Pod в статусе ContainerCreating** | IPAM исчерпан или пул перекрывается | `kubectl describe pod <pod>` → Events: `Failed to allocate` | Расширить пул; проверить отсутствие пересечений CIDR |
| **IP конфликт (ARP конфликт)** | Статический IP уже используется | `arping -D <ip>`; проверка логов CNI | Освободить конфликтующий адрес; использовать аннотации с проверкой |
| **Dual-Stack не работает** | Kubelet или CNI не поддерживает IPv6 | `kubectl get nodes -o wide`; проверка `ipv6` в CNI конфиге | Обновить Kubernetes до 1.23+; настроить `podSubnet` с двумя CIDR |
| **Потеря IP после перезапуска узла** | host-local IPAM без синхронизации | `calicoctl ipam show --show-blocks` | Переход на Integrated IPAM (etcd/CRD) для сохранения состояния |
| **Migration stuck** | Cilium Agent не перешел на новый пул | `cilium status --verbose`; логи `cilium-operator` | Увеличить `rollOutCiliumPods=false`; проверить отсутствие блокировок в `CiliumPodIPPool` |

### Проблемы специфичные для IPVS

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Трафик не балансируется** | `kube-proxy` не обновил таблицы IPVS | `ipvsadm -Ln`; `kubectl logs -n kube-system -l k8s-app=kube-proxy` | Проверить `syncPeriod`; перезапустить `kube-proxy` |
| **Connection timeout** | `conntrack` переполнен | `conntrack -C` vs `sysctl net.netfilter.nf_conntrack_max` | Увеличить `nf_conntrack_max` |
| **502/503 при удалении пода** | Нет Graceful Termination или слишком быстрый `PreStop` | `kubectl describe pod <pod>`; `ipvsadm -Ln --stats` (InActConn растет) | Настроить `terminationGracePeriodSeconds`; убедиться, что `PreStop` завершает приложение корректно |
| **strictARP conflict (MetalLB)** | `strictARP: false` в IPVS | `kubectl get configmap kube-proxy -n kube-system -o yaml` | Установить `strictARP: true` |
| **Высокий CPU на kube-proxy** | Большой churn сервисов (создание/удаление) | `top`/`htop` на узле; `kubectl get events --sort-by='.lastTimestamp'` | Увеличить `minSyncPeriod`; рассмотреть переход на `nftables` или `eBPF` |
| **Пакеты теряются** | Неправильный MTU или фрагментация | `ping -M do -s 1400 <pod-ip>`; `tcpdump` | Настроить MTU с учетом VXLAN overhead (1500 → 1450) |

---

## Рекомендации и очистка

### Рекомендации для production

1.  **Всегда выделяйте Service CIDR с запасом:** Если планируется 2000 сервисов, требуется сеть минимум `/16`.
2.  **Используйте IPVS только при необходимости:** Для большинства кластеров `nftables` (Kubernetes 1.31+) достаточно и обеспечивает лучшую совместимость.
3.  **Включите `strictARP: true`:** Обязательно для MetalLB L2 и предотвращения ARP-конфликтов.
4.  **Настройте мониторинг `conntrack`:** Регулярно проверяйте `conntrack -C` и `conntrack -S`. Установите алерты на 80% использования лимита.
5.  **Избегайте пересечения CIDR:** `serviceCIDR`, `podCIDR` и `nodeNetwork` не должны пересекаться.
6.  **Используйте `ipset` для масок:** IPVS автоматически создает `ipset` для `--no-masquerade-cidr`. Убедитесь, что CIDR не пересекается.
7.  **Настройте `minSyncPeriod`:** Увеличение до 5-10s снижает нагрузку на API-сервер при массовом создании сервисов.

### Очистка среды

```bash
# Остановка тестового пода
kubectl delete pod test-pod --ignore-not-found

# Очистка ipset (если требуется)
sudo ipset destroy KUBE-LOOP-BACK
sudo ipset destroy KUBE-MARK-MASQ

# Удаление старых правил IPVS (осторожно!)
sudo ipvsadm -C

# Удаление kube-proxy ConfigMap (вернуть iptables/nftables)
kubectl edit configmap -n kube-system kube-proxy
# → изменить mode: "ipvs" на mode: "nftables"
kubectl rollout restart daemonset/kube-proxy -n kube-system
```

---

## Крайние случаи и ограничения

1.  **Исчерпание conntrack:** При неверно рассчитанном `nf_conntrack_max` новые соединения будут сбрасываться с `timeout` или `connection refused`. Мониторьте `conntrack -S` и настраивайте алерты.
2.  **ARP флуд при strictARP: false:** В L2-средах без `strictARP` несколько узлов могут отвечать на ARP-запросы для одного VIP, вызывая флуд и нестабильную работу MetalLB.
3.  **Block-Based IPAM (Calico) и IPVS:** При сбое узла блок `/26` остается «зарезервированным» до освобождения через `calicoctl ipam release`. Это может привести к фрагментации адресного пространства.
4.  **UDP и задержки:** Для UDP-трафика (например, CoreDNS) могут возникать race conditions в `conntrack`. Рекомендуется использовать **NodeLocal DNSCache**.
5.  **Совместимость ядра:** Для стабильной работы IPVS требуется ядро 4.19+ с поддержкой `CONFIG_IP_VS` и `CONFIG_NF_CONNTRACK`. Всегда проверяйте `uname -r` и `zgrep CONFIG_IP_VS /boot/config-$(uname -r)`.
6.  **Взаимодействие с NetworkPolicy:** IPVS отвечает только за балансировку L4. Сетевые политики (`NetworkPolicy`) по-прежнему реализуются CNI-плагином (Calico, Cilium) через `iptables`, `ipset` или `eBPF`.
7.  **Hairpin NAT в IPVS:** Требует включенного `masquerade` или явной настройки `--hairpin-mode`. Проверяйте с помощью тестового пода внутри того же namespace.

---

## Дополнительные сведения

### Проблемы перекрытия (Subnet Overlap)

При проектировании критически важно исключить пересечение `serviceCIDR` с:
1.  **Node Network:** Физические IP узлов.
2.  **Pod CIDR:** Виртуальные IP подов.
3.  **Transit/Office Network:** Сети, доступные через VPN/Direct Connect.

### См. также

- [**CNI и kube-proxy: роли и взаимодействие**](../cni_kube_proxy_roles.md) — обзор режимов работы прокси и сравнение nftables, iptables, IPVS.
- [**Тип Service — ClusterIP**](../../Service/service_type_clusterip.md) — виртуальные IP и селекторы.
- [**MetalLB: Балансировщик для Bare Metal**](../../metallb.md) — использование IPVS с MetalLB.
