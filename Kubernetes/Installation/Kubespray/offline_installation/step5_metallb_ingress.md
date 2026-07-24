# Kubespray: Offline установка — Шаг 5: Настройка MetalLB и Ingress

## Определения

**Ingress (Входной контроллер)** — ресурс Kubernetes, который предоставляет правила для управления внешним доступом к сервисам в кластере (преимущественно HTTP/HTTPS). Он обеспечивает балансировку нагрузки на прикладном уровне (L7), терминацию SSL/TLS и маршрутизацию на основе виртуальных хостов и путей URL.

**MetalLB** — сетевой балансировщик нагрузки для кластеров Kubernetes, развёрнутых на «голом железе» (bare-metal). Поскольку в таких средах отсутствует встроенный механизм `LoadBalancer` (доступный в облаках AWS/GCP/Azure), MetalLB реализует эту функциональность через стандартные протоколы: ARP/NDP (режим Layer 2) или BGP.

**VIP (Virtual IP)** — виртуальный IP-адрес, который не привязан жестко к физическому интерфейсу конкретного узла, а динамически назначается MetalLB для обслуживания внешнего трафика.

Детальные концепции MetalLB и режимы его работы описаны в **[SSoT: MetalLB — балансировщик для Bare-metal](../../../Networking/metallb.md)**.

---

## Основные концепции

### Цель этапа

Обеспечение отказоустойчивого внешнего доступа к сервисам кластера в изолированном контуре. Без этого этапа приложения будут доступны только внутри кластерной сети (ClusterIP) или через NodePort, что неудобно для промышленной эксплуатации.

**Ключевые задачи:**

1. **Резервирование IP-пула:** выбор диапазона адресов, которые не конфликтуют с DHCP-сервером организации.
2. **Активация MetalLB:** настройка способа анонсирования адресов (в данном гайде — L2 как наиболее простой для закрытых сред).
3. **Развёртывание Ingress-контроллера:** создание «входной двери» для всех HTTP-запросов.
4. **Маршрутизация (Ingress Resources):** описание правил доступа к конкретным инструментам (Harbor, Hubble, Dashboard).
5. **Локальный DNS:** привязка доменных имен к выделенным VIP.

### Архитектура прохождения трафика (Offline)

В закрытом контуре цепочка выглядит следующим образом:

1. **Клиент (браузер)** → обращается к `hubble.k8s.domain.local`.
2. **DNS (Harbor/Internal DNS)** → возвращает IP `192.168.1.200` (MetalLB VIP).
3. **Сетевой уровень** → пакет попадает на узел кластера, который в данный момент владеет этим VIP (выбирается через лидерство в MetalLB Speaker).
4. **Ingress-Nginx Pod** → принимает трафик на портах 80/443, анализирует заголовок `Host: hubble.k8s.domain.local`.
5. **Cilium Network** → перенаправляет трафик в соответствующий Pod сервиса `hubble-ui`.

---

## Практические сценарии

### 1. Конфигурация MetalLB в режиме Layer 2

Для активации балансировщика необходимо создать два ресурса: `IPAddressPool` (где брать адреса) и `L2Advertisement` (как сообщать сети о них).

**Манифест конфигурации (`metallb-l2-setup.yaml`):**

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: primary-pool
  namespace: metallb-system
spec:
  # Используйте диапазон из вашей подсети, исключенный из DHCP
  addresses:
  - 192.168.1.200-192.168.1.210
  autoAssign: true
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: l2-adv
  namespace: metallb-system
spec:
  # Привязка анонсирования к созданному пулу
  ipAddressPools:
  - primary-pool
```

**Применение манифеста:**

```bash
kubectl apply -f metallb-l2-setup.yaml
# → ipaddresspool.metallb.io/primary-pool created
# → l2advertisement.metallb.io/l2-adv created
```

### 2. Валидация Ingress-Nginx и MetalLB

Если в `group_vars` Kubespray было указано `ingress_nginx_enabled: true`, контроллер развернется автоматически. Проверьте, получил ли он внешний адрес.

**Проверка статуса сервиса:**

```bash
kubectl get svc -n ingress-nginx ingress-nginx-controller
# → NAME                       TYPE           CLUSTER-IP      EXTERNAL-IP     PORT(S)
# → ingress-nginx-controller   LoadBalancer   10.233.15.204   192.168.1.200   80:31234/TCP,443:32456/TCP
```

> **Важно по версиям (2026):** Community-версия `ingress-nginx` (v1.x) перешла в стадию ограниченной поддержки (EOL). В новых инсталляциях на базе Cilium рекомендуется использовать **Cilium Ingress Controller**, который работает нативно через eBPF без лишних прослоек.

### 3. Настройка доступа к Hubble UI через Ingress

Для доступа к визуализации Cilium в закрытом контуре создадим правило Ingress.

**Манифест Ingress (`hubble-ui-rules.yaml`):**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hubble-ui
  namespace: kube-system
  annotations:
    # Использование Nginx в качестве контроллера
    kubernetes.io/ingress.class: nginx
spec:
  rules:
  - host: hubble.k8s.domain.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: hubble-ui
            port:
              number: 80
```

**Применение:**

```bash
kubectl apply -f hubble-ui-rules.yaml
# → ingress.networking.k8s.io/hubble-ui created
```

### 4. Настройка DNS в закрытом контуре

Для работы через браузер необходимо, чтобы клиентская машина понимала домен `hubble.k8s.domain.local`.

**Вариант А: Локальный DNS (рекомендуется)**
Добавьте A-запись на вашем DNS-сервере (который часто совмещен с Harbor):
`hubble.k8s.domain.local  IN  A  192.168.1.200`

**Вариант Б: Ручная настройка на клиенте**
Отредактируйте файл `/etc/hosts` (Linux/macOS) или `C:\Windows\System32\drivers\etc\hosts` (Windows):
`192.168.1.200  hubble.k8s.domain.local`

---

## Дополнительная информация

### Диагностика и устранение неполадок

**1. Статус External IP застрял в `<pending>`:**
- Проверьте логи MetalLB Controller: `kubectl logs -n metallb-system -l app.kubernetes.io/component=controller`.
- Убедитесь, что IP-пул (`addresses`) находится в той же L2-подсети, что и интерфейсы узлов.

**2. IP назначен, но сервис недоступен по сети:**
- Проверьте наличие ARP-ответов: `arping -I <eth_name> 192.168.1.200`.
- Убедитесь, что в конфигурации `kube-proxy` (если используется) включен параметр `strictARP: true`. Для Cilium это обычно не требуется, но при совместном использовании критично.

**3. Ошибка 404 при обращении по DNS:**
- Проверьте, что в Ingress-ресурсе правильно указан `host` и он совпадает с тем, что вы вводите в браузере.
- Проверьте логи Ingress-контроллера: `kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx`.

### См. также

- **[Шаг 4: Развёртывание кластера](./step4_cluster_deploy.md)** — процедура запуска Ansible.
- **[Проверка кластера](./cluster_verification.md)** — глубокое тестирование сетевой связности и DNS.
- **[SSoT: MetalLB — детальный справочник](../../../Networking/metallb.md)** — настройка BGP режима и продвинутых пулов.
- **[Cilium: Настройка Hubble](../../../Networking/Network/CNI/cilium.md#hubble-ui)** — параметры визуализации сетевых потоков.
