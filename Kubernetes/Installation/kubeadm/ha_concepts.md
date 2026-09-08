# Высокая доступность Control Plane: Keepalived, HAProxy и kube-vip

## Определения

**HA Control Plane (Отказоустойчивый Control Plane)** — архитектура кластера с 3+ узлами управления, обеспечивающая непрерывную работу API-сервера при выходе из строя отдельных серверов. Каждый узел Control Plane запускает `kube-apiserver`, `kube-scheduler`, `kube-controller-manager` и (в Stacked-топологии) `etcd`.

**Virtual IP (VIP)** — виртуальный IP-адрес, который не привязан к конкретному физическому интерфейсу и может динамически перемещаться между узлами кластера. Используется как Control Plane Endpoint — единая точка входа для `kubectl`, `kubelet` и всех компонентов кластера.

**VRRP (Virtual Router Redundancy Protocol)** — сетевой протокол уровня 3, используемый для автоматического назначения VIP активному узлу и обнаружения сбоев. Keepalived реализует VRRP для управления VIP в HA-кластерах Kubernetes.

**nopreempt** — режим VRRP, при котором восстановившийся узел с более высоким приоритетом **не** отбирает VIP обратно. Рекомендуется для Kubernetes, чтобы избежать лишних переключений VIP и кратковременных разрывов соединений при восстановлении узла.

**Gratuitous ARP** — механизм, с помощью которого Keepalived уведомляет сетевое оборудование (коммутаторы, маршрутизаторы) о том, что VIP-адрес переместился на другой MAC-адрес. Используется в режиме Multicast для обновления ARP-таблиц в L2-сегменте.

**Unicast VRRP** — режим работы Keepalived, при котором VRRP-пакеты отправляются на конкретные IP-адреса соседей, а не в Multicast-группу. Необходим в сетях, где Multicast заблокирован или недоступен (большинство облачных и enterprise-сред).

**BFD (Bidirectional Forwarding Detection)** — протокол обнаружения отказов линков с контролем времени жизни (iana-dud). Работает в паре с VRRP для ускорения обнаружения недоступности узла: вместо ожидания нескольких интервалов `advert_int` (по умолчанию 1 секунда), BFD детектирует отказ за миллисекунды.

**Control Plane Endpoint** — стабильный адрес (DNS или VIP:Port), который используется всеми компонентами кластера (`kubelet`, `kube-proxy`, `scheduler`) и администраторами (`kubectl`) для взаимодействия с API-сервером. Задаётся через флаг `--control-plane-endpoint` при `kubeadm init`.

**Stacked etcd** — топология, при которой распределённое хранилище `etcd` запускается на тех же узлах, что и компоненты Control Plane. Стандартная схема для `kubeadm`: манифест `/etc/kubernetes/manifests/etcd.yaml` автоматически создаётся при инициализации. Подробнее: [etcd: распределённое хранилище](../../Concepts/etcd_overview.md).

**External etcd** — топология с выносом `etcd` на отдельную группу выделенных узлов для максимальной изоляции и производительности. Рекомендуется для крупных кластеров с высокой нагрузкой на запись.

**ip_nonlocal_bind** — параметр ядра Linux (`net.ipv4.ip_nonlocal_bind`), позволяющий процессам (например, HAProxy) привязываться к IP-адресам, которые ещё не назначены интерфейсу. Критично для запуска HAProxy на BACKUP-узлах, которые не владеют VIP, но должны быть готовы принять трафик.

**Connection Draining** — механизм плавного завершения активных TCP-соединений при исключении бэкенда из балансировки. В HAProxy реализуется через параметры `timeout server` и `option redispatch`, позволяющие перенаправить незавершённые соединения на другой健康的 бэкенд.

**BGP (Border Gateway Protocol)** — протокол маршрутизации уровня 3, используемый kube-vip для анонсирования VIP через маршрутизаторы. В отличие от ARP (L2), BGP работает в L3-средах и поддерживает ECMP (Equal-Cost Multi-Path) для распределения трафика между несколькими узлами.

---

## Основные концепции

### Проблема единой точки отказа (SPOF)

В стандартной установке с одним мастером отказ этого узла приводит к:
- Прекращению обработки всех API-запросов.
- Невозможности управления жизненным циклом подов и сервисов.
- Работающие поды продолжают выполнение, но контроллеры (например, Deployment) не смогут среагировать на их падение или изменение нагрузки.

**Важно**:.worker-узлы с `kubelet` продолжают работать и выполнять контейнеры, но не могут получить обновления от Control Plane. Через `node-monitor-grace-period` (по умолчанию 40 секунд) узлы будут помечены как `NotReady`, и поды начнут выселяться на другие узлы (если есть куда).

### Архитектура VIP + HAProxy

В bare-metal окружениях без внешнего балансировщика используется связка Keepalived и HAProxy, развернутая непосредственно на мастер-узлах (или на отдельных LB-узлах).

#### Путь трафика (Traffic Flow)
1. **Клиент (kubectl/kubelet)** обращается к `https://<VIP>:7443`.
2. **Keepalived** направляет пакет на узел, владеющий VIP в данный момент.
3. **HAProxy** принимает TCP-соединение на порту 7443.
4. **Балансировщик** проверяет состояние локального и удалённых `kube-apiserver` (порт 6443) через health-проверки.
5. **Трафик** пересылается на один из здоровых бэкендов.

#### Два варианта развёртывания

| Характеристика | На OS-сервисах | Как Static Pods |
| :--- | :--- | :--- |
| **Управление** | Systemd-юниты | Kubelet управляет манифестами |
| **Порядок запуска** | Сервисы запускаются до kubeadm | Запускаются одновременно с Control Plane |
| **Обновление** | Через пакетный менеджер | Через обновление манифестов |
| **Рекомендация** | Отдельные LB-узлы | На тех же узлах, что и Control Plane |

Для Static Pods конфиги размещаются в `/etc/kubernetes/manifests/` (`keepalived.yaml` и `haproxy.yaml`). kubelet поднимает их до запуска `kubeadm init`. Подробности практических конфигов — в [Настройке Keepalived и HAProxy](./keepalived_haproxy_setup.md).

### VRRP: состояние и переключения

Keepalived реализует конечный автомат состояний VRRP с тремя ролями:

```
              ┌─────────────┐
              │   MASTER    │  Узел владеет VIP, обрабатывает трафик
              └──────┬──────┘
                     │ Отказ / Снижение приоритета
                     ▼
              ┌─────────────┐
              │   BACKUP    │  Узел в режиме ожидания, мониторит MASTER
              └──────┬──────┘
                     │ MASTER недоступен
                     ▼
              ┌─────────────┐
              │   FAULT     │  Узел отключён от VRRP-группы
              └─────────────┘
```

**Ключевые параметры переключения:**

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `priority` | Приоритет узла (0-255). Выше = чаще MASTER | MASTER: 105, BACKUP: 100 |
| `advert_int` | Интервал отправки VRRP-announce (сек) | 1 сек (по умолчанию) |
| `nopreempt` | Запрет возврата VIP при восстановлении старого мастера | **Включать** в production |
| `fall` | Количество неудачных проверок до снятия VIP | 3 (по умолчанию) |
| `rise` | Количество успешных проверок до получения VIP | 2 (по умолчанию) |

**Почему nopreempt критичен для Kubernetes:**
- При `preempt` (по умолчанию) восстановившийся узел с `priority=105` немедленно отбирает VIP у узла с `priority=100`.
- Это вызывает кратковременный (1-3 секунды) разрыв всех API-соединений.
- При `nopreempt` VIP остаётся на текущем узле до тех пор, пока он не выйдет из строя. Это предсказуемее и безопаснее для кластера.

### Сравнение режимов VRRP: Multicast vs Unicast

| Характеристика | Multicast | Unicast |
| :--- | :--- | :--- |
| **Тип трафика** | Мультикаст (224.0.0.18) | Уникаст на конкретные IP |
| **Совместимость** | Требует включённого Multicast в L2 | Работает везде |
| **Облачные среды** | Часто заблокирован | Рекомендуется |
| **Безопасность** | сложнее контролировать | Легче фильтровать через firewall |
| **Настройка** | Проще | Требует указания `unicast_peer` |

**Вывод**: В 2026 году **Unicast — де-факто стандарт** для Kubernetes HA. Multicast допустим только в изолированных L2-сегментах без ограничений на мультикаст-трафик.

### HAProxy: продвинутые настройки

HAProxy работает как L4 (TCP) балансировщик для API-сервера. Ключевые аспекты конфигурации:

#### Health-проверки

| Метод | Описание | Когда использовать |
| :--- | :--- | :--- |
| `option tcp-check` | Проверка TCP-соединения | Быстро, но не проверяет готовность API |
| `option httpchk GET /healthz` | HTTP-проверка эндпоинта `/healthz` | **Рекомендуется** — проверяет реальную готовность |
| `option httpchk GET /readyz` | HTTP-проверка `/readyz` | Проверяет, готов ли API принимать запросы |

**Важно**: Использование простого TCP-чека недостаточно — процесс может слушать порт, но быть в состоянии зависания. HTTP-проверка `/healthz` подтверждает, что API-сервер реально обрабатывает запросы.

```haproxy
backend k8s-api
    mode tcp
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200
    server master1 192.168.1.11:6443 check check-ssl verify none inter 3s fall 3 rise 2
    server master2 192.168.1.12:6443 check check-ssl verify none inter 3s fall 3 rise 2
    server master3 192.168.1.13:6443 check check-ssl verify none inter 3s fall 3 rise 2
```

#### Ключевые параметры

| Параметр | Значение по умолчанию | Рекомендация для K8s API |
| :--- | :--- | :--- |
| `maxconn` | 2000 | 4000-8000 (зависит от нагрузки) |
| `timeout connect` | 5000ms | 5000ms |
| `timeout client` | 50000ms | 3600000ms (1 час — long-running requests) |
| `timeout server` | 50000ms | 3600000ms |
| `timeout check` | 5000ms | 5000ms |
| `option redispatch` | выключена | **Включить** — перенаправление при отказе бэкенда |

**Почему timeout client/server = 1 час:**
- `kubectl exec`, `kubectl logs -f`, `kubectl port-forward` создают долгоживущие streaming-соединения.
- При стандартном таймауте 50 секунд这些 соединения разрываются.

### Топологии etcd и кворум

Для обеспечения отказоустойчивости необходимо нечётное количество узлов Control Plane (минимум 3). Это связано с алгоритмом консенсуса **Raft**, который использует `etcd`.

| Количество узлов | Кворум | Допустимые отказы | Рекомендация |
| :--- | :--- | :--- | :--- |
| 1 | 1 | 0 | SPOF — только для тестов |
| 3 | 2 | 1 | Оптимально для большинства систем |
| 4 | 3 | 1 | **Не рекомендуется** — дороже, но не надёжнее |
| 5 | 3 | 2 | Высокая надежность для крупных инсталляций |

> **Почему 4 узла бессмысленны:** кворум = `N/2 + 1`. При 4 узлах кворум = 3, поэтому кластер переживает отказ только **одного** узла — ровно как при 3 узлах, но по цене четвёртого сервера. Хуже того, при сетевом разделении пополам (2 против 2) ни одна сторона не наберёт большинства. Правило: добавление узла имеет смысл только если оно увеличивает допустимое число отказов (3 -> 5 -> 7).

> **Размещение мастеров в разных ЦОД:** растянутый кластер (мастера в трёх ЦОД с быстрым каналом между ними) не меняет математику кворума — правило нечётного числа остаётся прежним, а потеря целого ЦОД эквивалентна потере соответствующего числа узлов. Критично лишь качество сети: Raft чувствителен к задержкам и джиттеру между узлами, поэтому межЦОД-канал должен обеспечивать стабильный RTT < 10 мс.

#### Сравнение топологий etcd

| Характеристика | Stacked (Совмещённая) | External (Выделенная) |
| :--- | :--- | :--- |
| **Ресурсы** | Экономия серверов (мин. 3) | Требует больше серверов (мин. 3+3) |
| **Изоляция** | API и etcd делят CPU/RAM/Disk | Полная изоляция ресурсов |
| **Сложность** | Настраивается через `kubeadm` автоматически | Требует отдельного управления сертификатами |
| **Масштабируемость** | Ограничена ресурсами узла | Позволяет масштабировать etcd независимо |
| **Потеря узла** | Потеря API + etcd одновременно | Потеря etcd не затрагивает API |

Подробнее о внутреннем устройстве etcd (MVCC, WAL, BoltDB, кворум) — в [etcd: распределённое хранилище](../../Concepts/etcd_overview.md).

### kube-vip: современная альтернатива

Вместо связки Keepalived + HAProxy всё чаще используется **kube-vip** — cloud-native решение, работающее как Static Pod внутри Kubernetes.

#### Режимы работы kube-vip

| Режим | Уровень | Механизм | Когда использовать |
| :--- | :--- | :--- | :--- |
| **ARP** | L2 | Gratuitous ARP + Leader Election | Один L2-сегмент, простая топология |
| **BGP** | L3 | BGP-анонс через маршрутизаторы | Мультисегментные сети, ECMP |
| **WireGuard** | L3 | Анонс через WireGuard-интерфейс | Мультикластерная связность |

#### ARP vs BGP: подробное сравнение

| Характеристика | ARP (Layer 2) | BGP (Layer 3) |
| :--- | :--- | :--- |
| **Анонс VIP** | Gratuitous ARP broadcast | BGP UPDATE через пиринг |
| **Балансировка** | Только один узел (Leader) | ECMP — все узлы |
| **Масштаб** | Один L2-сегмент | До глобальных сетей |
| **Требования** | Сеть с Multicast/Broadcast | BGP-пиринг с маршрутизатором |
| **Сложность** | Проще | Выше (настройка AS, peers) |
| **Fault Detection** | Leader Election | BGP health check + withdrawal |

#### Генерация манифеста kube-vip

```bash
# Переменные окружения
export VIP=192.168.1.100
export INTERFACE=eth0
export KVVERSION=$(curl -sL https://api.github.com/repos/kube-vip/kube-vip/releases | jq -r '.[0].name')

# Создание алиаса для kube-vip (containerd)
alias kube-vip="ctr image pull ghcr.io/kube-vip/kube-vip:$KVVERSION; ctr run --rm --net-host ghcr.io/kube-vip/kube-vip:$KVVERSION vip /kube-vip"

# Генерация манифеста (ARP-режим)
kube-vip manifest pod \
    --interface $INTERFACE \
    --address $VIP \
    --controlplane \
    --services \
    --arp \
    --leaderElection | tee /etc/kubernetes/manifests/kube-vip.yaml

# Генерация манифеста (BGP-режим)
kube-vip manifest pod \
    --interface lo \
    --address $VIP \
    --controlplane \
    --services \
    --bgp \
    --localAS 65000 \
    --bgpRouterID 192.168.1.10 \
    --bgppeers 192.168.1.1:65000::false,192.168.1.2:65000::false | tee /etc/kubernetes/manifests/kube-vip.yaml
```

**Порядок развёртывания с kube-vip:**
1. Скопировать манифест `kube-vip.yaml` в `/etc/kubernetes/manifests/` на **всех** Control Plane-узлах.
2. Запустить `kubeadm init --control-plane-endpoint <VIP>:6443` на первом узле.
3. После инициализации kube-vip начнёт анонсировать VIP.
4. Присоединить остальные Control Plane-узлы через `kubeadm join --control-plane`.

**Важно**: kube-vip требует доступа к API-серверу для Leader Election. При первой инициализации используется `super-admin.conf` (с Kubernetes v1.29+), затем переключается на `admin.conf`. Подробнее: [kube-vip: Static Pods](https://kube-vip.io/docs/installation/static).

#### Сравнение Keepalived+HAProxy vs kube-vip

| Критерий | Keepalived + HAProxy | kube-vip |
| :--- | :--- | :--- |
| **Компоненты** | 2 сервиса на ОС | 1 Static Pod |
| **Настройка** | 2 конфигурационных файла | 1 манифест + генератор |
| **Балансировка** | HAProxy (L4) | IPVS (внутри kube-vip) |
| **Отладка** | Проще (системные логи, сокеты) | Сложнее (Kubernetes логи) |
| **Зависимости** | Внешние пакеты (apt/yum) | Контейнерный образ |
| **BGP** | Не поддерживает | Поддерживает |
| **Рекомендация** | Традиционные среды, SLA-требования | Современные инсталляции, простота |

---

## Практические сценарии

### 1. Настройка ядра для HA-режима

Для стабильной работы балансировщиков на всех узлах необходимо разрешить привязку к нелокальным адресам:

```bash
# Проверка текущего значения
sysctl net.ipv4.ip_nonlocal_bind

# Включение параметра (на всех Control Plane-узлах)
cat <<EOF | sudo tee /etc/sysctl.d/60-k8s-ha.conf
net.ipv4.ip_nonlocal_bind = 1
net.ipv4.ip_forward = 1
EOF
sudo sysctl --system

# Проверка
sysctl net.ipv4.ip_nonlocal_bind
# → net.ipv4.ip_nonlocal_bind = 1
```

### 2. Health Checks в HAProxy

HAProxy должен интеллектуально проверять статус API-сервера. Рекомендуется HTTP-проверка эндпоинта `/healthz`:

```haproxy
backend k8s-api
    mode tcp
    option httpchk GET /healthz
    http-check expect status 200
    server master1 192.168.1.11:6443 check check-ssl verify none inter 3s fall 3 rise 2
    server master2 192.168.1.12:6443 check check-ssl verify none inter 3s fall 3 rise 2
    server master3 192.168.1.13:6443 check check-ssl verify none inter 3s fall 3 rise 2
```

Полная конфигурация HAProxy — в [Настройке Keepalived и HAProxy](./keepalived_haproxy_setup.md).

### 3. Тестирование отказа (Failover)

Пошаговый сценарий проверки отказоустойчивости:

#### Шаг 1: Проверка начального состояния

```bash
# Определение узла, владеющего VIP
ip addr show | grep -E 'inet.*vip'
# → 192.168.1.100/24 dev eth0 scope global secondary eth0:vip

# Проверка доступности API через VIP
curl -sk https://192.168.1.100:7443/healthz
# → ok

# Проверка состояния etcd
kubectl exec -n kube-system etcd-master1 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status -w table
```

#### Шаг 2: Эмуляция отказа API-сервера

```bash
# На узле, владеющем VIP — остановить API-сервер
sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/

# Наблюдение за логами Keepalived
sudo journalctl -u keepalived -f

# Ожидаемое поведение:
# 1. HAProxy обнаружит, что бэкенд не отвечает (через fall=3, inter=3s = 9 секунд)
# 2. HAProxy исключит этот бэкенд из балансировки
# 3. Трафик пойдёт на оставшиеся 2 здоровых бэкенда
# 4. Keepalived: если check_haproxy упал, VIP может переключиться
```

#### Шаг 3: Проверка восстановления

```bash
# Вернуть API-сервер
sudo mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/

# Дождаться восстановления (rise=2, inter=3s = 6 секунд)
sleep 15

# Проверка
curl -sk https://192.168.1.100:7443/healthz
# → ok

# Проверка, что VIP вернулся (если nopreempt выключен)
ip addr show | grep -E 'inet.*vip'
```

#### Поведение worker-узлов во время failover

- **kubelet**: Продолжает работать, поды не перезапускаются. kubelet имеет собственный `serverTLSBootstrap` и кеширует токены.
- **kube-proxy**: Перенаправляет трафик через iptables/IPVS правила. При смене VIP правила обновляются автоматически.
- **Поды**: Не затронуты, если API-сервер вернётся в пределах `node-monitor-grace-period` (40 секунд по умолчанию).

### 4. Предотвращение Split-Brain

Split-brain — ситуация, когда VIP поднят на нескольких узлах одновременно. Это приводит к разделению трафика и непредсказуемому поведению.

**Причины split-brain:**
- Firewall блокирует VRRP-пакеты (IP protocol 112) между узлами.
- Неверно настроен Unicast (указаны не все IP соседей).
- Различия в `virtual_router_id` между узлами.
- Сетевое разделение (Partitional network).

**Диагностика:**

```bash
# Проверка VIP на всех узлах
for node in 192.168.1.11 192.168.1.12 192.168.1.13; do
  echo "=== $node ==="
  ssh $node "ip addr show | grep -E 'inet.*vip'"
done

# Если VIP есть на более чем одном узле — split-brain

# Проверка логов Keepalived
sudo journalctl -u keepalived -n 100 | grep -E 'MASTER|BACKUP|FAULT'
```

**Решение:**
1. Проверить firewall: `sudo iptables -L -n | grep vrrp`
2. Проверить `virtual_router_id` в конфиге Keepalived на всех узлах.
3. Убедиться, что `unicast_peer` содержит IP **всех** остальных узлов.
4. Включить `nopreempt` на всех узлах для предсказуемого поведения.

### 5. Сертификаты в HA-кластере

В HA-кластере с `kubeadm` сертификаты играют критическую роль:

#### Как kubeadm управляет сертификатами

- При `kubeadm init --upload-certs` сертификаты загружаются в Secret `kubeadm-certs` в namespace `kube-system`.
- При `kubeadm join --control-plane --certificate-key <key>` другой мастер скачивает сертификаты из этого Secret.
- Ключ `certificate-key` действителен **2 часа**. После истечения необходимо сгенерировать новый: `kubeadm init phase upload-certs --upload-certs`.

#### SAN (Subject Alternative Names) для API-сервера

Сертификат API-сервера должен содержать все адреса, по которым кластер будет доступен:

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
apiServer:
  certSANs:
    - "192.168.1.100"      # VIP
    - "k8s-api.example.com" # DNS-имя VIP
    - "192.168.1.11"       # IP master1
    - "192.168.1.12"       # IP master2
    - "192.168.1.13"       # IP master3
controlPlaneEndpoint: "192.168.1.100:7443"
```

**Важно**: Если SAN не содержит IP-адреса, по которому клиент подключается, будет ошибка `x509: certificate is valid for ...`.

#### Ротация сертификатов

Сертификаты Kubernetes действительны **1 год**. Процедура ротации:

```bash
# Проверка срока действия
sudo kubeadm certs check-expiration

# Ротация всех сертификатов
sudo kubeadm certs renew all

# Перезапуск Control Plane-компонентов (они перечитают сертификаты)
sudo crictl pods --name kube-apiserver -q | xargs -I {} sudo crictl stopp {}
sudo crictl pods --name kube-controller-manager -q | xargs -I {} sudo crictl stopp {}
sudo crictl pods --name kube-scheduler -q | xargs -I {} sudo crictl stopp {}
```

Подробнее: [Управление сертификатами](../../Operations/certificate_management.md).

### 6. DNS и TTL для HA-эндпоинта

Если Control Plane Endpoint — DNS-имя (а не IP), критично правильное значение TTL:

- **Низкий TTL (5-30 секунд)**: Быстрое обновление при смене VIP. Рекомендуется для HA.
- **Высокий TTL (300+ секунд)**: Кеширование на стороне клиента. Не рекомендуется для VIP.

**Пример настройки BIND:**

```
k8s-api.example.com.  30  IN  A  192.168.1.100
```

**Проблема кеширования:**
- `kubectl` и `kubelet` резолвят DNS при запуске и кешируют результат.
- При смене VIP старый IP может использоваться до перезапуска клиента.
- **Решение**: Используйте IP-адрес (а не DNS) для `--control-plane-endpoint`, либо настройте низкий TTL и перезапускайте `kubelet` при смене VIP.

---

## Дополнительная информация

### Диагностика состояния HA

| Команда | Описание |
| :--- | :--- |
| `ip addr show \| grep -E 'inet\|vip'` | Проверка владельца VIP |
| `ss -tulpn \| grep -E '6443\|7443'` | Проверка прослушивания портов API и балансировщика |
| `journalctl -u keepalived -n 50` | Просмотр последних событий VRRP (переключения Master/Backup) |
| `echo "show stat" \| socat /var/run/haproxy.sock stdio` | Статистика HAProxy: состояние бэкендов |
| `curl -sk https://<VIP>:7443/healthz` | Проверка доступности API через VIP |
| `kubectl get endpoints -n kube-system kube-scheduler -o jsonpath='{.metadata.annotations}'` | Проверка Leader Election для scheduler/controller-manager |
| `sudo kubeadm certs check-expiration` | Проверка срока действия сертификатов |

### Мониторинг HA-компонентов

#### Метрики для Prometheus

```yaml
groups:
- name: ha_control_plane
  rules:
  # Keepalived: смена VIP
  - alert: KeepalivedVIPFailover
    expr: changes(keepalived_VRRP_state{state="MASTER"}[5m]) > 0
    for: 0m
    labels:
      severity: warning
    annotations:
      summary: "VIP переключился (Keepalived)"

  # HAProxy: бэкенд недоступен
  - alert: HAProxyBackendDown
    expr: haproxy_backend_active_servers < 2
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Менее 2 здоровых API-серверов в HAProxy"

  # API-сервер: высокий latency
  - alert: APIServerHighLatency
    expr: histogram_quantile(0.99, rate(apiserver_request_duration_seconds_bucket{verb!="WATCH"}[5m])) > 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "p99 latency API > 1 секунда"
```

#### Эндпоинты диагностики API-сервера

```bash
# Проверка здоровья API
kubectl get --raw='/livez?verbose'    # жив ли процесс
kubectl get --raw='/readyz?verbose'   # готов ли принимать запросы
kubectl get --raw='/healthz'          # общее состояние

# Проверка etcd
kubectl exec -n kube-system etcd-$(hostname) -- etcdctl endpoint health
kubectl exec -n kube-system etcd-$(hostname) -- etcdctl endpoint status -w table
```

### Типичные ошибки конфигурации

| Ошибка | Симптомы | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Конфликт virtual_router_id** | VIP поднят на нескольких узлах | Одинаковый `virtual_router_id` в разных кластерах в одной L2-сети | Уникальный ID для каждого кластера |
| **MTU mismatch** | VRRP-пакеты отбрасываются | Разный MTU на интерфейсах узлов | Выровнять MTU на всех узлах |
| **Firewall блокирует VRRP** | VIP не переключается | Заблокирован IP protocol 112 | Разрешить VRRP: `iptables -A INPUT -p vrrp -j ACCEPT` |
| **HAProxy 503** | API недоступен через VIP | Сертификаты не совпадают / порт 6443 закрыт | Проверить `check-ssl verify none` и firewall |
| **VIP flapping** | Постоянное перемещение VIP | Слишком малый `advert_int` при высокой нагрузке | Увеличить `advert_int` до 3 сек |
| **x509 certificate error** | `kubectl` не может подключиться | VIP/DNS не в SAN сертификата | Добавить все адреса в `certSANs` |
| **Split-brain** | Два узла думают, что MASTER | Multicast/Unicast настроен некорректно | Проверить `unicast_peer`, firewall |
| **token expired** | `kubeadm join` отклонён | Прошло >24 часов | `kubeadm token create --print-join-command` |

### Best Practices для production

1. **Используйте Unicast VRRP** — Multicast ненадёжен в большинстве сред.
2. **Включайте nopreempt** — предотвращает лишние переключения VIP при восстановлении узла.
3. **HTTP health checks** — используйте `/healthz` вместо TCP-check для проверки реальной готовности API.
4. **Два LB-узла минимум** — Keepalived+HAProxy должны работать на отдельных серверах (не на мастер-узлах) для полной изоляции.
5. **NVMe SSD для etcd** — задержка `fsync` должна быть < 10 мс. Проверяйте: `etcd_disk_wal_fsync_duration_seconds`.
6. **Синхронизация времени** — все узлы должны быть синхронизированы через NTP (`chronyd`). Рассинхронизация приводит к проблемам с TLS-сертификатами.
7. **Регулярные тесты failover** — проводите в staging перед релизом, фиксируйте RTO.
8. **Резервное копирование etcd** — автоматические снапшоты через CronJob + проверка восстановления.
9. **Не используйте 4 узла** — кворум при 4 узлах = кворум при 3, но дороже. Только нечётные числа: 3, 5, 7.
10. **Версионность** — версии узлов не должны отставать от Control Plane более чем на 2 минорных релиза.

### См. также

- **[Настройка Keepalived и HAProxy](./keepalived_haproxy_setup.md)** — практические конфиги и пошаговая установка.
- **[Инициализация HA кластера](./cluster_initialization.md)** — запуск `kubeadm init` с учётом HA.
- **[etcd: распределённое хранилище](../../Concepts/etcd_overview.md)** — кворум, архитектура, обслуживание.
