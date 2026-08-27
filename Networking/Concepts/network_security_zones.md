# Сетевые зоны безопасности

## Определения

- **Зона безопасности (Security Zone):** Логический сегмент сети, объединяющий ресурсы с идентичными требованиями к безопасности и уровнем доверия. Границы зон определяются правилами на межсетевых экранах (МСЭ) или механизмами микросегментации.
- **Радиус поражения (Blast Radius):** Область потенциального ущерба при компрометации одного узла внутри зоны. Зонирование направлено на минимизацию этого радиуса путем изоляции критичных активов.
- **Уровень доверия (Trust Level):** Относительный показатель «чистоты» трафика. Традиционно: Интернет (0), DMZ (50), Внутренняя сеть (100). В современной модели [Zero Trust](./zero_trust_overview.md) уровень доверия к любой зоне по умолчанию равен нулю.
- **North-South трафик:** Трафик, входящий в сеть или покидающий ее (например, клиент -> веб-сервер). Традиционные МСЭ ориентированы на контроль этого направления.
- **East-West трафик:** Трафик между ресурсами внутри одного периметра (например, App -> DB). Рост этого трафика в микросервисных архитектурах требует перехода к [микросегментации](./network_segmentation_and_microsegmentation.md).
- **Контур безопасности (Security Perimeter):** Совокупность граничных контрольных точек (firewall, router, proxy), отделяющих одну зону от другой. В классической модели — это единый внешний рубеж («замок и ров»); в модели Zero Trust периметр распределяется до каждой рабочей нагрузки.
- **Граница зоны (Zone Boundary):** Точка принудительного применения политик (enforcement point), через которую весь трафик между зонами обязан проходить. Граница может быть физической (отдельный интерфейс/VLAN на МСЭ), виртуальной (VRF, VXLAN VNI) или программной (host firewall, eBPF, sidecar Service Mesh).
- **Default-deny (Запрет по умолчанию):** Базовый принцип зонирования: любое межзонное взаимодействие запрещено, пока не разрешено явным правилом. Это отличает зону от простой маршрутизируемой подсети, где трафик между сегментами разрешён по умолчанию.
- **Зонный шлюз (Zone Gateway):** Устройство/инстанс, терминирующее маршрутизацию между зонами и выполняющее фильтрацию (например, SVI на L3-коммутаторе с ACL, firewall context, cloud NAT/transit gateway). Все межзонные потоки должны проходить через него, иначе зона «протекает» (bypass).

## Базовые концепции

### Эволюция периметра: от DMZ к Zero Trust
Традиционная модель строится на защите периметра («Замок и ров»). Однако современная безопасность опирается на принцип **Assume Breach** (предположение о взломе): внутренняя сеть не считается безопасной, а зоны используются для ограничения «бокового перемещения» (Lateral Movement) злоумышленника. Переход к [Zero Trust](./zero_trust_overview.md) не отменяет зонирование, а делает границы более дробными и контекстно-зависимыми: вместо «внутренняя сеть = доверенная» каждая зона проверяет идентичность и состояние субъекта при каждом обращении.

### Типы стандартных зон

1.  **Публичная зона (Untrusted/Internet):** Весь внешний мир. Источник большинства атак. Уровень доверия — 0.
2.  **Демилитаризованная зона (DMZ):** Буфер между Интернетом и внутренними ресурсами. Здесь размещаются публичные сервисы:
    - Веб-серверы и WAF.
    - Reverse Proxy / Load Balancers.
    - Внешние почтовые реле (MTA).
    - Jump-хосты (Bastion).
3.  **Внутренняя зона (Trusted/Internal):** Сегменты для офисных пользователей, серверов приложений и БД. Часто разделяется на подзоны `Users`, `Apps` и `Data`.
4.  **Зона управления (Management/OOB):** Изолированная сеть Out-of-Band для доступа к IPMI/iDRAC, консолям управления и SSH оборудования.
5.  **Гостевая и карантинная зона (Guest/Quarantine):** Сегмент с минимальными привилегиями для посетителей и непроверенных устройств. Карантинная подзона (NAC post-auth remediation) используется для устройств, не прошедших аудит безопасности, — им доступен только сервер обновлений/проверки.
6.  **Зона хранения и резервного копирования (Storage/Backup):** Изолированный сегмент для СХД, реплик и бэкапов. Доступ односторонний (резервное ПО пишет в зону, восстановление — только с выделенного административного хоста), что защищает бэкапы от шифровальщиков (ransomware) при компрометации продуктива.
7.  **Зона IoT/OT-устройств:** Камеры, датчики, контроллеры с ограниченной поддержкой шифрования. Требуют отдельной зоны из-за слабой собственной защиты и высокого риска быть «входной точкой» (вектор атаки на корпоративную сеть).

### Модель Purdue (для промышленных систем / OT)
В сетях АСУ ТП применяется иерархическое зонирование для защиты техпроцессов:
- **Level 0-1:** Датчики, исполнительные механизмы и контроллеры (PLC).
- **Level 2:** Локальные консоли операторов (HMI).
- **Level 3:** Управление производственной площадкой (MES).
- **IDMZ (Industrial DMZ):** Критически важный барьер между OT и корпоративной IT-сетью. В отличие от IT-DMZ здесь запрещён прямой IP-поток: используются проксирование на уровне приложений (OPC UA broker, data diode) и строго односторонняя передача данных из OT в IT.

### Зонирование в IPv6
В отличие от IPv4 с NAT, в IPv6 каждый хост имеет глобальный адрес, что меняет подход к зонам:
- **GUA (Global Unicast):** Требуют обязательной фильтрации `Stateful Firewall` на границе зоны.
- **ULA (Unique Local):** Используются для внутренней изоляции, аналогично RFC 1918.
- **L2 Security:** Зонирование должно учитывать механизмы RA Guard и DHCPv6 Guard для предотвращения подмены шлюзов внутри сегмента. Дополнительно в IPv6 нет понятия broadcast (вместо него используется multicast и ICMPv6 Neighbor Discovery), поэтому фильтрация на границе зоны должна разрешать служебный ICMPv6 (types 133–137, Packet Too Big, Time Exceeded), иначе зона перестанет работать.

### Сравнение моделей зонирования

| Параметр | Традиционное зонирование | Микросегментация / Zero Trust |
| :--- | :--- | :--- |
| **Основа** | IP-адреса и VLAN | Идентичность (Identity), Контекст |
| **Гранулярность** | Уровень подсети/сегмента | Уровень процесса/контейнера/пода |
| **Трафик** | Фокус на North-South (вход/выход) | Фокус на East-West (внутри ЦОД) |
| **Динамичность** | Статичные правила | Динамические политики (eBPF, Service Mesh) |

### Способы реализации границ зон
Выбор точки применения политик (enforcement point) определяет надёжность зоны. Типовые варианты:

- **L2-изоляция:** Private VLAN (PVLAN), port isolation, MAC-фильтрация. Блокирует прямой L2-обмен внутри сегмента (защита от ARP-spoofing, локального сканирования). Детали сегментации на [VLAN](./vlan_l2_switching/vlan_design_patterns.md).
- **L3-фильтрация:** МСЭ/NGFW между подсетями, VRF (виртуальные маршрутные таблицы — изоляция на уровне маршрутизации без общего L3-домена), VXLAN с firewall в overlay.
- **Облачные примитивы:** VPC + Security Groups (stateful, уровень инстанса) + Network ACL (stateless, уровень подсети). Подробнее в [облачной сети](./cloud_networking.md).
- **Хостовый firewall:** firewalld/nftables/iptables на самом узле — последний рубеж, работает даже при обходе сетевого МСЭ.
- **Service Mesh / eBPF:** Микросегментация на L7 с mTLS и контекстом идентичности; зона определяется не IP, а сервисной идентичностью (SPIFFE). См. [микросегментацию](./network_segmentation_and_microsegmentation.md) и [Service Mesh](../../Service_Mesh/service_mesh_concepts.md).

Критически важно: зона считается изолированной только если **все** пути между зонами проходят через enforcement point. Альтернативные маршруты (второй NIC, direct L2, общий L2-домен, NAT bypass) превращают зону в иллюзорную.

### Зоны в контейнерах и Kubernetes
В Kubernetes физическая сеть прозрачна для планировщика, поэтому зона реализуется логически:

- **Namespace как логическая зона:** метка/пространство имён группирует рабочие нагрузки с общим уровнем доверия (например, `zone: cde`, `zone: bastion`).
- **NetworkPolicy** задаёт default-deny и явные разрешения между зонами (аналог межзонного МСЭ на уровне подов). Без CNI, поддерживающего NetworkPolicy (Calico, Cilium), политики не применяются — это частая ошибка «тихой» неизоляции.
- **Service Mesh (Istio/Linkerd)** добавляет mTLS и L7-контроль поверх зон, превращая зонирование в identity-based.

Практический сценарий изоляции зон в K8s — ниже; детальные примеры политик — в [NetworkPolicy: практика](../../Kubernetes/Networking/Network/NetworkPolicy/practical_scenarios.md).

### Комплаенс-зоны (регуляторные требования)
Помимо технической изоляции зоны часто диктуются стандартами:

- **PCI DSS (CDE):** зона данных держателей карт — жёсткая изоляция, MFA, белый список egress (см. сценарий ниже).
- **HIPAA / персональные данные:** выделенная зона PHI с шифрованием покоя/в движении и аудитом доступа.
- **Критическая информационная инфраструктура (КИИ):** сегментация значимых объектов, запрет прямого доступа из публичных сетей, отдельный контур управления.

## Практические сценарии

> **Общие предварительные требования для сценариев ниже:** определена схема адресации зон, выбрана точка применения политик (МСЭ/облако/host), составлена матрица межзонного доступа (кто → кому → порт → разрешено/запрещено). Без матрицы зонирование превращается в хаотичный набор правил.

### Реализация DMZ с двумя файрволами («Sandwich»)

Наиболее надежная схема, где выход из строя или взлом одного МСЭ не открывает доступ к внутренней сети:
- **Внешний МСЭ:** Пропускает только 80/443 порты из Интернета к балансировщику в DMZ.
- **Внутренний МСЭ:** Пропускает трафик только от балансировщика в DMZ к серверам приложений во внутренней сети по специфичным портам (например, 8080). Доступ к БД из DMZ запрещен напрямую.

**Предварительные требования:** два независимых МСЭ (разные вендоры желательны — снижает риск общей уязвимости), три L3-сегмента: `Internet`, `DMZ (10.10.200.0/26)`, `Internal (10.10.0.0/24)`.

**Пример правила на внутреннем МСЭ (концепт, iptables/nftables-подобно):**
```bash
# Разрешить только от балансировщика DMZ к App по 8080
rule add src=10.10.200.10 dst=10.10.10.0/24 dport=8080 action=allow
# Явно запретить DMZ -> DB
rule add src=10.10.200.0/26 dst=10.10.20.0/24 action=deny log=yes
# Всё остальное межзонное — deny
rule add action=deny
```

**Валидация (проверка матрицы доступа):**
```bash
# С DMZ-хоста должен работать только нужный порт во внутренней сети
nc -zv 10.10.10.5 8080
# → result: Connection to 10.10.10.5 8080 port [tcp/*] succeeded!

# Прямой доступ DMZ -> DB (10.10.20.5:5432) должен быть заблокирован
nc -zv 10.10.20.5 5432
# → result: nc: connect to 10.10.20.5 port 5432 (tcp) failed: Connection timed out
```

**Устранение неполадок:** если доступ к БД из DMZ «вдруг» появился — проверьте, не появился ли альтернативный маршрут (второй NIC на сервере, общий L2, статический маршрут в обход МСЭ). Зонирование нарушается при любом bypass.

### Облачное зонирование (VPC и Security Groups)

В облаках (AWS, Azure, Yandex Cloud) зоны реализуются через:
- **VPC (Virtual Private Cloud):** Полная логическая изоляция сети.
- **Subnets (Public/Private):** Публичные подсети имеют маршрут в Internet Gateway, приватные — нет.
- **Security Groups (SG):** Микро-файрволы на уровне каждого инстанса. Позволяют реализовать зоны на уровне ролей (например, группа `web` может обращаться к группе `db` по порту 5432).

**Предварительные требования:** аккаунт облака, CLI настроен (`aws configure` / `yc init`), выбран регион.

**Пример создания зон через AWS CLI:**
```bash
# VPC и публичная/приватная подсети
aws ec2 create-vpc --cidr-block 10.0.0.0/16 --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=prod}]'
# → result: { "Vpc": { "VpcId": "vpc-0abc123", "CidrBlock": "10.0.0.0/16", ... } }

aws ec2 create-subnet --vpc-id vpc-0abc123 --cidr-block 10.0.1.0/24 --availability-zone ru-central1-a

# Зона web и разрешение только 443 снаружи
aws ec2 create-security-group --group-name web --description "web zone" --vpc-id vpc-0abc123
# → result: { "GroupId": "sg-0web123" }
aws ec2 authorize-security-group-ingress --group-id sg-0web123 --protocol tcp --port 443 --cidr 0.0.0.0/0

# Зона db — доступ only от группы backend по 5432 (stateful, return-трафик разрешён автоматически)
aws ec2 authorize-security-group-ingress --group-id sg-0db123 --protocol tcp --port 5432 --source-group sg-0backend123
```

**Валидация:**
```bash
aws ec2 describe-security-groups --group-ids sg-0db123
# → result: ... "IpPermissions": [{ "FromPort": 5432, "ToPort": 5432,
#   "UserIdGroupPairs": [{ "GroupId": "sg-0backend123" }] }] ...

# Проверка достижимости между зонами (VPC Reachability Analyzer / AWS)
# → result: "Status": "REACHABLE" для web->backend, "UNREACHABLE" для internet->db
```

**Устранение неполадок:** если инстанс в приватной подсети недостижим извне по разрешённому порту — проверьте (1) привязку SG к сетевому интерфейсу инстанса, (2) Route Table подсети, (3) Network ACL (stateless — требует разрешения return-трафика по ephemeral ports, в отличие от SG).

### Управление зонами в Linux (Firewalld)

Firewalld реализует концепцию зон на уровне ОС. Интерфейс или Source IP привязывается к зоне, которая определяет политику.

```bash
# Просмотр активных зон и привязанных интерфейсов
firewall-cmd --get-active-zones
# → result: 
# public
#   interfaces: eth0
# trusted
#   interfaces: eth1

# Перенос интерфейса в зону DMZ
sudo firewall-cmd --zone=dmz --change-interface=eth0 --permanent
sudo firewall-cmd --reload

# Проверка разрешенных сервисов в зоне
firewall-cmd --zone=dmz --list-services
# → result: ssh http https
```

**Расширенный пример — кастомная зона Management с rich-правилами:**
```bash
# Создать зону management (target DROP по умолчанию)
sudo firewall-cmd --permanent --new-zone=management
sudo firewall-cmd --permanent --zone=management --set-target=DROP
# Разрешить SSH только с подсети админов и логировать отказы
sudo firewall-cmd --permanent --zone=management --add-source=10.0.99.0/24
sudo firewall-cmd --permanent --zone=management --add-rich-rule='rule family=ipv4 source address=10.0.99.0/24 service name=ssh accept'
sudo firewall-cmd --permanent --zone=management --add-rich-rule='rule family=ipv4 service name=ssh log prefix="ssh-deny: " reject'
sudo firewall-cmd --reload
```

**Валидация:**
```bash
sudo firewall-cmd --info-zone=management
# → result: management (active)
#   target: DROP
#   sources: 10.0.99.0/24
#   rich rules: rule family="ipv4" source address="10.0.99.0/24" service name="ssh" accept ...
firewall-cmd --get-active-zones
# → result: management
#   sources: 10.0.99.0/24
```

**Устранение неполадок:**
- Правило не применилось после перезагрузки — проверьте, что оно добавлено с `--permanent`; runtime и permanent конфигурации независимы.
- SSH-локаут после смены зоны — сначала добавьте rich-правило разрешения в новой сессии до `--reload`, или оставьте консольный доступ через IPMI.
- `set-target=DROP` блокирует ВЕСЬ трафик зоны, кроме явных разрешений, включая уже установленные соединения — будьте осторожны на live-системе.

### Изоляция управления (Management Network)

Для серверов в стойке или критичных ВМ:
1. Выделяется отдельный VLAN (например, VLAN 99).
2. На сервере SSH биндится только на IP из этого VLAN (директива `ListenAddress` в `sshd_config`).
3. На МСЭ создается зона `MGMT`, доступ в которую разрешен только с VPN-шлюза администраторов.

**Валидация биндинга SSH:**
```bash
grep -n "^ListenAddress" /etc/ssh/sshd_config
# → result: ListenAddress 10.0.99.10
ss -tlnp | grep ':22'
# → result: LISTEN 0 128 10.0.99.10:22 ... users:(("sshd",pid=...))
# Попытка зайти по публичному IP должна быть отклонена на уровне connect
nc -zv <public-ip> 22
# → result: failed: Connection refused (порт не слушается на этом интерфейсе)
```

**Edge case:** если сервер — это ВМ на гипервизоре, управление гипервизором (KVM/IPMI) тоже должно быть в OOB-зоне; иначе компрометация хоста даёт контроль над всеми ВМ независимо от их зон.

### Зона данных держателей карт (CDE) — PCI DSS

Специализированная зона с жестким комплаенсом:
- Весь сетевой сегмент, где передаются или хранятся данные карт, должен быть строго изолирован.
- Доступ разрешается только через Jump-хосты с обязательной двухфакторной аутентификацией (MFA).
- Любой Egress-трафик (исходящий) должен быть ограничен белым списком доменов.

**Пример ограничения egress (firewalld, зона cde с target DROP + белый список):**
```bash
sudo firewall-cmd --permanent --new-zone=cde
sudo firewall-cmd --permanent --zone=cde --set-target=DROP
# Разрешить только DNS и HTTPS к проверенным endpoints процессинга
sudo firewall-cmd --permanent --zone=cde --add-rich-rule='rule family=ipv4 service name=dns accept'
sudo firewall-cmd --permanent --zone=cde --add-rich-rule='rule family=ipv4 destination address=198.51.100.0/24 service name=https accept'
sudo firewall-cmd --reload
```

**Валидация (egress заблокирован по умолчанию):**
```bash
curl -sS -m 5 https://example.com
# → result: curl: (28) Failed to connect to example.com port 443 after 5000 ms: Timeout
# (не в белом списке — заблокировано)
```

### Изоляция зон в Kubernetes (Namespace как зона)

Логическая зона `payments` (CDE-аналог) с политикой default-deny и явным разрешением только от зоны `bastion`.

**Предварительные требования:** кластер с CNI, поддерживающим NetworkPolicy (Calico/Cilium), `kubectl` настроен. Без поддерживающего CNI политики игнорируются.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: payments
  labels:
    zone: cde
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: payments
spec:
  podSelector: {}            # применяется ко всем подам зоны
  policyTypes: ["Ingress", "Egress"]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-bastion
  namespace: payments
spec:
  podSelector: {}
  policyTypes: ["Ingress"]
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          zone: bastion     # разрешён только вход из зоны bastion
```

**Валидация:**
```bash
kubectl get networkpolicy -n payments
# → result: NAME             POD-SELECTOR   AGE
#          default-deny      <none>         2m
#          allow-from-bastion <none>        2m

# Попытка доступа из постороннего namespace должна быть отклонена
kubectl run test -n default --rm -i --tty --image=curlimages/curl -- curl -m 5 payments-svc.payments.svc:8080
# → result: curl: (28) Failed to connect ... Timeout  (default-deny сработал)
```

**Устранение неполадок:** если трафик НЕ блокируется — проверьте `kubectl get pods -n kube-system` на наличие работающего CNI с поддержкой NetworkPolicy; `kubectl describe networkpolicy` покажет применённые селекторы. Ошибка «тихой неизоляции» = CNI не поддерживает политики.

### Зоны на сетевом экране Cisco (Zone-Based Policy Firewall)

На маршрутизаторах IOS/XE зонирование задаётся явным сопоставлением интерфейсов с зонами и zone-pair политиками (stateful inspection). Это классическая реализация границы зон на L3-устройстве.

**Предварительные требования:** маршрутизатор с лицензией security, интерфейсы `Gi0/1` (inside), `Gi0/2` (dmz), `Gi0/0` (outside).

```cisco
! Определение зон
zone security INSIDE
zone security DMZ
zone security OUTSIDE

! Классификация инспектируемого трафика
class-map type inspect match-any CM-DMZ-OUT
 match protocol http
 match protocol https

! Политика: из INSIDE в DMZ разрешить только HTTP/HTTPS, остальное drop
policy-map type inspect PM-INSIDE-DMZ
 class type inspect CM-DMZ-OUT
  inspect
 class class-default
  drop log

! Привязка зон к интерфейсам
interface Gi0/1
 zone-member security INSIDE
interface Gi0/2
 zone-member security DMZ

! Zone-pair определяет направление и применяет политику
zone-pair security ZP-INSIDE-DMZ source INSIDE destination DMZ
 service-policy type inspect PM-INSIDE-DMZ
```

**Валидация:**
```cisco
show zone-pair security
! → result:
! Zone-pair: ZP-INSIDE-DMZ  Source-Zone INSIDE  Destination-Zone DMZ
!   Service-policy PM-INSIDE-DMZ

show policy-map type inspect zone-pair sessions
! → result: список активных inspected-сессий и счётчики drop
```

**Устранение неполадок:** после назначения `zone-member` весь трафик через интерфейс блокируется, пока нет zone-pair в нужном направлении (default-deny реализуется самой архитектурой ZBF). Если связь пропала после добавления зоны — проверьте наличие zone-pair `source->destination` для каждого нужного направления.

### Хостовые зоны через nftables (альтернатива firewalld)

Если firewalld недоступен (минимальный контейнер/embedded), зоны реализуются через цепочки по интерфейсу (аналог firewalld zone по `iifname`):

```bash
# Сохранить правила в /etc/nftables.conf
cat > /etc/nftables.conf <<'EOF'
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        iifname "eth0" goto public
        iifname "eth1" goto trusted
        iif "lo" accept
    }
    chain public {
        ct state established,related accept
        tcp dport { 80, 443 } accept
        counter drop
    }
    chain trusted {
        ct state established,related accept
        ip saddr 10.0.99.0/24 tcp dport 22 accept
        counter drop
    }
}
EOF
sudo nft -f /etc/nftables.conf
```

**Валидация:**
```bash
sudo nft list ruleset
# → result: table inet filter { chain input { ... iifname "eth0" goto public ... } ... }
```

## Диагностика и устранение неполадок

- **Асимметричная маршрутизация ломает stateful firewall.** Если пакет уходит через одну границу зоны, а ответ возвращается через другую, stateful МСЭ не видит установленную сессии и дропает return-трафик. Решение: единая точка применения (один МСЭ/zone-pair на направление) либо stateful-syncing (наличие conntrack-cluster), либо явный маршрут обратно через тот же enforcement point.
- **Возвратный трафик заблокирован (conntrack).** Для stateful зон (SG, ZBF, nftables с `ct state`) обратный пакет разрешается автоматически; для stateless (Network ACL, некоторые L3-ACL) нужно явно разрешить ephemeral ports (1024–65535) в ответном направлении.
- **Дрейф конфигурации зон.** Правило добавлено в runtime, но не в `--permanent` (firewalld) или не сохранено (`nft list ruleset` vs `nft -f`), и после перезагрузки зона «исчезает». Всегда валидируйте persistent-конфиг и применяйте `--reload`/`nft -f` с сохранением.
- **Ложная изоляция контейнеров.** NetworkPolicy не работает без поддерживающего CNI — трафик течёт свободно, создавая иллюзию зоны. Проверяйте CNI перед выводом зоны в прод.
- **Bypass через общий L2.** Две «разные» зоны в одном VLAN/коммутаторе с L2-доступом могут общаться напрямую, минуя МСЭ. Изолируйте зоны на L2 (разные VLAN/PVLAN) или применяйте L2-фильтрацию.
- **Методы диагностики:** `tcpdump -i <iface> host <zone-ip>` на границе зоны; `conntrack -L` для проверки сессий; `firewall-cmd --list-all-zones`; `nft list ruleset`; `show zone-pair security` (Cisco); VPC Reachability Analyzer и Flow Logs в облаке; экспорт в SIEM для выявления Lateral Movement.

## Лучшие практики

- **Default-deny между зонами:** разрешайте только явно необходимые потоки; всё неописанное — запрещено.
- **Минимизация blast radius:** дробите крупные зоны (Users/Apps/Data/Mgmt/Storage), изолируйте критичные активы отдельно.
- **Явное логирование на границах:** каждый deny и критичный allow пишется в лог/ SIEM для аудита и расследования инцидентов.
- **Отдельная OOB/Management зона:** управление оборудованием недоступно из пользовательских и публичных зон; доступ только через VPN/Bastion с MFA.
- **Матрица межзонного доступа (Zone Access Matrix):** документируйте «зона А → зона Б → порт → разрешено/запрещено» и регулярно сверяйте с реальными правилами.
- **Наблюдаемость (Day 2):** визуализация East-West (Hubble, Kiali), flow-логи, периодический аудит «забытых» разрешений.
- **Регулярный пересмотр:** зоны и правила устаревают вместе с архитектурой; проводите review при добавлении сервисов.
- **Откат и очистка:** перед применением критичных правил фиксируйте предыдущий state (`nft list ruleset > backup.conf`, экспорт SG/zone-pair). Для firewalld — сохраняйте `--permanent` и имейте консольный/OOB доступ на случай SSH-локаута. Удаляйте временные разрешения (white-list для тестов) сразу по завершении.

## Граничные случаи

- **IPv6 и отсутствие NAT:** каждый хост глобально адресуем, поэтому изоляция держится исключительно на stateful firewall и RA/DHCPv6 Guard; служебный ICMPv6 должен быть разрешён, иначе зона неработоспособна.
- **Облако: двойной слой.** Security Groups (stateful) и Network ACL (stateless) применяются независимо — правило в SG не компенсирует запрет в NACL и наоборот; return-трафик в NACL нужно разрешать вручную.
- **Контейнерные оверлеи:** зона на уровне CNI (Pod Network) не совпадает с физической сетью; востребована микросегментация (NetworkPolicy/eBPF), а не только сетевой МСЭ.
- **Stateful vs stateless на границе:** выбор влияет на необходимость явных return-правил и на масштабируемость (stateless дешевле по памяти, но требует симметрии).
- **OT/АСУ ТП:** в модели Purdue шифрование и произвольные протоколы могут быть запрещены техпроцессом; изоляция реализуется проксированием на уровне приложений и односторонними шлюзами (data diode) в IDMZ, а не прозрачным L3-фильтром.
- **Zero Trust поверх зон:** при внедрении mTLS/identity-based доступа статические IP-правила зон дополняются, но не заменяются — периметр сужается до каждой рабочей нагрузки.

## Дополнительная информация

- [Концепция Zero Trust (Нулевое доверие)](./zero_trust_overview.md) — современная альтернатива периметру и основа контекстного зонирования.
- [Сетевая сегментация и микросегментация](./network_segmentation_and_microsegmentation.md) — детализация изоляции до уровня подов и процессов.
- [Firewalld: Zone-based защита](../../Linux/Networking/Settings/tools/firewalld.md) — практическая реализация зон на уровне ОС.
