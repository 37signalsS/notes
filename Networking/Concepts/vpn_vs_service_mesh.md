# VPN vs Service Mesh

## Определения

- **VPN (Virtual Private Network):** Зашифрованный туннель на L3/L4 для безопасного подключения к частной сети через публичную. Защищает трафик **north-south** (удалённый доступ, site-to-site).
- **Service Mesh:** Инфраструктурный слой на L7 для управления взаимодействием между сервисами. Защищает трафик **east-west** (между микросервисами).

Оба инструмента — компоненты [Zero Trust](./zero_trust_overview.md), решающие разные задачи.

## Основные концепции

### Ключевые различия

| Критерий | VPN | Service Mesh |
| :--- | :--- | :--- |
| **Уровень** | L3/L4 туннели ([IPsec](../Tunnels/ipsec/ipsec.md), [WireGuard](../../Vpn/wireguard.md)) | L7 прокси/sidecar (Envoy), eBPF |
| **Идентичность** | IP-адреса, подсети, сертификаты | SPIFFE/SVID, сервисные аккаунты |
| **Шифрование** | Весь трафик внутри туннеля | mTLS между конкретными сервисами |
| **Политики доступа** | ACL на основе IP/портов | Правила L7 (методы, пути, заголовки) |
| **Наблюдаемость** | Ограничена (счётчики трафика) | Детальная (трассировка, метрики запросов) |
| **Гранулярность** | Макросегментация (сетевые сегменты) | Микросегментация (уровень сервисов) |

## Практические сценарии

### Гибридный подход

Типовой паттерн: VPN для site-to-site между облаком и on-premise (north-south), Service Mesh для контроля трафика между микросервисами в Kubernetes (east-west).

### Пример конфигурации VPN (WireGuard)

```ini
# Хост A
[Interface]
Address = 10.10.0.1/24
PrivateKey = <A-PRIVATE>

[Peer]
PublicKey = <B-PUBLIC>
AllowedIPs = 10.10.0.2/32
Endpoint = 203.0.113.2:51820
```

### Пример политики Service Mesh (Istio AuthorizationPolicy)

Требует mTLS и разрешает `POST` к `orders` только от `payments`:

```yaml
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: allow-payments-to-orders
spec:
  selector:
    matchLabels:
      app: orders
  action: ALLOW
  rules:
  - from:
    - source:
        principals: ["cluster.local/ns/payments/sa/payments-sa"]
    to:
    - operation:
        methods: ["POST"]
```

### Компромиссы

- **Производительность:** VPN на L3/L4 вносит минимальные задержки. Service Mesh (sidecar-прокси) добавляет оверхед за счёт L7-обработки и телеметрии.
- **Сложность:** VPN — управление ключами и маршрутизацией. Service Mesh — плоскость управления, ротация сертификатов, конфигурация прокси.

## Дополнительная информация

- Туннелирование: [Tunneling Overview](../Tunnels/tunneling_overview.md)
- WireGuard: [WireGuide Setup](../../Vpn/wireguard.md)
- Service Mesh: [Service Mesh Concepts](../../Service_Mesh/service_mesh_concepts.md)
- Сегментация: [Network Segmentation](./network_segmentation_and_microsegmentation.md)
