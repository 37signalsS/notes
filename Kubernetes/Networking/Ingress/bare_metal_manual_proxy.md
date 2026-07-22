# Внешний доступ в Bare-metal — NodePort, Nginx и dnsmasq

## Определения

**NodePort** — тип Service в Kubernetes, который открывает статический порт на всех узлах кластера. Трафик, поступающий на этот порт, перенаправляется на соответствующие поды через ClusterIP сервиса.

**dnsmasq** — легкий DNS-сервер (Domain Name System), используемый для централизованного управления доменными именами в локальной сети или на этапе разработки (DEV-среды).

**Nginx-прокси (Nginx Proxy)** — внешний по отношению к кластеру прокси-сервер, который принимает HTTP/HTTPS трафик на стандартных портах (80/443) и перенаправляет его на `NodePort` узлов Kubernetes.

---

## Основные концепции

В bare-metal (физические серверы без гипервизора) средах часто возникают сложности с использованием `MetalLB` в режиме L2 (Layer 2) из-за блокировки ARP (Address Resolution Protocol) между сегментами сети или BGP (Border Gateway Protocol) из-за отсутствия поддержки на сетевом оборудовании. Комбинация внешнего прокси и централизованного DNS является надежным обходным решением для DEV-стендов и этапов миграции.

### Архитектура решения

1. **Клиент** запрашивает доменное имя (например, `myapp.k8s.local`).
2. **DNS (dnsmasq)** возвращает IP-адрес внешнего прокси-сервера.
3. **Nginx** принимает запрос, терминирует SSL (опционально) и балансирует трафик между `NodePort` рабочих узлов (worker nodes) кластера.
4. **Ingress-контроллер** внутри кластера (например, Traefik или HAProxy) получает запрос от Nginx и направляет его в конкретный Pod.

**Преимущества:**

- Использование стандартных портов (80/443) для конечных пользователей.
- Понятные URL вместо комбинаций `IP:Port`.
- Централизованное управление именами через DNS.
- Отсутствие необходимости в поддержке ARP/BGP сетевым оборудованием.

### Сохранение IP-адреса клиента

Для того чтобы приложения внутри кластера видели реальный IP клиента, а не IP-адрес внешнего прокси, необходимо:
1. В Nginx настроить передачу заголовков `X-Forwarded-For` и `X-Real-IP`.
2. В Service типа `NodePort` (обычно это сервис Ingress-контроллера) установить `externalTrafficPolicy: Local`. Это исключает SNAT (Source Network Address Translation) при пересылке трафика между узлами.

---

## Практические сценарии

### Шаг 1 — настройка DNS (dnsmasq)

На выделенном сервере (обычно совмещенном с Nginx) создается конфигурация для локальной доменной зоны.

```bash
# Файл /etc/dnsmasq.d/k8s-local.conf
address=/myapp.k8s.local/192.168.1.100
address=/.k8s.local/192.168.1.100 # Wildcard для всех поддоменов
```

*Где `192.168.1.100` — IP-адрес сервера с Nginx.*

```bash
sudo systemctl restart dnsmasq
# → Job for dnsmasq.service started.

# Проверка резолвинга
dig @localhost myapp.k8s.local +short
# → 192.168.1.100
```

### Шаг 2 — настройка Nginx Proxy

Конфигурация Nginx как reverse proxy для балансировки трафика на NodePort Ingress-контроллера.

```nginx
# Файл /etc/nginx/conf.d/k8s-proxy.conf

# Группа рабочих узлов (worker-нод) кластера
# Указываем порты, на которых слушает Ingress-контроллер (NodePort)
upstream k8s-ingress {
    server 192.168.1.11:32080; # worker-node-1
    server 192.168.1.12:32080; # worker-node-2
    keepalive 32;
}

server {
    listen 80;
    server_name .k8s.local; # Принимать все запросы для этой зоны

    location / {
        proxy_pass http://k8s-ingress;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Настройки таймаутов для долгоживущих соединений (WebSocket)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

sudo systemctl reload nginx
# → Job for nginx.service reloaded.
```

### Шаг 3 — настройка Service в Kubernetes

Убедитесь, что сервис вашего Ingress-контроллера настроен на использование `externalTrafficPolicy: Local`.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx
spec:
  type: NodePort
  externalTrafficPolicy: Local # Сохранение исходного IP
  ports:
    - name: http
      port: 80
      targetPort: 80
      nodePort: 32080
    - name: https
      port: 443
      targetPort: 443
      nodePort: 32443
  selector:
    app.kubernetes.io/name: ingress-nginx
```

---

## Дополнительная информация

### Рекомендации

- **Автоматизация:** При расширении кластера новыми узлами необходимо обновлять секцию `upstream` в Nginx. Рекомендуется использовать Ansible или `nginx-upsync-module` для динамического обновления бэкендов.
- **Отказоустойчивость:** Для исключения Nginx как SPOF (Single Point of Failure — единая точка отказа) используйте `Keepalived` для создания плавающего IP (VIP) между двумя инстансами Nginx.
- **SSL-терминация:** Удобнее всего терминировать SSL на внешнем Nginx, используя `Certbot` (Let's Encrypt), чтобы не пробрасывать сертификаты внутрь кластера вручную.

**См. также:**

- [Обзор MetalLB](../metallb.md) — причины ограничения L2 режима.
- [NodePort в сервисах](../Service/service_type_nodeport.md) — детальное описание механизма NodePort и `externalTrafficPolicy`.
- [Ingress: обзор и концепции](./overview.md) — использование Ingress внутри кластера.
- [Gateway API](../gateway_api/migration.md) — современная замена Ingress в 2026 году.
