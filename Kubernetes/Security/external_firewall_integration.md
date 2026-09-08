# Интеграция внешних файрволов с Kubernetes

## Определения

- **Внешний файрвол (NGFW — Next-Generation Firewall)**: Аппаратное или виртуальное устройство сетевой безопасности, расположенное вне кластера Kubernetes. Обеспечивает глубокую инспекцию трафика (DPI) на уровнях L3–L7, включая IPS, Application Control и URL Filtering. Примеры: Palo Alto PA-Series, Check Point Quantum, Fortinet FortiGate, Cisco Firepower.
- **East-West трафик**: Сетевой трафик между подами внутри кластера Kubernetes. В традиционных архитектурах этот трафик не проходит через внешние файрволы, что создает слепую зону для аудита.
- **North-South трафик**: Трафик между кластером и внешними сетями (интернет, корпоративный ЦОД). Это наиболее часто фильтрируемый тип трафика.
- **UDR (User Defined Routes)**: Пользовательские правила маршрутизации в виртуальных сетях (Azure VNet, AWS VPC), позволяющие перенаправлять трафик через шлюзы безопасности (NGFW). Аналог статических маршрутов в физических сетях.
- **Identity Awareness**: Механизм идентификации рабочих нагрузок (подов) по метаданным Kubernetes (метки, namespace), позволяющий применять политики безопасности на уровне логических объектов, а не динамических IP-адресов. Синхронизация объектов осуществляется через Kubernetes API или Service Account Token.
- **Egress Gateway**: Паттерн проектирования (реализуемый через Cilium или Istio), при котором весь исходящий трафик определенных подов направляется через выделенный узел с фиксированным IP-адресом для упрощения фильтрации на внешнем файрволе.
- **FQDN Filtering / SNI Inspection**: Фильтрация трафика на основе доменных имен (через Server Name Indication в TLS), позволяющая ограничивать доступ к внешним ресурсам без полной расшифровки трафика.
- **Asymmetric Routing**: Ситуация, когда запрос и ответ проходят через разные сетевые устройства. Приводит к сбросу stateful-сессий на файрволе, так как он не видит обе стороны соединения.

---

## Основные концепции

### Архитектура интеграции

В корпоративных средах с высокими требованиями к безопасности (PCI DSS, HIPAA) Kubernetes-кластеры часто развертываются в приватном режиме. Весь трафик проходит через NGFW для инспекции и предотвращения эксфильтрации данных.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Приватный кластер (VPC/VNet)                     │
│  ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐   │
│  │    NodePool 1    │      │    NodePool 2    │      │    NodePool 3    │   │
│  │   (Frontend)     │      │    (Backend)     │      │    (Database)    │   │
│  │   10.4.1.0/24    │      │    10.4.2.0/24   │      │    10.4.3.0/24   │   │
│  └────────┬─────────┘      └────────┬─────────┘      └────────┬─────────┘   │
│           │                         │                         │             │
│           └─────────────────────────┼─────────────────────────┘             │
│                                     │                                       │
│                              ┌──────▼──────┐                                │
│                              │   CNI / L2  │                                │
│                              │ (Native/eBPF)                                │
│                              └──────┬──────┘                                │
└─────────────────────────────────────┼───────────────────────────────────────┘
                                      │
               ┌──────────────────────▼──────────────────────┐
               │         Слой маршрутизации (UDR / BGP)      │ ◄── Интеграция с
               │   Направление трафика 0.0.0.0/0 на NGFW     │     Cloud Fabric
               └──────────────────────┬──────────────────────┘
                                      │
                               ┌──────▼──────┐
                               │  NGFW / IPS │ ◄── Интеграция с K8s API
                               │  (L3 - L7)  │     (Identity Awareness)
                               └──────┬──────┘
                                      │
             ┌────────────────────────┼────────────────────────┐
             │                        │                        │
      ┌──────▼──────┐          ┌──────▼──────┐          ┌──────▼──────┐
      │   Интернет  │          │ Внутренняя  │          │    SaaS /   │
      │ (Egress Filter)        │    сеть     │          │ External API│
      └─────────────┘          └─────────────┘          └─────────────┘
```

### Уровни инспекции трафика

| Уровень | Описание | Когда использовать |
|---------|----------|-------------------|
| **Только North-South** | Через NGFW проходит только входящий/исходящий трафик из внешних сетей. | Базовая защита периметра и контроль Egress-трафика. |
| **Зональная сегментация** | Трафик между разными NodePool (например, Frontend ↔ Backend) проходит через NGFW. | Разделение сред по уровням доверия. |
| **Полный East-West** | Весь трафик между подами инспектируется на внешнем устройстве. | Максимальные требования к безопасности (Zero Trust), аудит всех связей. |

### Режимы работы CNI и видимость IP-адресов

Для корректной инспекции на NGFW пакеты должны приходить с **родных IP-адресов подов**.

#### Проблема NAT и Masquerade
По умолчанию многие CNI (Calico, Flannel) используют NAT для исходящего трафика, подменяя IP пода на IP ноды. Это делает невозможным точечную настройку политик на файрволе.

#### Решение: Отключение NAT
1. **Calico**: Требуется настройка `natOutgoing: false` в ресурсе `IPPool`.
   ```bash
   # Отключить NAT для основного пула адресов
   kubectl patch ippool default-ipv4-ippool \
     --type merge \
     --patch '{"spec":{"natOutgoing":false}}'
   ```
   *Примечание:* Это требует, чтобы внешняя сеть знала маршруты до Pod CIDR (через BGP или статические маршруты на роутерах).

2. **Azure CNI Overlay / AWS VPC CNI**:
   - Поды получают IP из адресного пространства VPC/VNet.
   - Маршрутизация осуществляется на уровне облачной инфраструктуры.
   - NAT не требуется, IP подов прозрачны для Azure Firewall / AWS Network Firewall.

3. **Cilium Egress Gateway**:
   - Позволяет перенаправлять трафик от специфических подов на выделенный узел-шлюз.
   - Обеспечивает стабильный Source IP для внешних систем, которым нужен белый список (Whitelisting).

### Identity Awareness и динамические политики

Современные NGFW (Check Point, Palo Alto, Fortinet) поддерживают прямую интеграцию с Kubernetes API.

1. **Синхронизация объектов**: Файрвол подключается к API-серверу и считывает список подов, их IP и метки (`labels`).
2. **Динамические правила**: Вместо IP-адресов в правилах используются объекты Kubernetes.
   ```
   Правило: Source [label: app=payments] -> Destination [FQDN: api.stripe.com] -> Action: Allow
   ```
3. **Ограничения**:
   - Задержка синхронизации (от нескольких секунд до минуты).
   - Не подходит для короткоживущих подов (Job, CronJob).

---

## Практические сценарии

### Сценарий 1: Инспекция только интернет-трафика (North-South)

**Конфигурация UDR:**
- Маршрут по умолчанию (`0.0.0.0/0`) направляется на внутренний IP NGFW.
- Локальная маршрутизация кластера (`10.4.0.0/16`) остается прямой.

**Результат:** NGFW выполняет роль шлюза, проверяя исходящие запросы к API и загрузку обновлений на наличие вредоносного ПО.

### Сценарий 2: Инспекция между зонами безопасности (Inter-NodePool)

**Конфигурация:**
- Разные группы узлов (NodePool) выносятся в отдельные подсети (Subnets).
- В таблице маршрутизации (Route Table) подсети Frontend прописывается маршрут к подсети Backend через NGFW.

**Использование:** Детекция lateral movement при компрометации публичного сервиса и глубокая инспекция L7-протоколов (например, SQL IPS-профили для защиты БД).

### Сценарий 3: Полная инспекция East-West через внешний NGFW

**Требования:**
- Высокая пропускная способность NGFW (инспекция 10-100 Гбит/с).
- Задержка (latency) инспекции менее 1 мс.
- Отключение NAT на уровне CNI.

**Использование:** Строгий комплаенс, где требуется журналирование каждого сетевого соединения на внешнем сертифицированном устройстве.

### Сценарий 4: Контроль FQDN/SNI без дешифрации TLS

Использование NGFW для ограничения доступа подов только к разрешенным внешним доменам.
- Файрвол анализирует поле SNI в пакете TLS Client Hello.
- Если домен не в белом списке, соединение сбрасывается (TCP Reset).
- Не требует установки корневых сертификатов (CA) в поды, так как не выполняется полная расшифровка трафика.

### Сценарий 5: Контроль East-West трафика через Calico BGP + NGFW

Когда NGFW поддерживает BGP-ансамблирование, можно настроить динамическую маршрутизацию Pod CIDR через Calico Bird:

```yaml
# BGP Peer Configuration (Calico)
apiVersion: projectcalico.org/v3
kind: BGPConfiguration
metadata:
  name: default
spec:
  logSeverityScreen: Info
  nodeToNodeMeshEnabled: true
  asNumber: 65100
---
apiVersion: projectcalico.org/v3
kind: BGPPeer
metadata:
  name: ngfw-peer
spec:
  peerIP: 10.0.1.100    # IP интерфейса NGFW
  asNumber: 65200        # ASN файрвола
  nodeSelector: all()
---
apiVersion: projectcalico.org/v3
kind: IPPool
metadata:
  name: pod-cidr-pool
spec:
  cidr: 10.244.0.0/16
  natOutgoing: false      # Отключаем NAT для прозрачности IP подов
  disabled: false
  nodeSelector: all()
```

```bash
# Проверка BGP-пиров
calicoctl get bgppeer
# → NAME         PEER IP      NODE SELECTOR   AS NUMBER
# → ngfw-peer    10.0.1.100   all()           65200

# Проверка маршрутов на узле
ip route | grep bird
# → 10.244.1.0/26 via 10.0.1.100 dev eth0 proto bird
# → 10.244.2.0/26 via 10.0.1.100 dev eth0 proto bird

# Проверка BGP-сессий
sudo birdc show protocols
# → BGP4:    up    10.0.1.100  master   Established
```

### Сценарий 6: Настройка UDR для перенаправления трафика через NGFW (iptables)

Для кластеров на裸-metal или в гипервизоре, где облачные UDR недоступны, маршрутизация через NGFW реализуется через статические маршруты или iptables:

```bash
# Включение IP forwarding на маршрутизаторе/ноде
sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.d/99-forward.conf

# Статический маршрут: весь трафик из Pod CIDR -> через NGFW
ip route add 10.244.0.0/16 via 10.0.1.100 dev eth0

# Альтернатива: iptables MARK + policy routing
# Помечаем пакеты от определенных подов
iptables -t mangle -A PREROUTING -s 10.244.1.0/24 -j MARK --set-mark 0x1

# Добавляем таблицу маршрутизации
echo "100 ngfw_route" >> /etc/iproute2/rt_tables

# Правило маршрутизации для помеченных пакетов
ip rule add fwmark 0x1 lookup ngfw_route
ip route add default via 10.0.1.100 dev eth0 table ngfw_route
```

**Проверка:**
```bash
# Проверка правил iptables
iptables -t mangle -L PREROUTING -v -n | grep MARK
# → pkts bytes target   prot opt in     out     source          destination
# →   12  1020 MARK       all  --  *      *       10.244.1.0/24   0.0.0.0/0   MARK set 0x1

# Проверка таблицы маршрутизации
ip route show table ngfw_route
# → default via 10.0.1.100 dev eth0
```

---

## Дополнительная информация

### Требования к NGFW для Kubernetes

| Функция | Описание |
|---------|----------|
| **Kubernetes API Integration** | Автоматический импорт Pod, Namespace, Label как объектов безопасности. |
| **Identity Awareness** | Динамическое применение политик на основе метаданных. |
| **FQDN/SNI Filtering** | Контроль доступа к доменам на уровне L7. |
| **IPS & Anti-Malware** | Обнаружение вторжений и сканирование файлов в трафике. |
| **BGP Support** | Возможность динамического получения маршрутов от CNI (например, Calico). |
| **TLS Inspection** | Полная дешифровка и инспекция HTTPS-трафика (с установкой корневого CA). |
| **HA (Active/Passive, Active/Active)** | Работа в кластере для отказоустойчивости. |

### Интеграция с конкретными NGFW

#### Palo Alto Panorama / PAN-OS
- **Плагин Kubernetes**: Palo Alto提供ит официальный плагин для Panorama, который синхронизирует Namespace, Pod и Label как Dynamic Address Groups.
- **Dynamic Address Groups**: Адресные группы обновляются в реальном времени при создании/удалении подов.
- **Статус panorama-kubernetes-plugin**: `show plugins` на Panorama.

#### Check Point SmartConsole
- **CloudGuard**: Решение Check Point для Kubernetes, обеспечивающее Identity Awareness и автоматическое обновление Security Groups при изменении Pod.
- **R81.20+**: Нативная поддержка Kubernetes API для динамических объектов.

#### Fortinet FortiGate
- **FortiGate- Kubernetes Integration**: API FortiGate для создания Address и Address Groups на основе Pod IP/Labels.
- **FortiGate REST API**: `POST /api/v2/cmdb/firewall/address` для создания объектов.
- **Синхронизация**: FortiGate-Fabric Connector для автоматического обновления объектов.

### Диагностика и устранение неисправностей

```bash
# 1. Проверка маршрутов: идет ли трафик через NGFW
traceroute -n 10.244.1.50          # С узла кластера
# → Должен показать hop через IP NGFW (10.0.1.100)

# 2. Проверка BGP-сессий (Calico)
calicoctl get bgppeer
sudo birdc show protocols
sudo birdc show routes

# 3. Проверка, что NAT отключен
kubectl get ippool -o yaml | grep natOutgoing
# → natOutgoing: false

# 4. Проверка SIP/Non-SIP трафика на NGFW
# На NGFW: monitor traffic
# Или через tcpdump на промежуточном узле:
tcpdump -i eth0 host 10.244.1.50 -nn -c 20

# 5. Проверка DNS-резолвинга (для FQDN-политик)
kubectl exec <pod> -- nslookup api.stripe.com
# → Должен резолвиться, но NGFW может блокировать по FQDN

# 6. Проверка ACL на NGFW (Palo Alto example)
# show running rule security
# Или через API:
curl -k -X GET "https://<panorama>/api/?type=config&xpath=/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/rulebase/security/rules" -H "X-PAN-KEY: <api-key>"
```

#### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Трафик не идет через NGFW** | Неправильная маршрутизация или NAT включен | Проверьте `ip route` на узлах. Убедитесь, что `natOutgoing: false` в IPPool. |
| **Сессия сбрасывается (stateful firewall)** | Асимметричная маршрутизация | Убедитесь, что и запрос, и ответ проходят через один NGFW. Проверьте `conntrack -S`. |
| **NGFW не видит Pod IP** | NAT в CNI или Masquerade | Отключите NAT. Проверьте `iptables -t nat -L POSTROUTING` на узлах. |
| **Identity Awareness не работает** | NGFW не может подключиться к K8s API | Проверьте SA-токен и RBAC. Убедитесь, что API-сервер доступен с NGFW. |
| **FQDN-политика не блокирует** | DNS-запросы обходят NGFW (DNS через 8.8.8.8) | Убедитесь, что DNS-трафик тоже маршрутизируется через NGFW. |
| **Высокая задержка (latency)** | Инспекция TLS на NGFW | Рассмотрите TLS Bypass для доверенных доменов или использование eBPF для L7-инспекции. |

### High Availability (HA)

Для production-сред NGFW должен работать в кластере:

**Active/Passive (HA Proxy):**
- Основной NGFW обрабатывает весь трафик.
- Резервный NGFW находится в режиме standby.
- При отказе Primary, Backup берет VIP (Virtual IP) и продолжает обработку.
- Время переключения: обычно 3–10 секунд (зависит от состояния сессий).

**Active/Active (ECMP):**
- Оба NGFW обрабатывают трафик параллельно.
- Трафик балансируется через ECMP (Equal-Cost Multi-Path) или DNS Round Robin.
- Требует синхронизации состояния сессий (session sync).
- Выше пропускная способность, но сложнее в настройке.

**Рекомендации:**
- Используйте VRRP (Virtual Router Redundancy Protocol) или HSRP для организации виртуального IP.
- Настройте синхронизация состояния (session table) между Primary и Backup.
- Тестируйте failover регулярно: `shutdown` интерфейса Primary и проверка непрерывности трафика.

### TLS Inspection (SSL Decrypt)

Для глубокой инспекции HTTPS-трафика NGFW должен выполнять TLS termination:

1. **Генерация Root CA**: NGFW генерирует собственный корневой сертификат.
2. **MITM (Man-in-the-Middle)**: При HTTPS-соединении NGFW подменяет сертификат сервера на свой, подписанном Root CA.
3. **Инспекция**: Расшифрованный трафик проверяется на malware, DLP, IPS.
4. **Re-encrypt**: Трафик заново шифруется и передается в под.

**Важно:**
- Требуется установка Root CA во все узлы/поды для предотвращения ошибок TLS.
- Используйте `trust-distribution` DaemonSet для автоматической установки CA в ConfigMap.
- Не выполнять TLS inspection для доверенных сервисов (внутренние API, базы данных).

### Мониторинг и метрики

```bash
# Метрики NGFW для Prometheus (пример для FortiGate)
# FortiGate exporter: https://github.com/bluecmd/fortigate_exporter

# Метрики Calico для проверки маршрутизации
calicoctl node status
# → IPv4 BGP status
# → +--------+-------------------+-------+----------+-------------+
# │ PEER   │     STATE/SINCE   │ AS    │ HOLES    │ ADDR/IFACE  │
# +--------+-------------------+-------+----------+-------------+
# │ 10.0.1.100  established  1h30m  65200   0        10.0.1.100/eth0│
# +--------+-------------------+-------+----------+-------------+

# Проверка количества сессий на NGFW
# Palo Alto: show session info
# FortiGate: get system performance | grep session
# Check Point: fw stat

# Логирование заблокированных пакетов
# Palo Alto: configure -> set rulebase security rules <rule> log-start yes log-end yes
# FortiGate: set logtraffic all
```

### Ограничения и рекомендации

1. **Асимметричная маршрутизация**: Убедитесь, что обратный трафик возвращается через тот же файрвол, иначе сессия будет сброшена. Используйте `conntrack` для мониторинга: `conntrack -E -e NEW`.
2. **Производительность**: East-West инспекция на внешнем NGFW — это дорогостоящая операция по ресурсам и задержкам. Рассмотрите использование [Cilium с eBPF](../../Kubernetes/Networking/Network/CNI/cilium.md) для частичной разгрузки L7-инспекции.
3. **NAT**: Всегда стремитесь к отключению NAT для обеспечения "прозрачности" сетевого стека для систем аудита.
4. **Зацикливание**: Не направляйте трафик к API-серверу Kubernetes через NGFW, если файрвол использует этот же API для синхронизации объектов (риск взаимной блокировки). Используйте выделенный интерфейс для управления.
5. **Масштабирование**: При масштабировании кластера (добавлении узлов) убедитесь, что NGFW автоматически обновляет маршруты (BGP) или вы вручную добавляете маршруты для новых Pod CIDR.
6. **Тестирование**: Перед развертыванием в production протестируйте NGFW в режиме tap/monitor (без блокировки), чтобы убедиться, что правила не блокируют легитимный трафик.

### См. также
- [Сетевые политики Kubernetes (NetworkPolicy)](../../Kubernetes/Networking/Network/network_policy.md) — микросегментация внутри кластера.
- [Calico HostEndpoint и GlobalNetworkPolicy](../../Kubernetes/Security/network_policies/Calico/index.md) — защита самих узлов кластера.
- [CNI и kube-proxy: роли](../../Kubernetes/Networking/Network/cni_kube_proxy_roles.md) — как работает сетевой стек.
- [Концепции сетевых файрволов](../../Networking/Concepts/firewall_concepts.md) — база по L3-L7 фильтрации.
- [Сегментация и микросегментация](../../Networking/Concepts/network_segmentation_and_microsegmentation.md) — общие принципы дизайна защищенных сетей.
- [Cilium: Egress Gateway](../../Kubernetes/Networking/Network/CNI/cilium.md#egress-gateway) — детальная настройка шлюзов.
