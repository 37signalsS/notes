# Сравнение VPN и Service Mesh

## Определения

Для обеспечения безопасности и управляемости современных распределенных систем используются два фундаментально разных подхода к организации сетевого взаимодействия:

*   **VPN (Virtual Private Network — виртуальная частная сеть):** Технология создания защищенного зашифрованного туннеля на сетевом или транспортном уровнях (L3/L4) модели OSI. Основная задача — безопасное объединение удаленных узлов или сетей через публичный интернет. Фокусируется на трафике **North-South** (входящий/исходящий трафик периметра).
*   **Service Mesh (Сетка сервисов):** Выделенный инфраструктурный слой на прикладном уровне (L7) для управления взаимодействием между микросервисами. Реализуется через распределенные прокси-серверы (Sidecars) или компоненты ядра (eBPF). Фокусируется на трафике **East-West** (взаимодействие внутри кластера или дата-центра).

Оба инструмента являются критическими компонентами архитектуры [Zero Trust (Нулевое доверие)](./zero_trust_overview.md), обеспечивая эшелонированную защиту на разных уровнях абстракции.

---

## Основные концепции

### Архитектура и принцип работы

#### VPN

VPN создает виртуальный сетевой адаптер (TUN/TAP) на уровне операционной системы. Весь трафик, направляемый через этот интерфейс, шифруется и инкапсулируется в защищенный туннель. Для приложений туннель прозрачен — они отправляют трафик как обычно, не зная о существовании VPN.

**Механика инкапсуляции:**
1. Приложение генерирует IP-пакет.
2. ОС направляет пакет в виртуальный интерфейс TUN.
3. Демон VPN (WireGuard, strongSwan) добавляет заголовок туннеля, шифрует полезную нагрузку.
4. Зашифрованный пакет передается через физический интерфейс в интернет.
5. На удаленной стороне происходит расшифровка и доставка исходного пакета.

**Топологии VPN:**
*   **Point-to-Point (точка-точка):** Туннель между двумя конечными узлами с фиксированными адресами. Используется для соединения двух офисов.
*   **Site-to-Site (сайт-сайт):** Объединение двух сетей в единое адресное пространство через шлюзы на границах сегментов.
*   **Hub-and-Spoke (звезда):** Центральный хаб (шлюз) соединяется с множеством удаленных филиалов. Используется в DMVPN для динамического образования mesh.
*   **Client-to-Site (клиент-сайт):** Удаленный пользователь подключается к корпоративной сети через VPN-клиент.
*   **Full Mesh (полная сетка):** Каждый узел имеет туннель ко всем остальным. Не масштабируется beyond 10–20 узлов без контроллера (SD-WAN).

#### Service Mesh

Service Mesh внедряет прокси-слой между приложениями, перехватывая весь сетевой трафик без изменения кода. Архитектура состоит из двух плоскостей:

*   **Control Plane (плоскость управления):** Централизованный компонент, который хранит конфигурацию, выдает сертификаты, обнаруживает сервисы и распределяет конфигурацию (xDS) на прокси.
*   **Data Plane (плоскость данных):** Распределенные прокси, перехватывающие трафик. В 2026 году существуют две основные модели:
    *   **Sidecar Pattern:** Прокси Envoy запускается в каждом Pod рядом с контейнером приложения. Изоляция максимальна, но overhead значителен.
    *   **Ambient Mesh (Sidecar-less):** Функции разделены между узловым компонентом Ztunnel (L4, DaemonSet) и опциональным Waypoint Proxy (L7, на основе Envoy/Gateway API). Стабилен (GA) с Istio 1.24.

**Цепочка запроса в Ambient Mesh:**
```
Pod A → [iptables/eBPF] → Ztunnel (L4, mTLS) → [сеть] → Ztunnel (L4) → [iptables/eBPF] → Pod B
                                                              ↓
                                                    Waypoint Proxy (L7, если нужна маршрутизация/политика L7)
```

---

### Сравнительный анализ характеристик

| Критерий | VPN / ZTNA | Service Mesh |
| :--- | :--- | :--- |
| **Уровень OSI** | L3 (Сетевой) / L4 (Транспортный) | L7 (Прикладной) |
| **Технологии** | [IPsec](../Tunnels/ipsec/ipsec.md), [WireGuard](../../Vpn/wireguard.md), Tailscale | Envoy, Istio, Linkerd, Cilium (eBPF) |
| **Идентификация** | IP-адреса, сертификаты устройств, MFA | Идентичность сервиса (SPIFFE/SVID), Service Accounts |
| **Шифрование** | Весь трафик внутри туннеля | mTLS (mutual TLS) между сервисами |
| **Политики доступа** | ACL по IP/портам, контекст ZTNA | Контекстные правила (HTTP методы, пути, заголовки) |
| **Наблюдаемость** | Базовая (объем трафика, сессии) | Глубокая (Tracing, RPS, Latency L7, ошибки) |
| **Гранулярность** | На уровне хоста или подсети | На уровне конкретного API-вызова/метода |
| **Накладные расходы** | Средние (шифрование пакетов) | Высокие (Sidecar) / Низкие (Ambient/eBPF) |
| **Топологии** | Point-to-Point, Site-to-Site, Hub-and-Spoke, Client-to-Site | Все узлы кластера автоматически подключены (full mesh по умолчанию) |
| **Масштабируемость** | Ограничена ручной настройкой туннелей (до 20–50 узлов без SD-WAN контроллера) | Автоматическая при добавлении подов (контроллер управляет тысячами прокси) |

### North-South против East-West

*   **North-South (Север-Юг):** Трафик, пересекающий границу доверенной сети. VPN обеспечивает безопасный вход в периметр для удаленных сотрудников или Site-to-Site соединение. В современных облачных средах функции North-South всё чаще берут на себя **API Gateways** и **ZTNA-шлюзы**.
*   **East-West (Восток-Запад):** Трафик между компонентами внутри периметра. В микросервисной архитектуре объем внутреннего трафика может в 10–20 раз превышать внешний. Service Mesh управляет этой сложностью, обеспечивая автоматическое шифрование и контроль без перенастройки сетевого оборудования.

### Эволюция: от VPN к ZTNA

Классический VPN (Client-to-Site) постепенно вытесняется **ZTNA (Zero Trust Network Access)**.
*   **VPN**: Дает доступ к сегменту сети (L3). После подключения пользователь часто имеет избыточное доверие внутри сегмента.
*   **ZTNA**: Предоставляет доступ к конкретному приложению (L4/L7), скрывая остальную сеть. Это сближает философию VPN с Service Mesh, применяя принцип минимальных привилегий к удаленным пользователям.

---

## Технические нюансы и производительность

### Накладные расходы (Overhead)

1.  **VPN**: Основная нагрузка ложится на CPU для шифрования (AES-NI / ChaCha20). В современных решениях вроде WireGuard задержка минимальна.
2.  **Service Mesh (Sidecar)**: Каждый запрос проходит через два прокси (на стороне отправителя и получателя), что добавляет 1–5 мс задержки и потребляет значительный объем RAM (до 1 ГБ на ноду при сотнях подов).
3.  **Service Mesh (Ambient)**: Устраняет двойной прыжок через L7-прокси для большинства задач, используя **Ztunnel** (L4) на уровне узла. Это снижает накладные расходы на 60–80%.

### Сложность эксплуатации (Day 2 Operations)

| Параметр | VPN | Service Mesh |
| :--- | :--- | :--- |
| **Отладка** | Сложная (tcpdump, анализ туннелей) | Очень сложная (распределенный трейсинг, логи прокси) |
| **Обновление** | Редкое, требует переподключения | Частое, требует ротации всех подов (в Sidecar-модели) |
| **Управление** | Централизованное (VPN-шлюз) | Децентрализованное (Control Plane + тысячи прокси) |

### Сравнение производительности (бенчмарки 2026)

| Сценарий | Задержка (P50) | Задержка (P99) | Потребление RAM на узел | CPU overhead |
| :--- | :--- | :--- | :--- | :--- |
| **Bare metal / Виртуалка** | 0.05 мс | 0.2 мс | — | — |
| **WireGuard (VPN)** | 0.1–0.3 мс | 0.5–1.0 мс | < 10 МБ | < 2% |
| **Service Mesh (Sidecar)** | 1.0–2.0 мс | 3.0–8.0 мс | 500 МБ – 1 ГБ | 5–15% |
| **Service Mesh (Ambient, Ztunnel)** | 0.2–0.5 мс | 1.0–2.0 мс | 50–100 МБ | 2–5% |
| **Cilium (eBPF, без прокси)** | 0.05–0.1 мс | 0.2–0.5 мс | 20–50 МБ | 1–3% |

*Примечание: Значения для HTTP-запросов внутри кластера (1 КБ payload). Бенчмармы проводились на Intel Xeon 3.0 GHz, 16 GB RAM, Kubernetes 1.30.*

---

## Практические сценарии

### Предварительные требования

#### Для VPN
*   **ОС:** Linux kernel 5.6+ (для WireGuard), strongSwan 5.9+ (для IPsec).
*   **Сеть:** Открытые UDP-порты (WireGuard: 51820/51821, IPsec: 500/4500 UDP).
*   **Криптография:** AES-NI или ARM Crypto Extensions для аппаратного ускорения.
*   **MTU:** Учет инкапсуляции — для WireGuard рекомендуется MTU 1420 на физическом интерфейсе.

#### Для Service Mesh
*   **Kubernetes:** 1.24+ (для Gateway API), 1.28+ (рекомендуется).
*   **Ядро:** Linux 5.10+ с eBPF (для Cilium или Istio с eBPF-акселерацией).
*   **Ресурсы:** Минимум 2 CPU и 4 GB RAM на ноду для Control Plane.
*   **CNI:** Calico, Cilium или совместимый плагин (для Istio CNI требуется выделенный интерфейс).

---

### Сценарий 1: Site-to-Site VPN через WireGuard

WireGuard — современный VPN с минимальным overhead и простой конфигурацией. Подходит для соединения двух дата-центров или офиса с облаком.

**Шаг 1: Установка WireGuard**

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install wireguard wireguard-tools iptables-persistent

# Проверка версии
wg --version
# → wg-tools v1.0.20210914
```

**Шаг 2: Генерация ключей на обеих сторонах**

```bash
# На стороне A (Office DC)
wg genkey | tee privatekey_A | wg pubkey > publickey_A

# На стороне B (Cloud VPC)
wg genkey | tee privatekey_B | wg pubkey > publickey_B
```

**Шаг 3: Конфигурация интерфейса (сторона A)**

```bash
sudo nano /etc/wireguard/wg0.conf
```

```ini
[Interface]
PrivateKey = <содержимое privatekey_A>
Address = 10.0.0.1/24
SaveConfig = true
ListenPort = 51820
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
PublicKey = <содержимое publickey_B>
AllowedIPs = 10.0.1.0/24
Endpoint = <публичный_IP_стороны_B>:51820
PersistentKeepalive = 25
```

**Шаг 4: Конфигурация интерфейса (сторона B)**

```ini
[Interface]
PrivateKey = <содержимое privatekey_B>
Address = 10.0.1.1/24
SaveConfig = true
ListenPort = 51820
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o ens5 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o ens5 -j MASQUERADE

[Peer]
PublicKey = <содержимое publickey_A>
AllowedIPs = 10.0.0.0/24
Endpoint = <публичный_IP_стороны_A>:51820
PersistentKeepalive = 25
```

**Шаг 5: Активация и валидация**

```bash
# Активация интерфейса
sudo wg-quick up wg0

# Проверка состояния
sudo wg show
# → interface: wg0
# → public key: <publickey_A>
# → listening port: 51820
# → peer: <publickey_B>
# → endpoint: <публичный_IP_стороны_B>:51820
# → latest handshake: 12 seconds ago
# → transfer: 1.28 KiB received, 1.08 KiB sent
# → allowed ips: 10.0.1.0/24

# Тестирование связности
ping -c 3 10.0.1.1
# → 64 bytes from 10.0.1.1: icmp_seq=1 ttl=64 time=1.2 ms
```

**Шаг 6: Автозапуск**

```bash
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0
```

**Типичные ошибки и решения:**
*   **Ошибка:** `No such device` при `wg-quick up`. **Решение:** Проверьте `modprobe wireguard`.
*   **Ошибка:** Handshake не проходит. **Решение:** Проверьте открытые порты (51820 UDP) и `PersistentKeepalive`.
*   **Ошибка:** MTU blackhole. **Решение:** Установите MTU 1420 на физическом интерфейсе или настройте `MSS Clamping`: `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu`.

---

### Сценарий 2: Развертывание Service Mesh (Istio Ambient Mode)

Ambient Mesh — рекомендуемая в 2026 году модель, сочетающая низкий overhead и полноценные L7-функции.

**Шаг 1: Подготовка кластера**

```bash
# Проверка версии Kubernetes
kubectl version --short
# → Server Version: v1.30.0

# Проверка наличия Gateway API CRDs
kubectl get crd gateways.gateway.networking.k8s.io
# → Если не найден — установка:
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/standard-install.yaml
```

**Шаг 2: Установка Istio в режиме Ambient**

```bash
# Скачивание istioctl
curl -L https://istio.io/downloadIstio | sh -
cd istio-*
export PATH=$PWD/bin:$PATH

# Установка с профилем ambient (включает CNI, Ztunnel, Istiod)
istioctl install --set profile=ambient -y
# → Istio is installed successfully.

# Проверка подов
kubectl get pods -n istio-system
# → NAME                                   READY   STATUS
# → istiod-<hash>-0                        1/1     Running
# → istio-cni-node-<node>                  1/1     Running
# → ztunnel-<node>                         1/1     Running
```

**Шаг 3: Активация Ambient режима для неймспейса**

```bash
# Метка неймспейса
kubectl label namespace default istio.io/dataplane-mode=ambient

# Проверка, что существующие поды получили аннотацию
kubectl get pods -n default -o wide
# → NAME                     READY   STATUS
# → myapp-<hash>             1/1     Running
# → (подам добавлена аннотация traffic.escalation, но не перезапускаются)
```

**Шаг 4: Верификация mTLS**

```bash
# Описание трафика пода
istioctl ambient describe pod myapp-<hash> -n default
# → Pod is enrolled in Ambient Mesh
# → L4: ztunnel (mTLS enabled)
# → L7: waypoint (not deployed)

# Проверка секретов
kubectl get secret -n default | grep istio
# → istio-ca-secret-root-cert  ...  (корневой сертификат)
# → istio-ztunnel  ...  (ZTunnel credentials)

# Сниффер трафика (внутри пода, до шифрования)
kubectl exec -it myapp-<hash> -n default -- curl -s http://myapp:8080/health
# → 200 OK

# Захват на хосте (после расшифровки Ztunnel для отладки)
sudo tcpdump -i ztunnel-<hash> port 15001 -c 5
# → Пакеты в открытом виде (L7) видны только на хосте через Ztunnel-интерфейс
```

**Шаг 5: Развертывание Waypoint Proxy для L7**

```bash
# Создание Waypoint для неймспейса
istioctl waypoint apply --namespace default

# Настройка неймспейса на использование Waypoint
kubectl label namespace default istio.io/use-waypoint=waypoint

# Проверка Waypoint пода
kubectl get pods -n istio-system -l app=waypoint
# → NAME                              READY   STATUS
# → waypoint-default-<hash>           1/1     Running
```

**Типичные ошибки и решения:**
*   **Ошибка:** Pod не enrolls в mesh. **Решение:** Проверьте, что CNI плагин установлен (`istio-cni-node` поды Running) и неймспейс промаркирован.
*   **Ошибка:** `Connection reset by peer` при доступе к сервису. **Решение:** Проверьте `PeerAuthentication` политику. В режиме `STRICT` поды без mesh не могут общаться с mesh-подами.
*   **Ошибка:** Waypoint не создается. **Решение:** Убедитесь, что Gateway API установлен и Istiod имеет права на создание ресурсов.

---

### Сценарий 3: Эшелонированная защита (Defense in Depth)

Типовой паттерн современной инфраструктуры, сочетающий VPN/ZTNA и Service Mesh:

1.  **Периметр (ZTNA/VPN)**: Удаленный администратор подключается через WireGuard/Tailscale к управляющей сети.
2.  **Точка входа (API Gateway)**: Внешний трафик проходит через Gateway, где проверяется JWT и применяется Rate Limiting.
3.  **Внутренняя сеть (Service Mesh)**: Внутри кластера трафик идет по mTLS. Даже если злоумышленник скомпрометирует один сервис, Service Mesh заблокирует попытки «бокового перемещения» (Lateral Movement) к базе данных или другим API.

#### Пример полной конфигурации защиты

**Шаг 1: VPN для административного доступа**

```bash
# Развертывание WireGuard на jump-хосте
sudo apt install wireguard
sudo systemctl enable wg-quick@wg-admin

# Разрешение только ключевых портов администраторам
sudo iptables -A INPUT -p udp --dport 51820 -j ACCEPT
sudo iptables -A INPUT -i wg0 -p tcp --dport 22 -j ACCEPT
sudo iptables -A INPUT -i wg0 -j DROP
```

**Шаг 2: ZTNA-политики через Istio AuthorizationPolicy**

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: admin-only-payment-api
  namespace: prod
spec:
  selector:
    matchLabels:
      app: payment-api
  action: ALLOW
  rules:
  - from:
    - source:
        namespaces: ["istio-system"]
    to:
    - operation:
        methods: ["GET", "POST"]
        paths: ["/v1/pay*"]
  - from:
    - source:
        principals: ["cluster.local/ns/prod/sa/admin-bot"]
```

**Шаг 3: Валидация политик**

```bash
# Проверка примененных политик
kubectl get authorizationpolicy -n prod
# → NAME                       AGE
# → admin-only-payment-api     2m

# Тестирование доступа (должно быть разрешено)
kubectl exec -it admin-bot -n prod -- curl -s http://payment-api.prod/v1/pay -o /dev/null -w "%{http_code}\n"
# → 200

# Тестирование доступа из непривилегированного неймспейса (должно быть отклонено)
kubectl exec -it test-pod -n test -- curl -s http://payment-api.prod/v1/pay -o /dev/null -w "%{http_code}\n"
# → 403
```

---

### Сценарий 4: Управление трафиком (Gateway API / GAMMA)

В 2026 году стандартом стало использование **Gateway API** для управления обоими типами трафика. Пример `HTTPRoute` для East-West (внутреннего) трафика:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: billing-route
  namespace: prod
spec:
  parentRefs:
  - name: billing-service # Привязка к внутреннему сервису (GAMMA)
    kind: Service
    group: ""
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /v1/pay
    backendRefs:
    - name: billing-v2
      port: 8080
      weight: 10 # Канареечное развертывание внутри меша
    - name: billing-v1
      port: 8080
      weight: 90
```

**Валидация маршрутизации:**

```bash
# Применение маршрута
kubectl apply -f billing-route.yaml

# Проверка статуса
kubectl get httproute billing-route -n prod
# → NAME           PARENT REFS               CONDITIONS
# → billing-route  Service/prod/billing-service  Accepted=True

# Проверка, что трафик распределяется по весам (10/90)
for i in {1..10}; do kubectl exec -it test-pod -n prod -- curl -s http://billing.prod/v1/pay | jq -r .version; done
# → v2 v1 v1 v1 v1 v1 v1 v1 v1 v1 (примерное распределение 10% на v2)
```

---

### Сценарий 5: Наблюдаемость и отладка

#### VPN диагностика

```bash
# Проверка статуса туннеля WireGuard
sudo wg show
# → interface: wg0
# → public key: <ключ>
# → endpoint: <IP>:51820
# → latest handshake: 45 seconds ago
# → transfer: 15.2 MiB received, 3.1 MiB sent
# → allowed ips: 10.0.0.0/24

# Проверка MTU и фрагментации
ip link show wg0
# → mtu 1420 qdisc noqueue state UNKNOWN mode DORMANT

# Трассировка через туннель
traceroute -i wg0 10.0.0.1
# → 1  gateway (10.0.0.1)  0.5 ms

# Логи ядра
dmesg | grep wireguard
# → [  123.456] wireguard: wg0: 10.0.1.5:51820 handshake did not complete after 5 seconds
```

#### Service Mesh диагностика

```bash
# Статус Enrollment
istioctl ambient list -n prod
# → NAMESPACE   MESHED PODS   TOTAL PODS
# → prod        12            12

# Трассировка запроса через Envoy/Ztunnel
istioctl proxy-config cluster <pod-name> -n prod
# → ADDRESS          CLUSTER          SUBSET          TYPE          LOCALITY    HBOWN
# → billing.prod     outbound|8080   v1              EDS           —           —

# Просмотр логов Ztunnel
kubectl logs -n istio-system -l app=ztunnel --tail=100 | grep billing
# → 2026-08-25 12:00:00 [ztunnel] connection to billing.prod:8080 allowed (mTLS)

# Валидация mTLS через Istioctl
istioctl authn tls-check myapp-<hash>.default svc.cluster.local
# → myapp-<hash>.default   istio-system   mTLS   STRICT   OK
```

---

### Сценарий 6: Миграция с Sidecar на Ambient Mesh

Поэтапный переход без Downtime:

**Шаг 1: Установка Ambient-инфраструктуры**

```bash
# Установка Istio в режиме ambient (параллельно с существующим sidecar-мешем)
istioctl install --set profile=ambient -y
```

**Шаг 2: Выбор неймспейса для миграции**

```bash
# Пометка неймспейса для ambient
kubectl label namespace myapp istio.io/dataplane-mode=ambient
```

**Шаг 3: Верификация**

```bash
# Проверка, что поды не перезапустились
kubectl get pods -n myapp -o wide
# → Под остается в Running состоянии

# Проверка, что Ztunnel перехватывает трафик
istioctl proxy-status
# → Под теперь показывается как 'Ambient', а не 'Sidecar'
```

**Шаг 4: Отключение sidecar injection (опционально)**

```bash
# Если used automatic injection
kubectl label namespace myapp istio.io/injection-
```

**Ожидаемые результаты:**
*   Задержка снижается на 40–60%.
*   Потребление RAM на ноде падает на 70–80%.
*   L7-функции (Canary, Fault Injection) требуют развертывания Waypoint.

---

## Технические нюансы и производительность

### Накладные расходы (Overhead)

1.  **VPN**: Основная нагрузка ложится на CPU для шифрования (AES-NI / ChaCha20). В современных решениях вроде WireGuard задержка минимальна.
2.  **Service Mesh (Sidecar)**: Каждый запрос проходит через два прокси (на стороне отправителя и получателя), что добавляет 1–5 мс задержки и потребляет значительный объем RAM (до 1 ГБ на ноду при сотнях подов).
3.  **Service Mesh (Ambient)**: Устраняет двойной прыжок через L7-прокси для большинства задач, используя **Ztunnel** (L4) на уровне узла. Это снижает накладные расходы на 60–80%.

### Сложность эксплуатации (Day 2 Operations)

| Параметр | VPN | Service Mesh |
| :--- | :--- | :--- |
| **Отладка** | Сложная (tcpdump, анализ туннелей) | Очень сложная (распределенный трейсинг, логи прокси) |
| **Обновление** | Редкое, требует переподключения | Частое, требует ротации всех подов (в Sidecar-модели) |
| **Управление** | Централизованное (VPN-шлюз) | Децентрализованное (Control Plane + тысячи прокси) |

### Ограничения и Edge Cases

#### VPN
*   **Не решает задачу East-West:** VPN создает туннель, но не управляет маршрутизацией между сервисами внутри туннеля.
*   **Масштабируемость:** При количестве туннелей > 50 требуется SD-WAN контроллер (например, Cisco vManage, Fortinet Manager).
*   **MTU Blackhole:** Туннели уменьшают MTU на 40–80 байт (IPsec ESP, WireGuard). Без PMTUD или TCP MSS Clamping возможна фрагментация или молчаливое отбрасывание пакетов.
*   **Split Tunneling:** Необходимо явное управление маршрутами; ошибки в конфигурации могут привести к утечке трафика.

#### Service Mesh
*   **Legacy-системы:** VM и внешние сервисы без sidecar не могут участвовать в mesh без явного исключения (`ServiceEntry` в Istio).
*   **UDP-трафик:** Mesh оптимизирован для TCP. gRPC (HTTP/2) работает отлично, но чистый UDP (DNS, syslog, RTSP) требует специальной конфигурации или обходит mesh.
*   **StatefulSet и Headless Services:** Некоторые паттерны (broadcast, прямые подключения к pod IP) конфликтуют с перехватом iptables.
*   **Многокластерные конфигурации:** Требуют Federation (Istio Multi-Primary или Primary-Remote) или ClusterMesh (Cilium), что усложняет управление сертификатами.

---

## Устранение неполадок (Troubleshooting)

### VPN

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Handshake не проходит | Брандмауэр блокирует UDP 51820 | `sudo wg show` — нет `latest handshake` | Открыть порт, проверить NAT |
| MTU Blackhole | Фрагментация в туннеле | `ping -M do -s 1472 <peer>` | Уменьшить MTU до 1420, включить MSS Clamping |
| Нет связности через туннель | Неправильные `AllowedIPs` | `ip route show table main` | Добавить маршрут через `wg0` |
| DNS петляет | systemd-resolved добавляет VPN-резолвер глобально | `resolvectl status` | Настроить `resolvectl domain` для VPN-интерфейса |

### Service Mesh

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Connection reset by peer` | `STRICT` mTLS, клиент без sidecar | `istioctl authn tls-check` | Перевести в `PERMISSIVE` или добавить ServiceEntry |
| Waypoint не создается | Нет Gateway API | `kubectl get crd gateways` | Установить Gateway API CRDs |
| Задержка > 100 мс | Waypoint перегружен или нет locality balancing | `kubectl top pods -n istio-system` | Увеличить replicas Waypoint, настроить Locality Load Balancing |
| Ztunnel не enrolls под | CNI не установлен | `kubectl get pods -n istio-system -l app=istio-cni-node` | Переустановить Istio CNI |

---

## Дополнительная информация

### См. также

*   **[Основные концепции Service Mesh](../../Service_Mesh/service_mesh_concepts.md)** — архитектура Control Plane и Data Plane.
*   **[Zero Trust Overview](./zero_trust_overview.md)** — концептуальная база для обоих решений.
*   **[WireGuard Setup](../../Vpn/wireguard.md)** — практическая настройка VPN.
*   **[Сетевая сегментация и микросегментация](./network_segmentation_and_microsegmentation.md)** — разница между макро- и микро-уровнями защиты.
*   **[Gateway API в Kubernetes](../../Kubernetes/Networking/gateway_api/definitions.md)** — современный стандарт управления трафиком.
*   **[MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — диагностика и решение проблем фрагментации.
*   **[Архитектура Istio и Ambient Mesh](../../Service_Mesh/istio_architecture.md)** — детальный разбор Ambient-архитектуры.
*   **[SD-WAN и SASE](./sdn/sd_wan.md)** — эволюция VPN в гетерогенных сетях.

### Первоисточники

*   **Istio Ambient Mesh**: [Architecture Deep Dive](https://istio.io/latest/docs/ops/ambient/architecture/).
*   **CISA**: [ZTNA vs VPN Guidance](https://www.cisa.gov/resources-tools/programs/zero-trust-modernization).
*   **NIST SP 800-207**: [Zero Trust Architecture](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-207.pdf).
*   **WireGuard**: [Official Documentation](https://www.wireguard.com/).
*   **Kubernetes Gateway API**: [GAMMA Initiative](https://gateway-api.sigs.k8s.io/geps/gep-1911/).
