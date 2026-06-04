# Yandex Cloud — Virtual Private Cloud (VPC)

## Определения

**Virtual Private Cloud (VPC)** — изолированная программно-определяемая сеть в Yandex Cloud для размещения ресурсов: виртуальных машин, баз данных, Kubernetes-кластеров, балансировщиков.

**Сеть (Network)** — логическое объединение подсетей в рамках каталога, определяющее границы сегментации и точки пирового соединения (peering).

**Подсеть (Subnet)** — сегмент сети в одной зоне доступности с собственным CIDR-пулом частных адресов.

**Security Group** — набор правил контроля сетевого трафика на уровне L3/L4 для сетевых интерфейсов.

---

## Основные концепции

### Компоненты VPC

| Компонент | Назначение | Ключевые параметры |
| :--- | :--- | :--- |
| **Network** | Изоляция и сегментация ресурсов | Границы для peering, набор подсетей |
| **Subnet** | Адресация в зоне доступности | CIDR, зона, сеть |
| **Route Table** | Маршрутизация трафика | Статические маршруты, привязка к подсетям |
| **Internet Gateway** | Публичный ingress/egress | Маршрут `0.0.0.0/0` для публичных ВМ |
| **NAT Gateway** | Приватный egress для подсетей | Публичный IP, маршрут `0.0.0.0/0` |
| **Security Group** | Политики трафика | Direction, протокол, порты, CIDR |

> **Важно:** Egress NAT устарел и не поддерживается для новых ресурсов. Рекомендуется использовать NAT Gateway.

### Типы подсетей

**Публичная подсеть:**

- ВМ с публичными IP-адресами.
- Таблица маршрутов: `0.0.0.0/0 → Internet Gateway`.
- Security Groups: вход 80/443 отовсюду, 22 только с доверенных IP.

**Приватная подсеть:**

- ВМ без публичных IP-адресов.
- Таблица маршрутов: `0.0.0.0/0 → NAT Gateway`.
- Вход только из публичной подсети, через Load Balancer или VPN.

### Security Groups (Группы безопасности)

Правила работают на уровне сетевых интерфейсов виртуальных машин.

**Типы правил:**

- **Ingress** — входящий трафик.
- **Egress** — исходящий трафик.

**Параметры правила:**

- Протокол (TCP, UDP, ICMP, любой).
- Порт или диапазон портов.
- CIDR-блок источника/назначения.
- Описание.

**Лимиты (2025):**

- До 10 security groups на каталог.
- До 60 правил на одну группу.

### Маршрутизация

**Статические маршруты:**

- Явно заданные пути для трафика.
- Пример: `10.0.0.0/8 → next-hop 192.168.1.1`.

**Таблицы маршрутов:**

- Привязываются к подсетям.
- Одна подсеть — одна таблица маршрутов.
- Маршрут по умолчанию: `0.0.0.0/0`.

### NAT Gateway (Шлюз NAT)

**Назначение:** обеспечение исходящего доступа в интернет для приватных ВМ без публичных IP-адресов.

**Преимущества:**

- Управляемый сервис.
- Автоматическое масштабирование.
- Интеграция с Security Groups.
- Статические публичные IP (через отдельные адреса).

**Лимиты:**

- До 20 NAT Gateway на каталог.
- Пропускная способность зависит от конфигурации.

### Cloud VPN и Peering (Пиринг)

**Cloud VPN:**

- [IPsec](../Networking/Tunnels/ipsec/ipsec.md)-туннели для подключения on-prem инфраструктуры.
- Динамическая маршрутизация (BGP).

**VPC Peering:**

- Прямое соединение между сетями Yandex Cloud.
- Без транзитной маршрутизации.

---

## Практические сценарии

### Создание сети и подсетей

```bash
# Создание сети
yc vpc network create --name net-main

# Подсеть в зоне ru-central1-a
yc vpc subnet create \
  --name subnet-a \
  --zone ru-central1-a \
  --range 10.10.1.0/24 \
  --network-name net-main

# Подсеть в зоне ru-central1-b
yc vpc subnet create \
  --name subnet-b \
  --zone ru-central1-b \
  --range 10.10.2.0/24 \
  --network-name net-main
```

### Security Group для веб-слоя

```bash
# Создание группы
yc vpc security-group create --name sg-web --network-name net-main

# Разрешить HTTP (80)
yc vpc security-group add-rule \
  --security-group-name sg-web \
  --direction ingress \
  --protocol tcp \
  --port 80 \
  --v4-cidr 0.0.0.0/0 \
  --description "HTTP from anywhere"

# Разрешить HTTPS (443)
yc vpc security-group add-rule \
  --security-group-name sg-web \
  --direction ingress \
  --protocol tcp \
  --port 443 \
  --v4-cidr 0.0.0.0/0 \
  --description "HTTPS from anywhere"

# Разрешить SSH только с доверенного IP
yc vpc security-group add-rule \
  --security-group-name sg-web \
  --direction ingress \
  --protocol tcp \
  --port 22 \
  --v4-cidr 203.0.113.0/24 \
  --description "SSH from admin network"

# Исходящий трафик (по умолчанию разрешён)
yc vpc security-group add-rule \
  --security-group-name sg-web \
  --direction egress \
  --protocol any \
  --v4-cidr 0.0.0.0/0 \
  --description "Allow all outbound"
```

### Security Group для БД

```bash
# PostgreSQL только из внутренней сети
yc vpc security-group create --name sg-db --network-name net-main

yc vpc security-group add-rule \
  --security-group-name sg-db \
  --direction ingress \
  --protocol tcp \
  --port 5432 \
  --v4-cidr 10.10.0.0/16 \
  --description "PostgreSQL from internal network"

yc vpc security-group add-rule \
  --security-group-name sg-db \
  --direction egress \
  --protocol any \
  --v4-cidr 0.0.0.0/0
```

### NAT Gateway для приватных подсетей

```bash
# Создание NAT Gateway
yc vpc gateway create --name nat-gw

# Таблица маршрутов с NAT
yc vpc route-table create --name rt-nat --network-name net-main

yc vpc route-table static-route create \
  --route-table-name rt-nat \
  --destination 0.0.0.0/0 \
  --gateway-id $(yc vpc gateway get --name nat-gw --format json | jq -r '.id')

# Привязка таблицы маршрутов к подсети
yc vpc subnet update --name subnet-b \
  --route-table-name rt-nat
```

### Типовая топология: двухуровневая архитектура

```
┌─────────────────────────────────────────────────────┐
│                    VPC: net-main                    │
│                                                     │
│  ┌─────────────────┐      ┌─────────────────────┐  │
│  │ Public Subnet   │      │  Private Subnet     │  │
│  │ 10.10.1.0/24    │      │  10.10.2.0/24       │  │
│  │                 │      │                     │  │
│  │ ┌─────────────┐ │      │ ┌─────────────────┐ │  │
│  │ │  Web VM     │ │      │ │   App VM        │ │  │
│  │ │  + Nat IP   │ │      │ │   (no Nat IP)   │ │  │
│  │ └─────────────┘ │      │ └─────────────────┘ │  │
│  │       │         │      │         │           │  │
│  │       ▼         │      │         ▼           │  │
│  │ ┌─────────────┐ │      │ ┌─────────────────┐ │  │
│  │ │  LB (App)   │ │      │ │   DB Cluster    │ │  │
│  │ └─────────────┘ │      │ └─────────────────┘ │  │
│  └─────────────────┘      └─────────────────────┘  │
│         │                          │                │
│         ▼                          ▼                │
│  ┌─────────────┐          ┌─────────────────┐      │
│  │ Internet GW │          │   NAT Gateway   │      │
│  └─────────────┘          └─────────────────┘      │
└─────────────────────────────────────────────────────┘
```

**Маршрутизация:**

- Public Subnet: `0.0.0.0/0 → Internet Gateway`.
- Private Subnet: `0.0.0.0/0 → NAT Gateway`.

**Security Groups:**

- `sg-web`: 80/443 ingress, 22 с админ-IP.
- `sg-app`: 8080 ingress только от `sg-web`.
- `sg-db`: 5432 ingress только от `sg-app`.

### Проверка и диагностика

```bash
# Список сетей
yc vpc network list

# Список подсетей
yc vpc subnet list

# Информация о security group
yc vpc security-group get --name sg-web

# Проверка маршрутов
yc vpc route-table get --name rt-nat

# Удаление неиспользуемых ресурсов
yc vpc security-group delete --name sg-old
yc vpc subnet delete --name subnet-unused
```

---

## Дополнительная информация

Размещение ВМ в подсетях — [Compute Cloud](./Compute-Cloud.md), управление каталогами и метками для сетей — [Resource Manager](./Resource_Manager/overview.md), мониторинг сетевого трафика — [Monitoring](./Monitoring/index.md).

Сетевая модель CNI в [Kubernetes](../Kubernetes/kubernetes_overview.md) использует VPC, интеграция балансировщиков с подсетями — [Load Balancer](../Networking/OSI_TCP_IP_Model/osi_model.md#балансировщики-нагрузки-l4-и-l7), декларативное управление сетью — [Terraform](../Concepts/iac_overview.md).

Безопасность: Security Groups как основной механизм сегментации, приватные подсети для изоляции критичных ресурсов, [VPN/Peering](../Networking/Tunnels/) для подключения on-prem.

### Актуальная информация

- **Egress NAT** — устарел, использовать NAT Gateway.
- **Лимиты:** до 10 security groups и до 20 NAT Gateway на каталог (квоты могут отличаться, проверять через `yc vpc`).
